from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models, schemas, auth, email_service, cache
from ..database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TOKEN_VALID_MINUTES = 30


def _enforce_rate_limit(request: Request, action: str, max_requests: int, window_seconds: int):
    """Real Redis-backed rate limiting (IP + action scoped). Protects
    login/signup/forgot-password from brute-force and abuse at scale --
    correct even across multiple backend instances since the counter
    lives in Redis, not in each process's memory."""
    client_ip = request.client.host if request.client else "unknown"
    allowed = cache.rate_limit_check(f"{action}:{client_ip}", max_requests, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many {action} attempts. Please try again in a few minutes.",
        )


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit(request, "login", max_requests=10, window_seconds=60)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not auth.verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    access = auth.create_access_token(user)
    refresh = auth.create_refresh_token(user)
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return schemas.Token(access_token=access, refresh_token=refresh, role=role_val, name=user.name)


@router.post("/refresh", response_model=schemas.Token)
def refresh_token(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    data = auth.decode_token(payload.refresh_token, "refresh")
    user = db.query(models.User).filter(models.User.id == data.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    access = auth.create_access_token(user)
    refresh = auth.create_refresh_token(user)
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return schemas.Token(access_token=access, refresh_token=refresh, role=role_val, name=user.name)


@router.get("/me", response_model=schemas.UserOut)
def get_me(user: models.User = Depends(auth.get_current_user)):
    return user


@router.post("/signup", response_model=schemas.Token)
def signup(payload: schemas.SignupRequest, request: Request, db: Session = Depends(get_db)):
    """Public self-registration. Always creates a Surveyor account -- Verifier
    and Admin roles are never self-assignable; an existing Admin must promote
    an account via /auth/register. This is enforced here, not just hidden in
    the UI, so it holds even if someone calls the API directly."""
    _enforce_rate_limit(request, "signup", max_requests=5, window_seconds=300)
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = models.User(
        name=payload.name, email=payload.email,
        hashed_password=auth.hash_password(payload.password),
        role=models.RoleEnum.surveyor,
    )
    db.add(user)
    db.flush()

    email_service.notify_welcome(db, user)

    db.commit()
    db.refresh(user)

    access = auth.create_access_token(user)
    refresh = auth.create_refresh_token(user)
    return schemas.Token(access_token=access, refresh_token=refresh, role="surveyor", name=user.name)


@router.post("/register", response_model=schemas.UserOut)
def register_user(
    name: str, email: str, password: str, role: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Admin-only: create a new Surveyor/Verifier/Admin account."""
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if role not in ("surveyor", "verifier", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    new_user = models.User(name=name, email=email, hashed_password=auth.hash_password(password), role=role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/forgot-password")
def forgot_password(payload: schemas.ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """
    Always returns the same generic response whether or not the email is
    registered -- this prevents account enumeration (an attacker probing
    which emails have accounts). The reset token itself is only ever
    stored as a SHA-256 hash in the database; the raw token exists only in
    the outgoing email.
    """
    _enforce_rate_limit(request, "forgot-password", max_requests=5, window_seconds=300)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user:
        raw_token, hashed_token = auth.generate_reset_token()
        reset_record = models.PasswordResetToken(
            user_id=user.id, token_hash=hashed_token,
            expires_at=datetime.utcnow() + timedelta(minutes=RESET_TOKEN_VALID_MINUTES),
        )
        db.add(reset_record)
        email_service.notify_password_reset(db, user, raw_token)
        db.commit()

    return {"detail": "If an account exists for this email, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    token_hash = auth.hash_token(payload.token)
    record = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token_hash == token_hash,
        models.PasswordResetToken.used == False,
    ).first()

    if not record:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset token")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset token has expired")

    user = db.query(models.User).filter(models.User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = auth.hash_password(payload.new_password)
    record.used = True
    db.commit()
    return {"detail": "Password has been reset successfully. You can now sign in."}
