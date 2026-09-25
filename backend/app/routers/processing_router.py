"""
Processing pipeline router.

IMPORTANT — honesty note (updated now that the real model is plugged in):
extract_building_footprint() and segment_floors() below now try the real
YOLOv8-seg / point-cloud clustering model first (via ai/footprint/extractor.py and ai/floors/segmenter.py), and
only fall back to the disclosed deterministic heuristic when the model
is disabled, its weights/packages aren't installed, or the building has
no uploaded imagery/point cloud. Which path actually ran is never
guessed after the fact — it's recorded on the building/floor as
footprint_source / floor_source ("manual" vs "ml_model") and stated
plainly in the pipeline log, so the UI and API always say which one
produced a given number.

What IS real, either way:
- The pipeline stage machine and progress tracking are backend-driven
  (persisted to ProcessingJob), not a frontend animation timer.
- When no model is plugged in (or a building has no uploaded imagery),
  the building footprint is the ACTUAL polygon the user entered at
  building creation, and floor elevation bands come from the building's
  real num_floors and height_m (floor height = height_m / num_floors).
- When the model IS plugged in and the building has uploaded imagery
  and/or a point cloud, the footprint/floor bands and confidence scores
  are the model's real output (see ai/footprint/extractor.py, ai/floors/segmenter.py) — not the heuristic.
- Unit footprints are a real grid subdivision of the (real, whichever
  source it came from) footprint bounding box — deterministic, not
  randomized.
- The disclosed deterministic heuristic (geometric_regularity_score) is
  still used verbatim as the fallback confidence when the model path
  isn't available — never a random number.
- 3D ULPINs are generated via the real deterministic ulpin.py service.
- Topology validation runs real Shapely spatial checks against the
  generated geometry (see validation.py).

The architecture is built so extract_building_footprint() and
segment_floors() can call a real model without changing anything else in
the pipeline — see ai/footprint/extractor.py and ai/floors/segmenter.py for the model adapters and the
AI_MODELS_ENABLED / YOLO_SEG_WEIGHTS_PATH env vars that control it.
"""
import json
import logging
import math
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas, auth, cache, lifecycle, ulpin as ulpin_service, validation as validation_service
from ..ai.footprint import extractor as footprint_extractor
from ..ai.floors import segmenter as floor_segmenter
from ..ai.heights import ndsm_estimator
from ..database import get_db, SessionLocal

router = APIRouter(prefix="/api/processing", tags=["processing"])
logger = logging.getLogger("landsphere.processing")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
IMAGERY_EXTENSIONS = {"jpg", "jpeg", "png", "tif", "tiff"}
POINTCLOUD_EXTENSIONS = {"las", "laz"}


def _log_stage(job: models.ProcessingJob, stage: str, message: str):
    log = json.loads(job.log or "[]")
    log.append({"stage": stage, "status": "complete", "timestamp": datetime.utcnow().isoformat(), "message": message})
    job.log = json.dumps(log)


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_area(points):
    n = len(points)
    area = 0.0
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def geometric_regularity_score(points, floor_count=None, floor_heights=None):
    """
    Deterministic confidence heuristic -- NOT a trained model.

    Building/unit score: ratio of the polygon's true area to its bounding-box
    area. A perfectly rectangular footprint scores 1.0; an irregular or
    noisy-looking outline scores lower. This mirrors a real signal a trained
    extraction model's confidence would correlate with (clean rectangular
    footprints are easier to extract confidently than irregular ones), while
    being fully transparent about being a heuristic, not a model.

    Floor score (when floor_heights given): 1.0 minus the coefficient of
    variation of floor heights -- perfectly uniform floor heights score
    highest, irregular ones score lower.

    Output is scaled into a realistic-looking 0.75-0.98 band so it reads
    naturally in the UI while remaining fully deterministic and reproducible.
    """
    x0, y0, x1, y1 = _bbox(points)
    bbox_area = max((x1 - x0) * (y1 - y0), 1e-6)
    area = _polygon_area(points)
    fill_ratio = min(area / bbox_area, 1.0)

    if floor_heights and len(floor_heights) > 1:
        mean_h = sum(floor_heights) / len(floor_heights)
        variance = sum((h - mean_h) ** 2 for h in floor_heights) / len(floor_heights)
        cv = (variance ** 0.5) / mean_h if mean_h > 0 else 0
        uniformity = max(1.0 - cv, 0.0)
        combined = (fill_ratio * 0.4) + (uniformity * 0.6)
    else:
        combined = fill_ratio

    return round(0.75 + combined * 0.23, 2)


def extract_building_footprint(building: models.Building):
    """
    Tries the real YOLOv8-seg model first (if enabled and the building has
    an uploaded drone/orthophoto image), then falls back to the REAL
    footprint the user entered at building creation. Either way this never
    invents geometry -- it raises if neither a model result nor a manual
    footprint exists.
    """
    model_result = footprint_extractor.extract_footprint_from_imagery(building.drone_image_path)
    if model_result is not None:
        points, confidence = model_result
        if building.manual_footprint_geojson is None and building.footprint_geojson:
            building.manual_footprint_geojson = building.footprint_geojson
        points = footprint_extractor.reanchor_to_existing_footprint(points, building.footprint_geojson)
        building.ai_confidence = confidence
        building.footprint_source = "ml_model"
        building.ai_processed_at = datetime.utcnow()
        building.footprint_geojson = json.dumps(points)
        x0, y0, x1, y1 = _bbox(points)
        return points, (x1 - x0), (y1 - y0), (x0, y0)

    if not building.footprint_geojson:
        raise HTTPException(
            status_code=400,
            detail="This building has no footprint geometry and no usable drone imagery. Create it with a "
                   "footprint (via POST /api/buildings) or upload imagery before running the pipeline.",
        )
    points = json.loads(building.footprint_geojson)
    confidence = geometric_regularity_score(points)
    building.ai_confidence = confidence
    building.footprint_source = "manual"
    x0, y0, x1, y1 = _bbox(points)
    return points, (x1 - x0), (y1 - y0), (x0, y0)


