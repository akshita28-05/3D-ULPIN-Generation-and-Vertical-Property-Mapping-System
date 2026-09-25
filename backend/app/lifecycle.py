"""
Ownership lifecycle helpers: locked baselines + tamper detection.

When a verifier approves a unit, its geometry (footprint, z-range, type) is
hashed and that hash is written to the tamper-evident audit log as a
"unit.baseline_lock" entry. From then on:

  * the unit can't be edited in place (parcels_router / review_router return 409),
  * changes go through a ChangeRequest that the rights-holder must approve,
  * anyone can recompute the hash and compare -- if the stored geometry no
    longer matches the last locked baseline (e.g. someone edited the database
    directly) the public passport shows a TAMPER WARNING.

No new columns: the baseline lives in the existing audit log, so this works on
databases that were created before this feature existed.
"""
import hashlib
import json

from sqlalchemy.orm import Session

from . import models

BASELINE_ACTION = "unit.baseline_lock"


def geometry_hash(unit) -> str:
    payload = json.dumps({
        "footprint": unit.footprint_geojson,
        "z_min": round(unit.z_min, 3) if unit.z_min is not None else None,
        "z_max": round(unit.z_max, 3) if unit.z_max is not None else None,
        "type": unit.parcel_type,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def is_locked(unit) -> bool:
    status = unit.verification_status.value if hasattr(unit.verification_status, "value") else unit.verification_status
    return status == "approved"


def lock_baseline(db: Session, unit, user_id):
    from .routers.review_router import write_audit
    write_audit(db, user_id, BASELINE_ACTION, "unit", unit.id, "", geometry_hash(unit))


def latest_baseline(db: Session, unit_id: str):
    return (
        db.query(models.AuditLog)
        .filter(models.AuditLog.action == BASELINE_ACTION, models.AuditLog.entity_id == unit_id)
        .order_by(models.AuditLog.created_at.desc())
        .first()
    )


def integrity(db: Session, unit) -> dict:
    """{locked, baseline_hash, current_hash, tampered, locked_at}"""
    baseline = latest_baseline(db, unit.id)
    current = geometry_hash(unit)
    locked = is_locked(unit)
    return {
        "locked": locked,
        "baseline_hash": baseline.new_value if baseline else None,
        "current_hash": current,
        "locked_at": baseline.created_at.isoformat() if baseline and baseline.created_at else None,
        "tampered": bool(locked and baseline and baseline.new_value != current),
        "has_baseline": baseline is not None,
    }


LOCKED_MESSAGE = (
    "This unit is a verified, locked baseline and can't be edited in place. "
    "Submit a change request -- the owner approves it, then an officer applies it."
)
