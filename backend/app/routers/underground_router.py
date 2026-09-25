"""
Underground utility AUTO-DETECTION endpoints -- kept separate from
assets_router.py's manual CRUD (POST /api/assets/underground-assets) on
purpose: manual assertion and automatic detection are two different
workflows that both need to keep working independently, per the project's
disclosed pattern of "real model when available, real manual fallback
otherwise."

Three stages, each independently callable and independently disclosed:
  1. POST /api/underground/detect-surface-assets  -- YOLO on drone orthophoto (manholes/valve boxes)
  2. POST /api/underground/detect-gpr              -- hyperbola detection on one GPR B-scan + real depth physics
  3. POST /api/underground/fuse                    -- clusters raw GPR detections into utility traces, tags quality level, PERSISTS as UndergroundAsset rows

See ai/underground/{surface_assets,gpr_detection,fusion}.py for the actual
detection/fusion logic -- this file is just the HTTP surface over it.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth
from ..ai.underground import surface_assets, gpr_detection, fusion
from ..database import get_db

router = APIRouter(prefix="/api/underground", tags=["underground-detection"])
logger = logging.getLogger("landsphere.routers.underground")


class DetectSurfaceAssetsRequest(BaseModel):
    image_path: str
    origin_x: float = 0.0
    origin_y: float = 0.0


class ScanLine(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    time_window_ns: float
    dielectric_constant: float | None = None
    origin_lat: float
    origin_lon: float


class DetectGprRequest(BaseModel):
    bscan_image_path: str
    scan_line: ScanLine
    image_width_px: int
    image_height_px: int


class FuseAndPersistRequest(BaseModel):
    parcel_id: str
    utility_type: str
    gpr_points: list
    surface_asset_points: list = []
    eps_m: float = 2.0
    min_samples: int = 3
    snap_radius_m: float = 3.0


@router.post("/detect-surface-assets")
def detect_surface_assets_endpoint(
    payload: DetectSurfaceAssetsRequest,
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Runs YOLO-based manhole/valve-box/chamber detection on a drone
    orthophoto. Returns the raw detections (not persisted) -- pass the
    result into POST /fuse's surface_asset_points to let GPR traces snap
    to them, or persist selected ones yourself via the manual
    POST /api/assets/underground-assets endpoint if you want them stored
    as their own asset records.
    """
    detections = surface_assets.detect_surface_assets(payload.image_path, origin_xy=(payload.origin_x, payload.origin_y))
    if detections is None:
        raise HTTPException(
            status_code=422,
            detail="Surface asset detection unavailable -- check SURFACE_ASSET_MODEL_ENABLED, "
                   "SURFACE_ASSET_WEIGHTS_PATH, and that the image exists. See ai/underground/surface_assets.py.",
        )
    return {"count": len(detections), "detections": detections}


@router.post("/detect-gpr")
def detect_gpr_endpoint(
    payload: DetectGprRequest,
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Runs hyperbola detection on ONE GPR B-scan image and converts each
    detection to a real 3D position using the scan line's actual GNSS
    trajectory + radar depth physics. A real utility survey covers an
    area with multiple parallel scan lines -- call this once per B-scan,
    accumulate the returned points client-side, and pass the full set
    into POST /fuse.
    """
    scan_line_dict = payload.scan_line.model_dump(exclude_none=True)
    result = gpr_detection.process_gpr_survey_line(
        payload.bscan_image_path, scan_line_dict, payload.image_width_px, payload.image_height_px,
    )
    if result is None:
        raise HTTPException(
            status_code=422,
            detail="GPR detection unavailable -- check GPR_MODEL_ENABLED, GPR_HYPERBOLA_WEIGHTS_PATH, "
                   "and that the B-scan image exists. See ai/underground/gpr_detection.py.",
        )
    return {"count": len(result), "detections": result}


@router.post("/fuse")
def fuse_and_persist_endpoint(
    payload: FuseAndPersistRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Clusters accumulated GPR detections (from repeated /detect-gpr calls)
    into utility traces, tags each with a real PAS 128 / ASCE 38 quality
    level, and PERSISTS them as UndergroundAsset rows with
    source="gpr_detected". Returns [] (and persists nothing) if there
    weren't enough detections to form a trace -- never fabricates a
    utility run from insufficient data.
    """
    if not db.query(models.Parcel).filter(models.Parcel.id == payload.parcel_id).first():
        raise HTTPException(status_code=404, detail="Parcel not found")
    if len(payload.gpr_points) < payload.min_samples:
        raise HTTPException(status_code=400, detail=f"Need at least {payload.min_samples} GPR detection points to fuse (got {len(payload.gpr_points)}).")

    traces = fusion.fuse_gpr_survey(
        payload.gpr_points, payload.utility_type, surface_assets=payload.surface_asset_points,
        eps_m=payload.eps_m, min_samples=payload.min_samples, snap_radius_m=payload.snap_radius_m,
    )

    created = []
    for trace in traces:
        asset = models.UndergroundAsset(
            parcel_id=payload.parcel_id,
            asset_type=trace["asset_type"],
            depth_min_m=trace["depth_min_m"],
            depth_max_m=trace["depth_max_m"],
            geometry_geojson=json.dumps(trace["geometry_geojson_points"]),
            source=trace["source"],
            quality_level=trace["quality_level"],
            detection_confidence=trace["detection_confidence"],
        )
        db.add(asset)
        created.append(asset)
    db.commit()
    for asset in created:
        db.refresh(asset)

    return {
        "parcel_id": payload.parcel_id,
        "traces_created": len(created),
        "assets": [
            {
                "id": a.id, "asset_type": a.asset_type,
                "quality_level": a.quality_level.value if hasattr(a.quality_level, "value") else a.quality_level,
                "detection_confidence": a.detection_confidence, "depth_min_m": a.depth_min_m, "depth_max_m": a.depth_max_m,
            }
            for a in created
        ],
    }