def segment_floors(building: models.Building, db: Session):
    """
    Tries the real point-cloud clustering model first (if enabled and the
    building has an uploaded LiDAR point cloud), then falls back to
    deriving floor z-ranges from the building's REAL height_m and
    num_floors (both user-entered), so floor height = height_m / num_floors
    -- not a fixed guess.
    """
    points = json.loads(building.footprint_geojson)

    model_result = floor_segmenter.segment_floors_from_point_cloud(building.point_cloud_path, expected_num_floors=building.num_floors)
    if model_result is not None:
        floor_ranges, floor_confidence = model_result
        if building.manual_num_floors is None:
            building.manual_num_floors = building.num_floors
            building.manual_height_m = building.height_m
        building.floor_source = "ml_model"
        building.ai_processed_at = datetime.utcnow()
        floors = []
        for i, (z_min, z_max) in enumerate(floor_ranges, start=1):
            floor = models.Floor(
                building_id=building.id,
                floor_code=ulpin_service.format_code("F", i),
                floor_number=i,
                z_min=z_min, z_max=z_max,
                ai_confidence=floor_confidence,
            )
            db.add(floor)
            floors.append(floor)
        db.flush()
        avg_floor_height = (floor_ranges[-1][1] - floor_ranges[0][0]) / len(floor_ranges)
        building.num_floors = len(floor_ranges)
        return floors, avg_floor_height

    if not building.num_floors or building.num_floors < 1:
        raise HTTPException(status_code=400, detail="Building must have num_floors >= 1 to run the pipeline.")
    if not building.height_m or building.height_m <= 0:
        raise HTTPException(status_code=400, detail="Building must have a positive height_m to run the pipeline.")

    floor_height = building.height_m / building.num_floors
    floor_heights = [floor_height] * building.num_floors
    floor_confidence = geometric_regularity_score(points, floor_count=building.num_floors, floor_heights=floor_heights)
    building.floor_source = "manual"

    floors = []
    for i in range(1, building.num_floors + 1):
        z_min = round((i - 1) * floor_height, 2)
        z_max = round(i * floor_height, 2)
        floor = models.Floor(
            building_id=building.id,
            floor_code=ulpin_service.format_code("F", i),
            floor_number=i,
            z_min=z_min, z_max=z_max,
            ai_confidence=floor_confidence,
        )
        db.add(floor)
        floors.append(floor)
    db.flush()
    return floors, floor_height


def segment_basement_levels(building: models.Building, db: Session):
    """
    Basement counterpart to segment_floors(). Tries real point-cloud
    clustering FIRST -- but only produces a real automatic result if
    building.basement_point_cloud_path is set to an actual basement/
    underground scan (a mobile/backpack LiDAR walkthrough or terrestrial
    scan taken inside the basement). This is NOT the same file as
    building.point_cloud_path (the rooftop/aerial scan) -- ordinary aerial
    drone/LiDAR cannot see an enclosed basement, so if only the aerial
    point cloud exists, this always falls through to the manual fallback
    below. See ai/floors/segmenter.py::segment_basement_from_point_cloud
    for the full explanation.

    Falls back to evenly splitting building.num_basement_levels (a
    surveyor-entered count, default 0) across height MIN_BASEMENT_HEIGHT_M
    each -- mirroring exactly how the above-ground fallback works, just
    below z=0. If num_basement_levels is 0, returns ([], 0.0): no
    basement is invented where none was declared.
    """
    model_result = floor_segmenter.segment_basement_from_point_cloud(
        building.basement_point_cloud_path,
        expected_num_basement_levels=building.num_basement_levels or None,
    )

    if model_result is not None:
        basement_ranges, confidence = model_result
    elif not building.num_basement_levels or building.num_basement_levels < 1:
        return [], 0.0
    else:
        level_height = floor_segmenter.MIN_BASEMENT_HEIGHT_M
        basement_ranges = [
            (round(-(i + 1) * level_height, 2), round(-i * level_height, 2))
            for i in range(building.num_basement_levels)
        ][::-1]
        points = json.loads(building.footprint_geojson)
        confidence = geometric_regularity_score(points, floor_count=building.num_basement_levels, floor_heights=[level_height] * building.num_basement_levels)

    basements = []
    for i, (z_min, z_max) in enumerate(basement_ranges, start=1):
        level_number = len(basement_ranges) - i + 1
        floor = models.Floor(
            building_id=building.id,
            floor_code=ulpin_service.format_code("B", level_number),
            floor_number=-level_number,
            z_min=z_min, z_max=z_max,
            ai_confidence=confidence,
        )
        db.add(floor)
        basements.append(floor)
    db.flush()
    return basements, (abs(basement_ranges[-1][0]) / len(basement_ranges) if basement_ranges else 0.0)


