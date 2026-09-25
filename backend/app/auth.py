"""
Authentication & authorization.

Real JWT access + refresh tokens, bcrypt password hashing, and
role-based dependencies that are enforced server-side on every
protected route (never trust a frontend-only role check).
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import List

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from . import models

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_use_a_long_random_secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire, "type": token_type})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user: models.User) -> str:
    return create_token(
        {"sub": user.id, "role": user.role.value if hasattr(user.role, "value") else user.role},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(user: models.User) -> str:
    return create_token({"sub": user.id}, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    payload = decode_token(token, "access")
    user_id = payload.get("sub")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_roles(*allowed_roles: str):
    """
    Dependency factory enforcing RBAC on the backend. Use as:
      Depends(require_roles("admin", "verifier"))
    Admin implicitly passes every check.
    """
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        role_val = user.role.value if hasattr(user.role, "value") else user.role
        if role_val == "admin" or role_val in allowed_roles:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role_val}' is not permitted to perform this action",
        )
    return checker


def generate_reset_token() -> tuple[str, str]:
    """Returns (raw_token, hashed_token). The raw token is what goes in the
    email link; only the hash is stored in the database, so a database leak
    alone can't be used to reset accounts (same principle as password
    hashing)."""
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()
