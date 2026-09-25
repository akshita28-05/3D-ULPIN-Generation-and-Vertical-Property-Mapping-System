"""
Cesium 3D Tiles generation + serving.

POST /api/tiles/parcels/{parcel_id}/rebuild regenerates that parcel's
tileset (all its buildings) as a background task -- same fire-and-poll
pattern as /api/processing/start, so a big parcel doesn't hold a worker
thread. The static files are served straight from disk at
/tiles/{parcel_id}/tileset.json (mounted in main.py), which a CesiumJS
Cesium3DTileset can point at directly.

This replaces shipping every building's full footprint_geojson on every
map pan/zoom (see /api/export/units.geojson, GisMap.jsx's current data
flow) with Cesium's own tile-based level-of-detail streaming.
"""
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db, SessionLocal
from ..tiles.build_tileset import build_tileset_for_parcel

router = APIRouter(prefix="/api/tiles", tags=["tiles"])

TILES_DIR = os.getenv("TILES_DIR", "./tiles_output")


def _rebuild(parcel_id: str):
    db = SessionLocal()
    try:
        parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
        if not parcel:
            return
        buildings = db.query(models.Building).filter(models.Building.parcel_id == parcel_id).all()
        build_tileset_for_parcel(parcel, buildings, os.path.join(TILES_DIR, parcel_id))
    finally:
        db.close()


@router.post("/parcels/{parcel_id}/rebuild")
def rebuild_parcel_tiles(
    parcel_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    if parcel.centroid_lat is None or parcel.centroid_lon is None:
        raise HTTPException(
            status_code=400,
            detail="Parcel has no centroid_lat/centroid_lon set -- needed to georeference the tileset. "
                   "Set the parcel's centroid before generating tiles.",
        )

    background_tasks.add_task(_rebuild, parcel_id)
    return {
        "parcel_id": parcel_id,
        "status": "queued",
        "tileset_url": f"/tiles/{parcel_id}/tileset.json",
        "note": "Tile generation runs in the background; poll tileset_url until it 200s.",
    }