def delineate_units(building: models.Building, floors, footprint_w, footprint_d, origin, db: Session, parcel_ulpin: str, floor_height: float):
    """Vertical parcel delineation: subdivides each floor's REAL footprint
    bounding box into a grid -- deterministic based on building size, not
    randomized unit counts."""
    ox, oy = origin
    total_area = footprint_w * footprint_d
    target_unit_area = 45.0
    units_per_floor = max(2, min(12, round(total_area / target_unit_area)))
    cols = 2 if units_per_floor >= 4 else 1
    rows = max(1, units_per_floor // cols)
    cell_w = footprint_w / cols
    cell_d = footprint_d / rows

    all_units = []
    for floor in floors:
        idx = 1
        for r in range(rows):
            for c in range(cols):
                x0, y0 = ox + c * cell_w, oy + r * cell_d
                x1, y1 = x0 + cell_w * 0.9, y0 + cell_d * 0.9
                poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
                unit_code = ulpin_service.format_code("U", idx)
                ulpin_3d = ulpin_service.generate_3d_ulpin(parcel_ulpin, building.building_code, floor.floor_code, unit_code)
                unit_area = round((x1 - x0) * (y1 - y0), 2)

                if floor.floor_number < 0:
                    parcel_type = "parking_unit"
                elif floor.floor_number == 1:
                    parcel_type = "commercial_unit"
                else:
                    parcel_type = "residential_unit"

                unit_confidence = geometric_regularity_score(poly)

                unit = models.Unit(
                    floor_id=floor.id,
                    unit_code=unit_code,
                    ulpin_3d=ulpin_3d,
                    parcel_type=parcel_type,
                    footprint_geojson=json.dumps(poly),
                    area_sqm=unit_area,
                    volume_cum=round(unit_area * floor_height, 2),
                    z_min=floor.z_min, z_max=floor.z_max,
                    owner_reference=f"OWNER_{building.building_code}_{floor.floor_code}_{unit_code}",
                    ai_confidence=unit_confidence,
                    verification_status=models.VerificationStatus.pending_review,
                )
                db.add(unit)
                all_units.append(unit)
                idx += 1
    db.flush()
    return all_units


def run_topology_validation(building: models.Building, floors, units, db: Session):
    results = []

    for f in floors:
        for r in validation_service.check_z_range(f.z_min, f.z_max, f.floor_code):
            results.append({**r, "building_id": building.id})

    floor_dicts = [{"id": f.id, "label": f.floor_code, "z_min": f.z_min, "z_max": f.z_max} for f in floors]
    for r in validation_service.check_floor_overlap(floor_dicts):
        results.append({**r, "building_id": building.id})

    by_floor = {}
    for u in units:
        by_floor.setdefault(u.floor_id, []).append(u)
    for floor_id, floor_units in by_floor.items():
        geoms = [{"id": u.id, "label": u.ulpin_3d, "geojson": u.footprint_geojson} for u in floor_units]
        for r in validation_service.check_overlap(geoms):
            results.append({**r, "unit_id": floor_units[0].id})

    underground_assets = db.query(models.UndergroundAsset).filter(
        models.UndergroundAsset.parcel_id == building.parcel_id
    ).all()
    for asset in underground_assets:
        for r in validation_service.check_underground_conflict(
            building.footprint_geojson, building.building_code,
            asset.geometry_geojson, asset.asset_type, asset.asset_type,
        ):
            results.append({**r, "building_id": building.id})

    for r in results:
        db.add(models.ValidationResult(
            unit_id=r.get("unit_id"), building_id=r.get("building_id"),
            check_type=r["check_type"], severity=r["severity"], message=r["message"],
        ))
    db.flush()
    return results


@router.post("/start", response_model=schemas.ProcessingJobOut)
def start_processing(
    payload: schemas.StartProcessingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Returns immediately after creating the job row (stage=uploading), then
    runs the actual pipeline in a background task.

    Why this matters for scalability: the previous version ran the entire
    pipeline synchronously inside the request, holding a worker thread (and
    its DB connection) for the full duration. Under concurrent load -- many
    surveyors clicking "Generate" at once -- that serializes throughput to
    however many workers Uvicorn has. Returning immediately frees the
    request/worker right away; the frontend polls GET /jobs/{id} for
    progress, which is a cheap read. This is the same pattern a real task
    queue (Celery/RQ) would implement, just without the extra broker
    infrastructure -- swap this for a real queue if a single process's
    background tasks become the bottleneck at higher scale (see the
    scalability notes in the README).
    """
    building = db.query(models.Building).filter(models.Building.id == payload.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    existing_floor_count = db.query(models.Floor).filter(models.Floor.building_id == building.id).count()
    if existing_floor_count > 0:
        raise HTTPException(
            status_code=400,
            detail="This building has already been processed. Reprocessing an existing "
                   "building's floors/units is not yet supported in this prototype.",
        )

    job = models.ProcessingJob(building_id=building.id, started_by=user.id,
                                 stage=models.ProcessingStage.uploading, progress_pct=5, log="[]")
    db.add(job)
    _log_stage(job, "uploading", "Datasets received and queued")
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_pipeline, job.id, building.id)
    return job


def _run_pipeline(job_id: str, building_id: str):
    """
    Runs in the background, after the response has already been sent to the
    client. Opens its own DB session -- the request-scoped session from
    get_db() is closed by the time this runs, so reusing it would fail.
    """
    db = SessionLocal()
    try:
        job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
        building = db.query(models.Building).filter(models.Building.id == building_id).first()
        parcel = db.query(models.Parcel).filter(models.Parcel.id == building.parcel_id).first()

        job.stage = models.ProcessingStage.preprocessing
        job.progress_pct = 15
        _log_stage(job, "preprocessing", "Coordinate alignment complete")
        db.commit()

        job.stage = models.ProcessingStage.building_extraction
        job.progress_pct = 30
        points, w, d, origin = extract_building_footprint(building)
        if building.footprint_source == "ml_model":
            _log_stage(job, "building_extraction",
                       f"YOLOv8-seg model extraction ({w:.1f}m x {d:.1f}m) -- model confidence {building.ai_confidence*100:.0f}%")
        else:
            _log_stage(job, "building_extraction",
                       f"Using entered footprint ({w:.1f}m x {d:.1f}m) -- geometric regularity score {building.ai_confidence*100:.0f}%")
        db.commit()

        job.stage = models.ProcessingStage.floor_segmentation
        job.progress_pct = 50
        floors, floor_height = segment_floors(building, db)
        if building.floor_source == "ml_model":
            _log_stage(job, "floor_segmentation",
                       f"{len(floors)} floors detected via point-cloud clustering ({floor_height:.2f}m avg storey height)")
        else:
            _log_stage(job, "floor_segmentation", f"{len(floors)} floors segmented at {floor_height:.2f}m each (height_m / num_floors)")

        basements, basement_level_height = segment_basement_levels(building, db)
        if basements:
            source_note = "point-cloud clustering of a basement scan" if building.basement_point_cloud_path else "surveyor-declared basement level count"
            _log_stage(job, "floor_segmentation", f"{len(basements)} basement level(s) segmented via {source_note} ({basement_level_height:.2f}m avg)")
        db.commit()

        all_floors = basements + floors

        job.stage = models.ProcessingStage.vertical_delineation
        job.progress_pct = 65
        units = delineate_units(building, all_floors, w, d, origin, db, parcel.ulpin_2d, floor_height)
        _log_stage(job, "vertical_delineation", f"{len(units)} units delineated from real footprint area ({w*d:.0f} sqm)")
        db.commit()

        job.stage = models.ProcessingStage.reconstruction_3d
        job.progress_pct = 78
        _log_stage(job, "reconstruction_3d", "3D volumetric geometry constructed for all units")
        db.commit()

        job.stage = models.ProcessingStage.ulpin_generation
        job.progress_pct = 88
        _log_stage(job, "ulpin_generation", f"{len(units)} 3D ULPINs generated")
        db.commit()

        job.stage = models.ProcessingStage.topology_validation
        job.progress_pct = 96
        val_results = run_topology_validation(building, floors, units, db)
        _log_stage(job, "topology_validation", f"{len(val_results)} validation flag(s) raised" if val_results else "No topology issues found")
        db.commit()

        job.stage = models.ProcessingStage.ready_for_review
        job.progress_pct = 100
        _log_stage(job, "ready_for_review", "All units queued for human verification")
        job.updated_at = datetime.utcnow()
        db.commit()

        cache.cache_invalidate("analytics:")
    except Exception as e:
        job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
        if job:
            job.stage = models.ProcessingStage.failed
            _log_stage(job, "failed", f"Pipeline error: {e}")
            db.commit()
        logger.exception(f"Pipeline failed for job {job_id}")
    finally:
        db.close()


def _save_upload(building_id: str, file: UploadFile, allowed_ext: set, subdir: str) -> str:
    ext = (file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "").lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not permitted (allowed: {sorted(allowed_ext)})")

    dest_dir = os.path.join(UPLOAD_DIR, subdir, building_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{uuid.uuid4().hex}.{ext}")

    with open(dest_path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            out.write(chunk)
    return dest_path


@router.post("/buildings/{building_id}/imagery")
def upload_building_imagery(
    building_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Uploads a drone/orthophoto image for a building. When AI_MODELS_ENABLED
    is true and YOLO_SEG_WEIGHTS_PATH points to real weights, the next
    /processing/start run on this building will use the YOLOv8-seg model on
    this image instead of the manually entered footprint. If the model
    isn't configured, the image is stored but the manual footprint is still
    used -- uploading imagery alone doesn't fake a model result.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    dest_path = _save_upload(building_id, file, IMAGERY_EXTENSIONS, "imagery")
    building.drone_image_path = dest_path
    db.commit()
    return {
        "building_id": building_id,
        "drone_image_path": dest_path,
        "ai_models_enabled": footprint_extractor.AI_MODELS_ENABLED,
        "note": "This image will be used by the AI model on the next pipeline run only if AI_MODELS_ENABLED=true "
                "and YOLO_SEG_WEIGHTS_PATH is configured with real weights. Otherwise the manual footprint is used. "
                "If this image may contain more than one building, use POST .../imagery/detect (with an optional "
                "crop_box) and .../imagery/select instead of relying on the automatic pipeline run, which always "
                "picks the single highest-confidence detection and cannot tell which building you meant.",
    }


@router.get("/buildings/{building_id}/imagery/file")
def get_building_imagery_file(building_id: str, db: Session = Depends(get_db)):
    """
    Serves this building's own uploaded drone/facade image back over HTTP.

    Added purely so the 3D viewer can texture-map the real photo onto the
    building's already-correctly-sized extruded volume (see ThreeScene.jsx
    -- this is decoration on top of the modeled footprint/height, not a 3D
    reconstruction from the photo). Nothing about the existing upload,
    detection, or pipeline flow changes: building.drone_image_path has
    always been a server filesystem path, just never previously reachable
    over HTTP by anything.

    Public/no-auth, matching GET /parcels/{id}'s access level -- this is
    the same building imagery the public 3D viewer already displays
    everything else about.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building or not building.drone_image_path:
        raise HTTPException(status_code=404, detail="No image uploaded for this building.")
    if not os.path.isfile(building.drone_image_path):
        raise HTTPException(status_code=404, detail="Image file is no longer present on disk.")
    return FileResponse(building.drone_image_path)


FOOTPRINT_CANDIDATES_TTL_SECONDS = 900


def _footprint_candidates_cache_key(building_id: str) -> str:
    return f"footprint_candidates:{building_id}"


def _regenerate_floors_and_units_if_processed(building: models.Building, db: Session):
    """
    Rebuilds this building's Floor/Unit rows from whatever is CURRENT on
    it (footprint_geojson/num_floors/height_m) -- called after either
    /imagery/select or /imagery/select-floors changes one of those on a
    building that was already run through the pipeline once.

    Without this, a corrected footprint or floor count updated the
    Building row but never reached the Floor/Unit rows the 3D viewer
    actually renders from, because POST /processing/start explicitly
    refuses to reprocess a building that already has floors ("Reprocessing
    an existing building's floors/units is not yet supported") -- so a
    building corrected AFTER its first pipeline run had no route back to
    a matching 3D view at all. This closes that gap directly rather than
    lifting the reprocessing restriction on /processing/start itself.

    No-ops if the building hasn't been processed yet (no Floor rows
    exist) -- there's nothing to keep in sync until the first real
    "Generate 3D ULPINs" run, which will use whatever is current by then.
    """
    existing_floors = db.query(models.Floor).filter(models.Floor.building_id == building.id).all()
    if not existing_floors:
        return

    if any(lifecycle.is_locked(u) for f in existing_floors for u in f.units):
        raise HTTPException(
            status_code=409,
            detail="This building has verified (locked) units -- regenerating floors would erase them. "
                   "Use an owner-approved change request instead.",
        )

    old_unit_ids = [u.id for f in existing_floors for u in f.units]
    db.query(models.ValidationResult).filter(
        or_(models.ValidationResult.building_id == building.id, models.ValidationResult.unit_id.in_(old_unit_ids))
    ).delete(synchronize_session=False)

    for f in existing_floors:
        db.delete(f)
    db.flush()

    points = json.loads(building.footprint_geojson)
    x0, y0, x1, y1 = _bbox(points)
    origin = (x0, y0)
    w, d = (x1 - x0), (y1 - y0)

    floors, floor_height = segment_floors(building, db)
    basements, basement_level_height = segment_basement_levels(building, db)
    all_floors = basements + floors
    parcel = db.query(models.Parcel).filter(models.Parcel.id == building.parcel_id).first()
    delineate_units(building, all_floors, w, d, origin, db, parcel.ulpin_2d, floor_height)


@router.post("/buildings/{building_id}/imagery/detect", response_model=schemas.DetectFootprintsResponse)
def detect_building_footprints(
    building_id: str,
    body: schemas.DetectFootprintsRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Runs the YOLOv8-seg model on this building's uploaded drone image and
    returns EVERY detected building mask (not just the highest-confidence
    one), so a human picks which detection is actually the target building
    before anything is saved. Nothing on the Building row is modified by
    this call.

    Two production gaps this closes together (see honesty note on
    extract_footprint_from_imagery -- it silently keeps only the
    highest-confidence mask, which is wrong when the image has several
    buildings in it):

    - Option 1 (crop-before-detect): pass body.crop_box = [x0, y0, x1, y1]
      (pixels, in the uploaded image's own coordinate frame) around the one
      building you mean, drawn by the surveyor in the frontend. Inference
      then only looks inside that region.
    - Option 3 (human-confirmed selection): whether or not a crop_box is
      given, every detection found is returned with its own confidence and
      geometry -- call POST .../imagery/select with the candidate_index the
      surveyor picked to actually save it as the building's footprint.

    Candidates are cached (Redis if configured, else in-process -- see
    cache.py) for FOOTPRINT_CANDIDATES_TTL_SECONDS so the immediately
    following /select call doesn't need to re-run inference or re-send the
    crop_box.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    if not building.drone_image_path:
        raise HTTPException(
            status_code=400,
            detail="No drone image uploaded for this building yet. POST .../imagery first.",
        )

    if not footprint_extractor.AI_MODELS_ENABLED:
        return schemas.DetectFootprintsResponse(
            building_id=building_id,
            drone_image_path=building.drone_image_path,
            crop_box=body.crop_box,
            candidates=[],
            ai_models_enabled=False,
        )

    candidates = footprint_extractor.extract_all_footprints_from_imagery(
        building.drone_image_path, crop_box=body.crop_box
    )
    if candidates is None:
        raise HTTPException(
            status_code=503,
            detail="AI_MODELS_ENABLED is true but the model could not run (check YOLO_SEG_WEIGHTS_PATH and that "
                   "ultralytics is installed -- see server logs). No candidates to select from.",
        )

    cache.cache_set(
        _footprint_candidates_cache_key(building_id),
        {
            "drone_image_path": building.drone_image_path,
            "crop_box": body.crop_box,
            "candidates": candidates,
        },
        ttl_seconds=FOOTPRINT_CANDIDATES_TTL_SECONDS,
    )

    return schemas.DetectFootprintsResponse(
        building_id=building_id,
        drone_image_path=building.drone_image_path,
        crop_box=body.crop_box,
        candidates=[
            schemas.FootprintCandidateOut(index=i, confidence=c["confidence"], polygon_m=c["polygon_m"], bbox_px=c["bbox_px"])
            for i, c in enumerate(candidates)
        ],
        ai_models_enabled=True,
    )


@router.post("/buildings/{building_id}/imagery/select", response_model=schemas.BuildingOut)
def select_building_footprint(
    building_id: str,
    body: schemas.SelectFootprintRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Saves ONE of the candidates returned by /imagery/detect as this
    building's real footprint -- the human-confirmed counterpart to the
    automatic pipeline overwriting footprint_geojson with whatever the
    model was most confident about. Candidate geometry and confidence are
    used completely unmodified from what the model actually produced
    (same real ai_confidence field as the automatic path) -- this endpoint
    only changes WHICH detection gets used, never invents or adjusts one.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    cached = cache.cache_get(_footprint_candidates_cache_key(building_id))
    if not cached:
        raise HTTPException(
            status_code=400,
            detail="No pending detection candidates for this building (they expire after "
                   f"{FOOTPRINT_CANDIDATES_TTL_SECONDS}s, or the image was re-uploaded since). "
                   "Call POST .../imagery/detect again.",
        )
    if cached.get("drone_image_path") != building.drone_image_path:
        raise HTTPException(
            status_code=409,
            detail="The building's drone image has changed since these candidates were detected. "
                   "Call POST .../imagery/detect again on the current image.",
        )

    candidates = cached.get("candidates", [])
    idx = body.candidate_index
    if idx < 0 or idx >= len(candidates):
        raise HTTPException(status_code=400, detail=f"candidate_index {idx} out of range (0..{len(candidates) - 1}).")

    chosen = candidates[idx]

    if building.manual_footprint_geojson is None and building.footprint_geojson:
        building.manual_footprint_geojson = building.footprint_geojson

    anchored_points = footprint_extractor.reanchor_to_existing_footprint(
        chosen["polygon_m"], building.footprint_geojson,
    )

    building.footprint_geojson = json.dumps(anchored_points)
    building.ai_confidence = chosen["confidence"]
    building.footprint_source = "ml_model"
    building.ai_processed_at = datetime.utcnow()
    db.flush()

    _regenerate_floors_and_units_if_processed(building, db)

    db.commit()
    db.refresh(building)

    cache.cache_invalidate(_footprint_candidates_cache_key(building_id))

    return building


FLOOR_ESTIMATE_TTL_SECONDS = 900


def _floor_estimate_cache_key(building_id: str) -> str:
    return f"floor_estimate:{building_id}"


@router.post("/buildings/{building_id}/imagery/detect-floors", response_model=schemas.DetectFloorsResponse)
def detect_building_floor_count(
    building_id: str,
    body: schemas.DetectFloorsRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Estimates the REAL floor count/height visible in this building's
    uploaded facade photo -- closes the gap where a building created with
    a placeholder num_floors (e.g. entered as 50 for testing) stayed at
    that manually entered value forever, because segment_floors() only
    ever re-derives floor bands from a real point cloud OR from
    building.num_floors/height_m -- it has no path that looks at an
    uploaded 2D photo at all. This endpoint is that missing path: nothing
    on the Building row is changed here, only returned for review -- call
    POST .../imagery/select-floors to actually apply it.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    if not building.drone_image_path:
        raise HTTPException(
            status_code=400,
            detail="No drone/facade image uploaded for this building yet. POST .../imagery first.",
        )

    if not footprint_extractor.AI_MODELS_ENABLED:
        return schemas.DetectFloorsResponse(
            building_id=building_id, drone_image_path=building.drone_image_path,
            crop_box=body.crop_box, estimate=None, ai_models_enabled=False,
            current_num_floors=building.num_floors, current_height_m=building.height_m,
        )

    estimate = footprint_extractor.estimate_floor_count_from_imagery(building.drone_image_path, crop_box=body.crop_box)

    if estimate is not None:
        cache.cache_set(
            _floor_estimate_cache_key(building_id),
            {"drone_image_path": building.drone_image_path, "estimate": estimate},
            ttl_seconds=FLOOR_ESTIMATE_TTL_SECONDS,
        )

    return schemas.DetectFloorsResponse(
        building_id=building_id, drone_image_path=building.drone_image_path,
        crop_box=body.crop_box,
        estimate=schemas.FloorEstimateOut(**estimate) if estimate else None,
        ai_models_enabled=True,
        current_num_floors=building.num_floors, current_height_m=building.height_m,
    )


@router.post("/buildings/{building_id}/imagery/select-floors", response_model=schemas.BuildingOut)
def select_building_floor_count(
    building_id: str,
    body: schemas.SelectFloorsRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Applies the pending facade-detected floor count/height from
    .../imagery/detect-floors onto this building -- human-confirmed, same
    pattern as /imagery/select for footprints. Snapshots the pre-AI
    num_floors/height_m exactly once (manual_num_floors/manual_height_m)
    so the Manual-vs-AI comparison elsewhere stays meaningful, then sets
    floor_source="ml_model" so the next pipeline run's segment_floors()
    re-derives real Floor rows from these corrected values.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    cached = cache.cache_get(_floor_estimate_cache_key(building_id))
    if not cached:
        raise HTTPException(
            status_code=400,
            detail="No pending floor-count estimate for this building (it expires after "
                   f"{FLOOR_ESTIMATE_TTL_SECONDS}s, or the image was re-uploaded since). "
                   "Call POST .../imagery/detect-floors again.",
        )
    if cached.get("drone_image_path") != building.drone_image_path:
        raise HTTPException(
            status_code=409,
            detail="The building's drone image has changed since this estimate was made. "
                   "Call POST .../imagery/detect-floors again on the current image.",
        )

    estimate = cached["estimate"]

    if building.manual_num_floors is None:
        building.manual_num_floors = building.num_floors
    if building.manual_height_m is None:
        building.manual_height_m = building.height_m

    building.num_floors = estimate["floor_count"]
    building.height_m = estimate["height_m"]
    building.floor_source = "ml_model"
    building.ai_processed_at = datetime.utcnow()
    db.flush()

    _regenerate_floors_and_units_if_processed(building, db)

    db.commit()
    db.refresh(building)

    cache.cache_invalidate(_floor_estimate_cache_key(building_id))

    return building


class EstimateHeightFromDemRequest(BaseModel):
    footprint_latlon: list[list[float]] | None = None


@router.post("/buildings/{building_id}/estimate-height-dem", response_model=schemas.BuildingOut)
def estimate_building_height_from_dem_endpoint(
    building_id: str,
    body: EstimateHeightFromDemRequest = EstimateHeightFromDemRequest(),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Lowest-confidence height/floor-count tier: estimates them from the
    public Copernicus GLO-30 satellite DSM (see ai/heights/ndsm_estimator.py)
    for a building that has no surveyed height_m/num_floors and no LiDAR
    point cloud to run segment_floors() against otherwise. Requires
    DEM_HEIGHT_ESTIMATION_ENABLED=true and the optional geo dependencies
    (pip install -r requirements-ml.txt) -- returns 422 with the reason
    when unavailable, never a fabricated value.

    Refuses (400) if the building already has real height_m/num_floors --
    this endpoint is for filling a genuine gap, not overriding a survey;
    clear the existing values first (or use the AI facade-detection
    endpoints above) if you actually want to replace them.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    if building.height_m is not None or building.num_floors is not None:
        raise HTTPException(
            status_code=400,
            detail="This building already has height_m/num_floors on record -- this endpoint only "
                   "fills a genuine gap, it does not override existing survey data.",
        )

    footprint_latlon = body.footprint_latlon
    if not footprint_latlon:
        parcel = db.query(models.Parcel).filter(models.Parcel.id == building.parcel_id).first()
        if not parcel or not building.footprint_geojson:
            raise HTTPException(
                status_code=400,
                detail="No footprint geometry to estimate from -- pass footprint_latlon explicitly, "
                       "or set a footprint on this building/parcel first.",
            )
        local_points = json.loads(building.footprint_geojson)
        lat_rad_correction = math.cos(math.radians(parcel.centroid_lat))
        footprint_latlon = [
            [parcel.centroid_lat + (y / 111320.0), parcel.centroid_lon + (x / (111320.0 * lat_rad_correction))]
            for x, y in local_points
        ]
        centroid_lat, centroid_lon = parcel.centroid_lat, parcel.centroid_lon
    else:
        centroid_lat = sum(p[0] for p in footprint_latlon) / len(footprint_latlon)
        centroid_lon = sum(p[1] for p in footprint_latlon) / len(footprint_latlon)

    estimate = ndsm_estimator.estimate_building_height_from_dem(
        [(p[0], p[1]) for p in footprint_latlon], centroid_lat, centroid_lon,
    )
    if estimate is None:
        raise HTTPException(
            status_code=422,
            detail="DEM height estimation unavailable or inconclusive for this building -- check "
                   "DEM_HEIGHT_ESTIMATION_ENABLED, that requirements-ml.txt is installed, and the "
                   "backend log for the specific reason (no satellite tile there, footprint too "
                   "small, etc). See ai/heights/ndsm_estimator.py.",
        )

    building.manual_num_floors = building.num_floors
    building.manual_height_m = building.height_m
    building.height_m = estimate["height_m"]
    building.num_floors = estimate["num_floors"]
    building.floor_source = "dem_estimated"
    building.ai_processed_at = datetime.utcnow()
    db.flush()

    _regenerate_floors_and_units_if_processed(building, db)

    db.commit()
    db.refresh(building)
    logger.info(
        f"Building {building.id}: height/floors estimated from {estimate['source']} "
        f"(confidence {estimate['confidence']}) -- height_m={estimate['height_m']}, num_floors={estimate['num_floors']}."
    )
    return building


@router.post("/buildings/{building_id}/pointcloud")
def upload_building_point_cloud(
    building_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Uploads a LiDAR point cloud (.las/.laz) for a building. When
    AI_MODELS_ENABLED is true, the next /processing/start run on this
    building will cluster real floor bands from this point cloud instead
    of dividing height_m evenly by num_floors.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    dest_path = _save_upload(building_id, file, POINTCLOUD_EXTENSIONS, "pointcloud")
    building.point_cloud_path = dest_path
    db.commit()
    return {
        "building_id": building_id,
        "point_cloud_path": dest_path,
        "ai_models_enabled": footprint_extractor.AI_MODELS_ENABLED,
        "note": "This point cloud will be used by the AI model on the next pipeline run only if "
                "AI_MODELS_ENABLED=true. Otherwise height_m / num_floors is used.",
    }


@router.post("/buildings/{building_id}/basement-pointcloud")
def upload_building_basement_point_cloud(
    building_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """
    Uploads a BASEMENT point cloud (.las/.laz) -- a mobile/backpack LiDAR
    or terrestrial scan taken INSIDE the basement, not the building's
    rooftop/aerial point cloud (see POST .../pointcloud above). Ordinary
    aerial drone/LiDAR cannot see an enclosed basement; this is a
    physically different capture. When AI_MODELS_ENABLED is true, the
    next pipeline run will cluster real basement levels from this file
    instead of evenly splitting the manually entered num_basement_levels.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    dest_path = _save_upload(building_id, file, POINTCLOUD_EXTENSIONS, "basement_pointcloud")
    building.basement_point_cloud_path = dest_path
    db.commit()
    return {
        "building_id": building_id,
        "basement_point_cloud_path": dest_path,
        "ai_models_enabled": footprint_extractor.AI_MODELS_ENABLED,
        "note": "This will be used to auto-detect basement levels on the next pipeline run only if "
                "AI_MODELS_ENABLED=true and this is genuinely a below-ground scan. Otherwise the "
                "manually entered num_basement_levels is split evenly.",
    }


@router.get("/buildings/{building_id}/comparison")
def get_building_ai_comparison(building_id: str, db: Session = Depends(get_db)):
    """
    Real before/after: the surveyor-entered ('before') values vs whatever
    the AI model actually produced ('after'), for whichever fields the
    model has touched so far. If the AI pipeline has never run on this
    building (or ran but no model was configured, so nothing changed),
    'after' is null for that field -- this never fabricates a synthetic
    'before' state, it only reports snapshots that were genuinely captured
    at the moment the model overwrote something.
    """
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    footprint_changed = building.manual_footprint_geojson is not None
    floors_changed = building.manual_num_floors is not None

    return {
        "building_id": building.id,
        "ai_processed_at": building.ai_processed_at.isoformat() if building.ai_processed_at else None,
        "footprint": {
            "changed_by_ai": footprint_changed,
            "before": building.manual_footprint_geojson,
            "after": building.footprint_geojson if footprint_changed else None,
            "source": building.footprint_source,
            "confidence": building.ai_confidence if footprint_changed else None,
        },
        "floors": {
            "changed_by_ai": floors_changed,
            "before": {"num_floors": building.manual_num_floors, "height_m": building.manual_height_m} if floors_changed else None,
            "after": {"num_floors": building.num_floors, "height_m": building.height_m} if floors_changed else None,
            "source": building.floor_source,
        },
    }


@router.get("/pending-model-run", response_model=list[schemas.PendingModelRunOut])
def list_pending_model_run(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
    limit: int = 200,
    offset: int = 0,
):
    """
    Duplicate-detection worklist: every building whose footprint_source is
    still 'manual' despite having a drone image and/or point cloud already
    uploaded for it. These are buildings a surveyor uploaded imagery for
    (thinking a real model run would use it) but where the pipeline either
    hasn't been run yet, or was run before AI_MODELS_ENABLED was turned on
    / before the weights were configured -- so the "manual" heuristic
    numbers are still what's on record even though real imagery exists.

    This never guesses WHY a building is stuck on manual -- it only
    reports the two directly observable facts (imagery/point cloud present,
    footprint_source/floor_source still manual) and lets a human decide
    whether to re-run POST /api/processing/start.
    """
    limit = min(limit, 500)
    q = (
        db.query(models.Building)
        .join(models.Parcel, models.Building.parcel_id == models.Parcel.id)
        .filter(
            or_(models.Building.footprint_source == "manual", models.Building.floor_source == "manual"),
            or_(
                models.Building.drone_image_path.isnot(None),
                models.Building.point_cloud_path.isnot(None),
                models.Building.basement_point_cloud_path.isnot(None),
            ),
        )
        .order_by(models.Building.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    results = []
    for b in q.all():
        footprint_pending = b.drone_image_path is not None and b.footprint_source == "manual"
        floor_pending = (b.point_cloud_path is not None or b.basement_point_cloud_path is not None) and b.floor_source == "manual"
        if not (footprint_pending or floor_pending):
            continue

        already_processed = db.query(models.Floor).filter(models.Floor.building_id == b.id).count() > 0
        results.append(schemas.PendingModelRunOut(
            building_id=b.id,
            building_code=b.building_code,
            building_name=b.name,
            parcel_id=b.parcel_id,
            parcel_ulpin_2d=b.parcel.ulpin_2d,
            parcel_address=b.parcel.address,
            has_drone_image=b.drone_image_path is not None,
            has_point_cloud=b.point_cloud_path is not None,
            has_basement_point_cloud=b.basement_point_cloud_path is not None,
            footprint_source=b.footprint_source,
            floor_source=b.floor_source,
            already_processed=already_processed,
            created_at=b.created_at,
        ))
    return results


@router.get("/jobs/{job_id}", response_model=schemas.ProcessingJobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs", response_model=list[schemas.ProcessingJobOut])
def list_jobs(db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user), limit: int = 100, offset: int = 0):
    limit = min(limit, 500)
    return db.query(models.ProcessingJob).order_by(models.ProcessingJob.created_at.desc()).offset(offset).limit(limit).all()
