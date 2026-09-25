"""Underground + air-rights auto-discovery endpoints (no sensors, no manual entry).

    POST /api/infra/scan   scan the area under the map view in open data (public, cached, throttled by grid cell)
    POST /api/infra/link   attach discovered structures to registered parcels (officers)

The read side for the map is GET /api/map/infrastructure (routers/map_router.py).
See app/infra/ for what is real and what is assumed.
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..infra import service

router = APIRouter(prefix="/api/infra", tags=["infrastructure"])

MAX_AREA_SQKM = 60.0


class BBox(BaseModel):
    south: float
    west: float
    north: float
    east: float


def _check(b: BBox):
    if not (-90 <= b.south < b.north <= 90 and -180 <= b.west < b.east <= 180):
        raise HTTPException(status_code=422, detail="Invalid bounding box.")
    mid = math.radians((b.south + b.north) / 2)
    area = (b.north - b.south) * 111.32 * (b.east - b.west) * 111.32 * math.cos(mid)
    return area


@router.post("/scan")
def scan(payload: BBox, db: Session = Depends(get_db)):
    area = _check(payload)
    if area > MAX_AREA_SQKM:
        return {"status": "zoom_in", "cells": 0, "scanned": 0, "cached": 0, "failed": 0, "added": 0,
                "message": "Zoom in a little to scan this area for underground and elevated structures."}
    return service.scan_bbox(db, payload.south, payload.west, payload.north, payload.east)


@router.post("/link")
def link(
    payload: BBox, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    _check(payload)
    result = service.scan_and_link(db, payload.south, payload.west, payload.north, payload.east)
    return result


@router.get("/parcel/{parcel_id}")
def parcel_infra(
    parcel_id: str,
    radius_m: float = Query(120.0, ge=20.0, le=400.0),
    scan: bool = Query(True, description="scan the surrounding open-data cells first if they have not been scanned yet"),
    db: Session = Depends(get_db),
):
    """Underground structures and air-right corridors around one parcel, in the parcel's own
    local-metre frame, for the per-parcel 3D viewer. Same store as the map layers
    (GET /api/map/infrastructure) -- nothing generated. Public, like the map."""
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if parcel is None:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return service.parcel_infrastructure(db, parcel, radius_m=radius_m, scan=scan)
