"""
User management (admin-only) and system status endpoints.

Real data throughout: user list/role changes hit the actual users table;
system status reflects the actual live state of Redis and SMTP
configuration (via cache.is_redis_backed() and email_service.SMTP_CONFIGURED)
rather than hardcoded claims.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth, cache, email_service
from ..database import get_db, DATABASE_URL

router = APIRouter(prefix="/api/users", tags=["users"])
system_router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin"))):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: str, payload: schemas.UserUpdate,
    db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_roles("admin")),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == current_user.id and payload.role is not None and payload.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot demote your own account")
    if target.id == current_user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    if payload.role is not None:
        if payload.role not in ("surveyor", "verifier", "admin"):
            raise HTTPException(status_code=400, detail="Invalid role")
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active

    db.commit()
    db.refresh(target)
    return target


def _mask_db_url(url: str) -> str:
    """Never expose credentials -- shows only the scheme + host shape."""
    if "sqlite" in url:
        return "sqlite:///./<local file>"
    if "@" in url:
        scheme = url.split("://")[0]
        host_part = url.split("@")[-1]
        return f"{scheme}://***:***@{host_part}"
    return url


@system_router.get("/status", response_model=schemas.SystemStatusOut)
def system_status(user: models.User = Depends(auth.require_roles("admin"))):
    return schemas.SystemStatusOut(
        redis_backed=cache.is_redis_backed(),
        smtp_configured=email_service.SMTP_CONFIGURED,
        database_type="postgresql" if "postgresql" in DATABASE_URL else "sqlite",
        database_url_masked=_mask_db_url(DATABASE_URL),
    )
