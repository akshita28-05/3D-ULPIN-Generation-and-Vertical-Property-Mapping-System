"""
Ownership lifecycle API: property passport, change requests, owner consent.

  GET  /api/lifecycle/units/{id}/passport          public -- what the QR code opens
  POST /api/lifecycle/change-requests              officer proposes a change to a LOCKED unit
  GET  /api/lifecycle/change-requests              officers -- list
  GET  /api/lifecycle/owner/{token}                public, one-time link -- what the owner sees
  POST /api/lifecycle/owner/{token}/decision       public, one-time link -- owner approves/declines
  POST /api/lifecycle/change-requests/{id}/apply   verifier/admin -- apply an owner-approved change
  POST /api/lifecycle/change-requests/{id}/reject  verifier/admin

There are no citizen accounts in this prototype, so the owner's consent is a
random one-time link (only its SHA-256 is stored). In production this would sit
behind Aadhaar/DigiLocker-style identity -- stated, not hidden.
"""
import hashlib
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth, cache, lifecycle
from ..database import get_db
from .review_router import write_audit

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])

EDITABLE_FIELDS = {"footprint_geojson", "z_min", "z_max", "parcel_type"}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _status(req) -> str:
    return req.status.value if hasattr(req.status, "value") else req.status


def _unit_or_404(db, unit_id):
    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


def _request_out(req, unit=None, token=None):
    unit = unit or req.unit
    proposed = json.loads(req.proposed_json or "{}")
    current = {k: getattr(unit, k) for k in proposed}
    out = {
        "id": req.id, "unit_id": req.unit_id, "ulpin_3d": unit.ulpin_3d,
        "change_type": req.change_type, "reason": req.reason, "status": _status(req),
        "proposed": proposed, "current": current,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "owner_decided_at": req.owner_decided_at.isoformat() if req.owner_decided_at else None,
        "applied_at": req.applied_at.isoformat() if req.applied_at else None,
        "officer_note": req.officer_note,
    }
    if token:
        out["owner_link_path"] = f"/owner-approve/{token}"
    return out


@router.get("/units/{unit_id}/passport")
def property_passport(unit_id: str, db: Session = Depends(get_db)):
    unit = _unit_or_404(db, unit_id)
    floor = unit.floor
    building = floor.building if floor else None
    parcel = building.parcel if building else None
    open_requests = db.query(models.ChangeRequest).filter(
        models.ChangeRequest.unit_id == unit.id,
        models.ChangeRequest.status.in_([models.ChangeRequestStatus.pending_owner, models.ChangeRequestStatus.owner_approved]),
    ).count()
    from ..auto_pipeline import floor_evidence_state, floor_method_label
    return {
        "unit_id": unit.id, "ulpin_3d": unit.ulpin_3d,
        "ulpin_2d": parcel.ulpin_2d if parcel else None,
        "parcel_id": parcel.id if parcel else None,
        "parcel_type": unit.parcel_type, "area_sqm": unit.area_sqm, "volume_cum": unit.volume_cum,
        "z_min": unit.z_min, "z_max": unit.z_max,
        "floor_code": floor.floor_code if floor else None,
        "building_code": building.building_code if building else None,
        "building_name": building.name if building else None,
        "floor_state": floor_evidence_state(building) if building else None,
        "floor_method": floor_method_label(building) if building else None,
        "verification_status": unit.verification_status.value if hasattr(unit.verification_status, "value") else unit.verification_status,
        "verified_at": unit.verified_at.isoformat() if unit.verified_at else None,
        "integrity": lifecycle.integrity(db, unit),
        "open_change_requests": open_requests,
        "disclaimer": "Proposed 3D spatial identifier for the SIH prototype -- not an official DoLR ULPIN issuance.",
    }


class ChangeRequestCreate(BaseModel):
    unit_id: str
    change_type: str = "geometry"
    proposed: dict
    reason: str | None = None


