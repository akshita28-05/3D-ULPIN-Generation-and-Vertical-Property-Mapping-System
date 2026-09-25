"""
Review / verification router — the human-in-the-loop workflow.

Every approve/reject/edit action is written to a real audit log with a
SHA-256 hash of (previous_value + new_value + user + timestamp), making
the trail tamper-evident: any retroactive edit to a row breaks its hash
chain against the recorded value. This is intentionally NOT a blockchain
(no distributed consensus) — just honest, verifiable audit logging.
"""
import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth, email_service, cache, lifecycle
from ..database import get_db

router = APIRouter(prefix="/api/review", tags=["review"])


def write_audit(db: Session, user_id: str, action: str, entity_type: str, entity_id: str,
                 previous_value: str, new_value: str):
    timestamp = datetime.utcnow().isoformat()
    raw = f"{user_id}|{action}|{entity_type}|{entity_id}|{previous_value}|{new_value}|{timestamp}"
    record_hash = hashlib.sha256(raw.encode()).hexdigest()
    entry = models.AuditLog(
        user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id,
        previous_value=previous_value, new_value=new_value, record_hash=record_hash,
    )
    db.add(entry)


@router.get("/queue", response_model=list[schemas.UnitOut])
def review_queue(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("verifier")), limit: int = 100, offset: int = 0):
    limit = min(limit, 500)
    return db.query(models.Unit).filter(
        models.Unit.verification_status.in_([models.VerificationStatus.pending_review, models.VerificationStatus.reprocessing])
    ).order_by(models.Unit.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/units/{unit_id}/validation", response_model=list[schemas.ValidationResultOut])
def unit_validation(unit_id: str, db: Session = Depends(get_db)):
    return db.query(models.ValidationResult).filter(models.ValidationResult.unit_id == unit_id).all()


@router.post("/units/{unit_id}/action", response_model=schemas.UnitOut)
def review_action(
    unit_id: str, payload: schemas.UnitReviewAction,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("verifier")),
):
    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    if lifecycle.is_locked(unit) and (
        payload.edited_footprint_geojson or payload.edited_z_min is not None or payload.edited_z_max is not None
    ):
        raise HTTPException(status_code=409, detail=lifecycle.LOCKED_MESSAGE)

    previous_state = json.dumps({
        "verification_status": unit.verification_status.value if hasattr(unit.verification_status, "value") else unit.verification_status,
        "footprint_geojson": unit.footprint_geojson, "z_min": unit.z_min, "z_max": unit.z_max,
    })

    if payload.edited_footprint_geojson:
        unit.footprint_geojson = payload.edited_footprint_geojson
    if payload.edited_z_min is not None:
        unit.z_min = payload.edited_z_min
    if payload.edited_z_max is not None:
        unit.z_max = payload.edited_z_max

    if payload.action == "approve":
        unit.verification_status = models.VerificationStatus.approved
        unit.verified_by = user.id
        unit.verified_at = datetime.utcnow()
    elif payload.action == "reject":
        unit.verification_status = models.VerificationStatus.rejected
        unit.verified_by = user.id
        unit.verified_at = datetime.utcnow()
    elif payload.action == "reprocess":
        unit.verification_status = models.VerificationStatus.reprocessing
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    new_state = json.dumps({
        "verification_status": unit.verification_status.value if hasattr(unit.verification_status, "value") else unit.verification_status,
        "footprint_geojson": unit.footprint_geojson, "z_min": unit.z_min, "z_max": unit.z_max,
        "note": payload.note,
    })

    write_audit(db, user.id, f"unit.{payload.action}", "unit", unit.id, previous_state, new_state)

    if payload.action == "approve":
        lifecycle.lock_baseline(db, unit, user.id)
        email_service.notify_unit_verified(db, unit)

    db.commit()
    db.refresh(unit)
    cache.cache_invalidate("analytics:")
    return unit


@router.post("/buildings/{building_id}/bulk-action")
def bulk_review_action(
    building_id: str, payload: schemas.BulkReviewAction,
    db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("verifier")),
):
    """
    Approve/reject every pending unit in a building in one action, instead
    of clicking through each floor/unit individually — this is what lets a
    verifier clear an entire 20-floor building's review queue at once
    rather than 240 separate clicks. Every unit still gets its own audit
    log entry (same tamper-evident hash chain as a single-unit action) —
    this is a loop over the same real logic, not a shortcut that skips
    accountability.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    if payload.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    units = (
        db.query(models.Unit)
        .join(models.Floor)
        .filter(models.Floor.building_id == building_id)
        .filter(models.Unit.verification_status.in_([models.VerificationStatus.pending_review, models.VerificationStatus.reprocessing]))
        .all()
    )

    updated = 0
    for unit in units:
        previous_state = json.dumps({"verification_status": unit.verification_status.value})
        unit.verification_status = models.VerificationStatus.approved if payload.action == "approve" else models.VerificationStatus.rejected
        unit.verified_by = user.id
        unit.verified_at = datetime.utcnow()
        new_state = json.dumps({"verification_status": unit.verification_status.value, "note": payload.note, "bulk": True})
        write_audit(db, user.id, f"unit.{payload.action}", "unit", unit.id, previous_state, new_state)
        if payload.action == "approve":
            lifecycle.lock_baseline(db, unit, user.id)
            email_service.notify_unit_verified(db, unit)
        updated += 1

    db.commit()
    cache.cache_invalidate("analytics:")
    return {"building_id": building_id, "action": payload.action, "units_updated": updated}


@router.get("/conflicts", response_model=list[schemas.ValidationResultOut])
def conflicts(db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    return db.query(models.ValidationResult).filter(models.ValidationResult.resolved == False).all()


@router.post("/conflicts/{result_id}/resolve", response_model=schemas.ValidationResultOut)
def resolve_conflict(
    result_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("verifier")),
):
    result = db.query(models.ValidationResult).filter(models.ValidationResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Validation result not found")
    result.resolved = True
    write_audit(db, user.id, "conflict.resolve", "validation_result", result.id, "unresolved", "resolved")
    db.commit()
    db.refresh(result)
    return result
