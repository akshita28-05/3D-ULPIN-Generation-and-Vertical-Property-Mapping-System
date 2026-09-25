"""
Rights, Restrictions & Responsibilities registry -- Layer 4 (3D Cadastral
Data Model & Registry) and Layer 5 (Services & APIs) of the architecture.

RRRs attach to a spatial unit (surface parcel, flat/unit, underground
asset, or air-right corridor) via spatial_unit_type + spatial_unit_id
rather than a dedicated FK per type -- this is what lets one registry
cover all four spatial-unit kinds the problem statement calls out
(surface parcels, multi-storey apartments, underground infrastructure,
air-rights), matching LADM's Basic Administrative Unit concept.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/api/rrr", tags=["rrr"])

_SPATIAL_UNIT_MODELS = {
    "parcel": models.Parcel,
    "unit": models.Unit,
    "underground_asset": models.UndergroundAsset,
    "air_right_corridor": models.AirRightCorridor,
}


def _validate_spatial_unit(db: Session, spatial_unit_type: str, spatial_unit_id: str):
    model = _SPATIAL_UNIT_MODELS.get(spatial_unit_type)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Unknown spatial_unit_type '{spatial_unit_type}'. Must be one of {list(_SPATIAL_UNIT_MODELS)}.")
    obj = db.query(model).filter(model.id == spatial_unit_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"No {spatial_unit_type} with id '{spatial_unit_id}'.")
    return obj


@router.post("/parties", response_model=schemas.PartyOut)
def create_party(payload: schemas.PartyCreate, db: Session = Depends(get_db),
                  user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin"))):
    if db.query(models.Party).filter(models.Party.reference_code == payload.reference_code).first():
        raise HTTPException(status_code=409, detail="A party with this reference_code already exists.")
    party = models.Party(**payload.model_dump())
    db.add(party)
    db.commit()
    db.refresh(party)
    return party


@router.get("/parties/{party_id}", response_model=schemas.PartyOut)
def get_party(party_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    party = db.query(models.Party).filter(models.Party.id == party_id).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


@router.patch("/parties/{party_id}", response_model=schemas.PartyOut)
def update_party(party_id: str, payload: dict, db: Session = Depends(get_db),
                  user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin"))):
    party = db.query(models.Party).filter(models.Party.id == party_id).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    for key, value in payload.items():
        if key in {"party_type", "display_label"}:
            setattr(party, key, value)
    db.commit()
    db.refresh(party)
    return party


@router.post("", response_model=schemas.RRROut)
def create_rrr(payload: schemas.RRRCreate, db: Session = Depends(get_db),
               user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin"))):
    """Attaches a right/restriction/responsibility to any spatial unit.
    Validates the spatial unit actually exists before attaching -- an RRR
    can never point at a fabricated/nonexistent parcel or flat."""
    _validate_spatial_unit(db, payload.spatial_unit_type, payload.spatial_unit_id)
    if payload.party_id and not db.query(models.Party).filter(models.Party.id == payload.party_id).first():
        raise HTTPException(status_code=404, detail="party_id does not exist")
    if not payload.right_type and not payload.restriction_type and not payload.responsibility_note:
        raise HTTPException(status_code=400, detail="Provide at least one of right_type, restriction_type, or responsibility_note.")

    rrr = models.RightRestrictionResponsibility(**payload.model_dump())
    db.add(rrr)
    db.commit()
    db.refresh(rrr)
    return rrr


@router.get("/{spatial_unit_type}/{spatial_unit_id}", response_model=list[schemas.RRROut])
def list_rrrs_for_spatial_unit(spatial_unit_type: str, spatial_unit_id: str, db: Session = Depends(get_db),
                                user: models.User = Depends(auth.get_current_user)):
    """All rights/restrictions/responsibilities attached to a given
    parcel / unit / underground_asset / air_right_corridor -- e.g. what
    GET /parcel/{ulpin} in the architecture doc would surface."""
    _validate_spatial_unit(db, spatial_unit_type, spatial_unit_id)
    return (
        db.query(models.RightRestrictionResponsibility)
        .options(joinedload(models.RightRestrictionResponsibility.party))
        .filter(
            models.RightRestrictionResponsibility.spatial_unit_type == spatial_unit_type,
            models.RightRestrictionResponsibility.spatial_unit_id == spatial_unit_id,
        )
        .all()
    )


@router.delete("/{rrr_id}")
def delete_rrr(rrr_id: str, db: Session = Depends(get_db),
               user: models.User = Depends(auth.require_roles("admin"))):
    rrr = db.query(models.RightRestrictionResponsibility).filter(models.RightRestrictionResponsibility.id == rrr_id).first()
    if not rrr:
        raise HTTPException(status_code=404, detail="RRR not found")
    db.delete(rrr)
    db.commit()
    return {"deleted": rrr_id}


@router.patch("/{rrr_id}", response_model=schemas.RRROut)
def update_rrr(rrr_id: str, payload: dict, db: Session = Depends(get_db),
               user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin"))):
    rrr = db.query(models.RightRestrictionResponsibility).filter(models.RightRestrictionResponsibility.id == rrr_id).first()
    if not rrr:
        raise HTTPException(status_code=404, detail="RRR not found")
    allowed = {"right_type", "restriction_type", "responsibility_note", "party_id", "start_date", "end_date"}
    if "party_id" in payload and payload["party_id"] and not db.query(models.Party).filter(models.Party.id == payload["party_id"]).first():
        raise HTTPException(status_code=404, detail="party_id does not exist")
    for key, value in payload.items():
        if key in allowed:
            setattr(rrr, key, value)
    db.commit()
    db.refresh(rrr)
    return rrr