@router.post("/change-requests")
def create_change_request(
    payload: ChangeRequestCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    unit = _unit_or_404(db, payload.unit_id)
    if not lifecycle.is_locked(unit):
        raise HTTPException(status_code=400, detail="This unit isn't a locked baseline yet -- edit it directly, or approve it first.")
    proposed = {k: v for k, v in payload.proposed.items() if k in EDITABLE_FIELDS}
    if not proposed:
        raise HTTPException(status_code=422, detail=f"Nothing to change. Editable fields: {sorted(EDITABLE_FIELDS)}")
    z_min = proposed.get("z_min", unit.z_min)
    z_max = proposed.get("z_max", unit.z_max)
    if z_min is not None and z_max is not None and z_min >= z_max:
        raise HTTPException(status_code=422, detail="z_min must be less than z_max")
    if "footprint_geojson" in proposed and not isinstance(proposed["footprint_geojson"], str):
        proposed["footprint_geojson"] = json.dumps(proposed["footprint_geojson"])

    token = secrets.token_urlsafe(24)
    req = models.ChangeRequest(
        unit_id=unit.id, requested_by=user.id, change_type=payload.change_type,
        proposed_json=json.dumps(proposed), reason=payload.reason,
        status=models.ChangeRequestStatus.pending_owner, owner_token_hash=_hash_token(token),
    )
    db.add(req)
    write_audit(db, user.id, "unit.change_requested", "unit", unit.id, "", json.dumps({"proposed": list(proposed), "reason": payload.reason}))
    db.commit()
    db.refresh(req)
    return _request_out(req, unit, token=token)


@router.get("/change-requests")
def list_change_requests(
    status: str | None = None, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
    limit: int = 200,
):
    q = db.query(models.ChangeRequest)
    if status:
        try:
            q = q.filter(models.ChangeRequest.status == models.ChangeRequestStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown status")
    return [_request_out(r) for r in q.order_by(models.ChangeRequest.created_at.desc()).limit(min(limit, 500)).all()]


def _by_token_or_404(db, token):
    req = db.query(models.ChangeRequest).filter(models.ChangeRequest.owner_token_hash == _hash_token(token)).first()
    if not req:
        raise HTTPException(status_code=404, detail="This approval link is invalid or has already been used.")
    return req


def _rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not cache.rate_limit_check(f"owner-link:{ip}", 30, 60):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a minute.")


@router.get("/owner/{token}")
def owner_view(token: str, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request)
    return _request_out(_by_token_or_404(db, token))


class OwnerDecision(BaseModel):
    approve: bool


@router.post("/owner/{token}/decision")
def owner_decision(token: str, payload: OwnerDecision, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request)
    req = _by_token_or_404(db, token)
    if req.status != models.ChangeRequestStatus.pending_owner:
        raise HTTPException(status_code=409, detail=f"This request is already '{_status(req)}'.")
    req.status = models.ChangeRequestStatus.owner_approved if payload.approve else models.ChangeRequestStatus.owner_declined
    req.owner_decided_at = datetime.utcnow()
    write_audit(db, None, "unit.owner_" + ("approved" if payload.approve else "declined"), "unit", req.unit_id, "", req.id)
    db.commit()
    db.refresh(req)
    return _request_out(req)


class OfficerNote(BaseModel):
    note: str | None = None


@router.post("/change-requests/{request_id}/apply")
def apply_change_request(
    request_id: str, payload: OfficerNote, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("verifier")),
):
    req = db.query(models.ChangeRequest).filter(models.ChangeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Change request not found")
    if req.status != models.ChangeRequestStatus.owner_approved:
        raise HTTPException(status_code=409, detail="Only owner-approved requests can be applied.")
    unit = req.unit
    proposed = json.loads(req.proposed_json)
    before = {k: getattr(unit, k) for k in proposed}
    for key, value in proposed.items():
        if key in EDITABLE_FIELDS:
            setattr(unit, key, value)
    req.status = models.ChangeRequestStatus.applied
    req.applied_by, req.applied_at, req.officer_note = user.id, datetime.utcnow(), payload.note
    write_audit(db, user.id, "unit.change_applied", "unit", unit.id, json.dumps(before), json.dumps({**proposed, "note": payload.note}))
    lifecycle.lock_baseline(db, unit, user.id)
    db.commit()
    db.refresh(req)
    return _request_out(req)


@router.post("/change-requests/{request_id}/reject")
def reject_change_request(
    request_id: str, payload: OfficerNote, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("verifier")),
):
    req = db.query(models.ChangeRequest).filter(models.ChangeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Change request not found")
    if req.status in (models.ChangeRequestStatus.applied, models.ChangeRequestStatus.rejected):
        raise HTTPException(status_code=409, detail=f"Already '{_status(req)}'.")
    req.status = models.ChangeRequestStatus.rejected
    req.officer_note = payload.note
    write_audit(db, user.id, "unit.change_rejected", "unit", req.unit_id, "", json.dumps({"note": payload.note}))
    db.commit()
    db.refresh(req)
    return _request_out(req)
