"""
One-click automation: "Auto-map this view".

The officer pans/zooms the 3D map to an area and presses one button. This
endpoint picks the data source itself, starts the same background import job
the Bulk Import panel uses, and the job then runs the whole pipeline (see
auto_pipeline.py) with no further input:

    fetch footprints -> parcels/buildings + deterministic 2D ULPIN
      -> floor evidence (OBSERVED / PREDICTED / NOT_DETERMINABLE)
      -> floors -> units -> 3D ULPINs -> topology + anomaly validation
      -> verifier review queue

Source selection ("auto"):
  * if the local Microsoft footprints table has data for this area, use it --
    dense, works with no internet, and it is the data you loaded for this region;
  * otherwise query OpenStreetMap live (Overpass).
"""
import math

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from . import bulk_import_router

router = APIRouter(prefix="/api/auto", tags=["auto"])

MAX_AREA_SQKM = 25.0


class AutoRunRequest(BaseModel):
    south: float
    west: float
    north: float
    east: float
    search_query: str | None = None


def _area_sqkm(s, w, n, e):
    mid_lat = math.radians((s + n) / 2)
    return abs(n - s) * 111.32 * abs(e - w) * 111.32 * math.cos(mid_lat)


@router.post("/run")
def auto_run(
    payload: AutoRunRequest, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    if not (-90 <= payload.south < payload.north <= 90 and -180 <= payload.west < payload.east <= 180):
        raise HTTPException(status_code=422, detail="Invalid bounding box.")
    area = _area_sqkm(payload.south, payload.west, payload.north, payload.east)
    if area > MAX_AREA_SQKM:
        raise HTTPException(status_code=422, detail=f"That view covers ~{area:.0f} sq km. Zoom in to under {MAX_AREA_SQKM:.0f} sq km and try again.")

    has_local = (
        db.query(models.ExternalBuildingFootprint.id)
        .filter(
            models.ExternalBuildingFootprint.centroid_lat.between(payload.south, payload.north),
            models.ExternalBuildingFootprint.centroid_lon.between(payload.west, payload.east),
        )
        .first()
    ) is not None
    source = "ms_footprints" if has_local else "osm"

    job = models.BulkImportJob(
        started_by=user.id, status="pending",
        south=payload.south, west=payload.west, north=payload.north, east=payload.east,
        search_query=payload.search_query, source=source,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(bulk_import_router._run_bulk_import, job.id)
    return {"job_id": job.id, "status": job.status, "source": source, "area_sqkm": round(area, 2)}
