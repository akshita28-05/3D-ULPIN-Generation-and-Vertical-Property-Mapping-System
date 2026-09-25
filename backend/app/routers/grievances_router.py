import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth, email_service, cache
from ..database import get_db

router = APIRouter(prefix="/api/grievances", tags=["grievances"])


def _next_grievance_number(db: Session) -> str:
    year = datetime.utcnow().year
    count = db.query(models.Grievance).filter(models.Grievance.grievance_number.like(f"GRV-{year}-%")).count()
    return f"GRV-{year}-{count + 1:05d}"


@router.post("", response_model=schemas.GrievanceOut)
def submit_grievance(payload: schemas.GrievanceCreate, db: Session = Depends(get_db)):
    """Public endpoint — any citizen can submit, no auth required."""
    grievance = models.Grievance(
        grievance_number=_next_grievance_number(db),
        unit_id=payload.unit_id, building_id=payload.building_id, category=payload.category,
        description=payload.description, reporter_contact=payload.reporter_contact,
        status=models.GrievanceStatus.submitted,
    )
    db.add(grievance)
    db.commit()
    db.refresh(grievance)
    return grievance


@router.get("/track/{grievance_number}", response_model=schemas.GrievanceOut)
def track_grievance(grievance_number: str, db: Session = Depends(get_db)):
    g = db.query(models.Grievance).filter(models.Grievance.grievance_number == grievance_number).first()
    if not g:
        raise HTTPException(status_code=404, detail="Grievance not found")
    return g


@router.get("", response_model=list[schemas.GrievanceOut])
def list_grievances(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")), limit: int = 200, offset: int = 0):
    limit = min(limit, 500)
    return db.query(models.Grievance).order_by(models.Grievance.created_at.desc()).offset(offset).limit(limit).all()


@router.patch("/{grievance_id}", response_model=schemas.GrievanceOut)
def update_grievance(
    grievance_id: str, payload: schemas.GrievanceStatusUpdate,
    db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin", "verifier")),
):
    g = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Grievance not found")
    if payload.status not in [s.value for s in models.GrievanceStatus]:
        raise HTTPException(status_code=400, detail="Invalid status")
    g.status = payload.status
    if payload.assigned_to:
        g.assigned_to = payload.assigned_to
    g.updated_at = datetime.utcnow()

    if g.reporter_contact:
        email_service.notify_grievance_status_changed(db, g)

    db.commit()
    db.refresh(g)
    cache.cache_invalidate("analytics:")
    return g
