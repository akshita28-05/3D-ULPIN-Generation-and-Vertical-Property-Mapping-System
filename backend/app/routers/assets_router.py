import json
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from .. import models, auth, schemas
from ..ai.registration import alignment as registration
from ..database import get_db

router = APIRouter(prefix="/api", tags=["assets"])

ALLOWED_EXTENSIONS = {"geojson", "csv", "tif", "tiff", "las", "laz", "json", "png", "jpg", "jpeg", "pdf"}
MAX_FILE_SIZE_MB = 50


class UndergroundAssetCreate(BaseModel):
    parcel_id: str
    asset_type: str
    depth_min_m: float
    depth_max_m: float
    geometry_geojson: str
    source: str = "manual"
    quality_level: str = "QL-D"


class AirRightCorridorCreate(BaseModel):
    parcel_id: str
    corridor_type: str
    height_min_m: float
    height_max_m: float
    geometry_geojson: str
    conflict_status: str = "none"
    source: str = "manual"
    detection_confidence: float | None = None
    height_source: str | None = None


@router.post("/underground-assets")
def create_underground_asset(
    payload: UndergroundAssetCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    if not db.query(models.Parcel).filter(models.Parcel.id == payload.parcel_id).first():
        raise HTTPException(status_code=404, detail="Parcel not found")
    try:
        pts = json.loads(payload.geometry_geojson)
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="geometry_geojson must be a JSON array of at least 3 [x,y] points")
    if payload.depth_min_m < 0 or payload.depth_max_m < 0:
        raise HTTPException(status_code=400, detail="Depths must be positive metres below ground (e.g. min=1.5, max=3)")
    if payload.depth_min_m >= payload.depth_max_m:
        raise HTTPException(status_code=400, detail="depth_min_m must be less than depth_max_m (e.g. min=1.5, max=3)")

    asset = models.UndergroundAsset(
        parcel_id=payload.parcel_id, asset_type=payload.asset_type,
        depth_min_m=payload.depth_min_m, depth_max_m=payload.depth_max_m,
        geometry_geojson=payload.geometry_geojson,
        source=payload.source, quality_level=payload.quality_level,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {
        "id": asset.id, "parcel_id": asset.parcel_id, "asset_type": asset.asset_type,
        "depth_min_m": asset.depth_min_m, "depth_max_m": asset.depth_max_m,
        "geometry_geojson": asset.geometry_geojson,
    }


@router.post("/air-rights")
def create_air_right_corridor(
    payload: AirRightCorridorCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    if not db.query(models.Parcel).filter(models.Parcel.id == payload.parcel_id).first():
        raise HTTPException(status_code=404, detail="Parcel not found")
    try:
        pts = json.loads(payload.geometry_geojson)
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="geometry_geojson must be a JSON array of at least 3 [x,y] points")
    if payload.height_max_m <= payload.height_min_m:
        raise HTTPException(status_code=400, detail="height_max_m must be greater than height_min_m")

    corridor = models.AirRightCorridor(
        parcel_id=payload.parcel_id, corridor_type=payload.corridor_type,
        height_min_m=payload.height_min_m, height_max_m=payload.height_max_m,
        geometry_geojson=payload.geometry_geojson, conflict_status=payload.conflict_status,
        source=payload.source, detection_confidence=payload.detection_confidence, height_source=payload.height_source,
    )
    db.add(corridor)
    db.commit()
    db.refresh(corridor)
    return {
        "id": corridor.id, "parcel_id": corridor.parcel_id, "corridor_type": corridor.corridor_type,
        "height_min_m": corridor.height_min_m, "height_max_m": corridor.height_max_m,
        "geometry_geojson": corridor.geometry_geojson, "conflict_status": corridor.conflict_status,
    }


@router.patch("/underground-assets/{asset_id}")
def update_underground_asset(
    asset_id: str, payload: dict, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    asset = db.query(models.UndergroundAsset).filter(models.UndergroundAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Underground asset not found")
    allowed = {"asset_type", "depth_min_m", "depth_max_m", "geometry_geojson"}
    for key, value in payload.items():
        if key in allowed:
            setattr(asset, key, value)
    if asset.depth_min_m is not None and asset.depth_max_m is not None and asset.depth_min_m >= asset.depth_max_m:
        db.rollback()
        raise HTTPException(status_code=400, detail="depth_min_m must be less than depth_max_m")
    db.commit()
    db.refresh(asset)
    return {
        "id": asset.id, "parcel_id": asset.parcel_id, "asset_type": asset.asset_type,
        "depth_min_m": asset.depth_min_m, "depth_max_m": asset.depth_max_m,
        "geometry_geojson": asset.geometry_geojson,
    }


@router.delete("/underground-assets/{asset_id}")
def delete_underground_asset(
    asset_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    asset = db.query(models.UndergroundAsset).filter(models.UndergroundAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Underground asset not found")
    db.delete(asset)
    db.commit()
    return {"deleted": asset_id}


@router.patch("/air-rights/{corridor_id}")
def update_air_right_corridor(
    corridor_id: str, payload: dict, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    corridor = db.query(models.AirRightCorridor).filter(models.AirRightCorridor.id == corridor_id).first()
    if not corridor:
        raise HTTPException(status_code=404, detail="Air-right corridor not found")
    allowed = {"corridor_type", "height_min_m", "height_max_m", "geometry_geojson", "conflict_status"}
    for key, value in payload.items():
        if key in allowed:
            setattr(corridor, key, value)
    if corridor.height_min_m is not None and corridor.height_max_m is not None and corridor.height_max_m <= corridor.height_min_m:
        db.rollback()
        raise HTTPException(status_code=400, detail="height_max_m must be greater than height_min_m")
    db.commit()
    db.refresh(corridor)
    return {
        "id": corridor.id, "parcel_id": corridor.parcel_id, "corridor_type": corridor.corridor_type,
        "height_min_m": corridor.height_min_m, "height_max_m": corridor.height_max_m,
        "geometry_geojson": corridor.geometry_geojson, "conflict_status": corridor.conflict_status,
    }


@router.delete("/air-rights/{corridor_id}")
def delete_air_right_corridor(
    corridor_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    corridor = db.query(models.AirRightCorridor).filter(models.AirRightCorridor.id == corridor_id).first()
    if not corridor:
        raise HTTPException(status_code=404, detail="Air-right corridor not found")
    db.delete(corridor)
    db.commit()
    return {"deleted": corridor_id}


@router.get("/underground-assets")
def list_underground_assets(db: Session = Depends(get_db)):
    assets = db.query(models.UndergroundAsset).all()
    return [{
        "id": a.id, "parcel_id": a.parcel_id, "asset_type": a.asset_type,
        "depth_min_m": a.depth_min_m, "depth_max_m": a.depth_max_m,
        "geometry_geojson": a.geometry_geojson,
        "source": a.source or "manual", "detection_confidence": a.detection_confidence,
        "quality_level": a.quality_level.value if hasattr(a.quality_level, "value") else a.quality_level,
    } for a in assets]


@router.get("/air-rights")
def list_air_rights(db: Session = Depends(get_db)):
    corridors = db.query(models.AirRightCorridor).all()
    return [{
        "id": c.id, "parcel_id": c.parcel_id, "corridor_type": c.corridor_type,
        "height_min_m": c.height_min_m, "height_max_m": c.height_max_m,
        "geometry_geojson": c.geometry_geojson, "conflict_status": c.conflict_status,
        "source": c.source or "manual", "detection_confidence": c.detection_confidence,
        "height_source": c.height_source, "detection_notes": c.detection_notes,
    } for c in corridors]


@router.get("/change-detection")
def list_change_detections(db: Session = Depends(get_db)):
    changes = db.query(models.ChangeDetection).all()
    return [{
        "id": c.id, "parcel_id": c.parcel_id, "date_before": c.date_before,
        "date_after": c.date_after, "description": c.description, "confidence": c.confidence,
    } for c in changes]


@router.post("/change-detection/sweep")
def run_change_detection_sweep(
    user: models.User = Depends(auth.require_roles("admin", "verifier")),
):
    """
    On-demand trigger for the same sweep app.change_detection_scheduler
    runs on a timer (CHANGE_DETECTION_ENABLED/CHANGE_DETECTION_INTERVAL_HOURS
    env vars) -- re-extracts footprint/floor-count for every building with
    uploaded imagery or a point cloud and flags any that drifted past the
    threshold since the last check. Runs synchronously; for a large
    portfolio this should move to the same background-task pattern as
    /api/processing/start if it starts taking more than a few seconds.
    """
    from ..change_detection_scheduler import run_sweep_once
    return run_sweep_once()


@router.post("/datasets/upload")
async def upload_dataset(
    dataset_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not permitted")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit")

    dataset = models.Dataset(
        uploaded_by=user.id, dataset_type=dataset_type, filename=file.filename,
        file_format=ext, size_bytes=len(contents), status="uploaded",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return {"id": dataset.id, "filename": dataset.filename, "status": dataset.status, "size_bytes": dataset.size_bytes}


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    datasets = db.query(models.Dataset).order_by(models.Dataset.created_at.desc()).all()
    return [{
        "id": d.id, "dataset_type": d.dataset_type, "filename": d.filename,
        "file_format": d.file_format, "size_bytes": d.size_bytes, "status": d.status,
        "created_at": d.created_at.isoformat(),
    } for d in datasets]


@router.post("/gnss-control-points", response_model=schemas.GnssControlPointOut)
def add_gnss_control_point(payload: schemas.GnssControlPointCreate, db: Session = Depends(get_db),
                            user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin"))):
    """Records a CORS/GCP ground-control point (Layer 1: Data Sources &
    Acquisition) used to georeference a dataset during ETL. This is
    metadata about a real-world control point YOU provide (from your CORS
    network / RTK survey) -- there is no public API that supplies these,
    so there's nothing to auto-fetch here."""
    if payload.dataset_id and not db.query(models.Dataset).filter(models.Dataset.id == payload.dataset_id).first():
        raise HTTPException(status_code=404, detail="dataset_id does not exist")
    gcp = models.GnssControlPoint(**payload.model_dump())
    db.add(gcp)
    db.commit()
    db.refresh(gcp)
    return gcp


@router.get("/gnss-control-points", response_model=list[schemas.GnssControlPointOut])
def list_gnss_control_points(dataset_id: str = None, db: Session = Depends(get_db),
                              user: models.User = Depends(auth.get_current_user)):
    q = db.query(models.GnssControlPoint)
    if dataset_id:
        q = q.filter(models.GnssControlPoint.dataset_id == dataset_id)
    return q.order_by(models.GnssControlPoint.created_at.desc()).all()


class RegisterViaGCPRequest(BaseModel):
    correspondences: list


class RegisterICPRequest(BaseModel):
    target_dataset_id: str
    max_points: int = 50000


@router.post("/assets/datasets/{dataset_id}/register")
def register_dataset_via_gcp(
    dataset_id: str, payload: RegisterViaGCPRequest, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Georeferences a dataset (Layer 2: Ingestion & ETL) using >=3
    correspondences you've identified between raw local coordinates in the
    dataset and real GNSS control points already recorded via
    POST /api/assets/gnss-control-points. Computes the real closed-form
    similarity transform (registration.align_via_control_points) -- this
    does NOT auto-detect which local point is which control point; that
    correspondence is the one input only a person (or a feature-matching
    step outside this endpoint's scope) can supply.
    """
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if len(payload.correspondences) < 3:
        raise HTTPException(status_code=400, detail="Need at least 3 correspondences for a similarity-transform fit.")

    local_points, control_points = [], []
    for c in payload.correspondences:
        gcp = db.query(models.GnssControlPoint).filter(models.GnssControlPoint.id == c["gnss_control_point_id"]).first()
        if not gcp:
            raise HTTPException(status_code=404, detail=f"GNSS control point '{c['gnss_control_point_id']}' not found")
        local_points.append([c["local_x"], c["local_y"], c.get("local_z", 0.0)])
        control_points.append({"lat": gcp.latitude, "lon": gcp.longitude, "ellipsoidal_height_m": gcp.ellipsoidal_height_m or 0.0})

    try:
        transform = registration.align_via_control_points(local_points, control_points)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    dataset.transform_matrix_json = json.dumps(transform)
    dataset.registration_rmse_m = transform["rmse_m"]
    dataset.registered_at = datetime.utcnow()
    db.commit()
    return {"dataset_id": dataset_id, "transform": transform}


@router.post("/assets/datasets/{dataset_id}/register-icp")
def register_dataset_via_icp(
    dataset_id: str, payload: RegisterICPRequest, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Refines a dataset's alignment against an overlapping reference point
    cloud via real ICP (registration.icp_refine) -- for fusing two
    LiDAR/photogrammetry passes of the same area, per Layer 2 of the
    architecture ("Register point clouds (ICP) and fuse LiDAR +
    photogrammetry"). Starts from the dataset's existing GCP transform if
    one was set by /register above, otherwise identity.

    Requires both datasets to be actual point clouds with storage_path set
    (i.e. uploaded .las/.laz files) -- returns 400 if either is missing,
    rather than fabricating a refinement from nothing.
    """
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    target = db.query(models.Dataset).filter(models.Dataset.id == payload.target_dataset_id).first()
    if not dataset or not target:
        raise HTTPException(status_code=404, detail="Dataset or target_dataset_id not found")
    if not dataset.storage_path or not target.storage_path:
        raise HTTPException(status_code=400, detail="Both datasets need an uploaded point cloud file (storage_path) to run ICP.")

    source_pts = registration.load_point_cloud_xyz(dataset.storage_path, max_points=payload.max_points)
    target_pts = registration.load_point_cloud_xyz(target.storage_path, max_points=payload.max_points)
    if source_pts is None or target_pts is None:
        raise HTTPException(status_code=422, detail="Could not read one or both point clouds (see server log) -- check laspy is installed and the files are valid LAS/LAZ.")

    initial_transform = json.loads(dataset.transform_matrix_json) if dataset.transform_matrix_json else None
    try:
        transform = registration.icp_refine(source_pts, target_pts, initial_transform=initial_transform)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    dataset.transform_matrix_json = json.dumps(transform)
    dataset.registration_rmse_m = transform["rmse_m"]
    dataset.registered_at = datetime.utcnow()
    db.commit()
    return {"dataset_id": dataset_id, "transform": transform}
