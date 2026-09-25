"""
Periodic satellite/drone re-capture comparison, wired to the existing
ChangeDetection model (see app/routers/assets_router.py's GET
/api/change-detection, which already lists whatever rows are here --
this module is what starts populating them from real detections instead
of only seed data).

Honesty/scope note: this checks FOOTPRINT AREA and FLOOR COUNT drift --
the two signals directly available by re-running the existing real model
adapters (ai/footprint/extractor.py, ai/floors/segmenter.py) WITHOUT
re-running the full delineation pipeline, which this prototype does not
support re-running on an already-processed building (see
processing_router.start_processing()'s "already processed" guard). It
never invents a comparison: a ChangeDetection row is only created when a
real re-extraction actually differs from the last recorded snapshot by
more than the disclosed threshold below, using the exact same YOLOv8-seg /
point-cloud adapters as the main pipeline -- not a separate model of its
own, and not a pixel-diff (no satellite pixel-diff model is plugged in
here; wire one into ai/change_detection/ and call it from here if that
becomes available).
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .ai.footprint import extractor as footprint_extractor
from .ai.floors import segmenter as floor_segmenter

logger = logging.getLogger("landsphere.change_detection")

AREA_CHANGE_THRESHOLD_PCT = 15.0
FLOOR_INCREASE_THRESHOLD = 1


def _polygon_area(points) -> float:
    n = len(points)
    area = 0.0
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _change_confidence(magnitude_pct: float) -> float:
    """Deterministic, disclosed heuristic -- NOT a trained model's
    confidence score. Scales how large the detected change is into a
    0.6-0.95 band: a bigger area/floor delta reads as more confidently a
    real change (vs. extraction noise) while staying fully reproducible,
    same spirit as processing_router.geometric_regularity_score()."""
    magnitude = min(abs(magnitude_pct) / 100.0, 1.0)
    return round(0.6 + magnitude * 0.35, 2)


def check_building_for_change(building: models.Building, db: Session) -> Optional[models.ChangeDetection]:
    """
    Re-extracts footprint (if a drone image is present) and floor count
    (if a point cloud is present) using the real model adapters, and
    compares against this building's last recorded snapshot. Updates the
    snapshot regardless of outcome (so the next sweep has a fresh
    baseline), but only creates+returns a ChangeDetection row when
    something moved past the threshold. Returns None if nothing changed,
    if this is the first-ever check (no baseline to compare against yet),
    or if no model is currently available to re-extract from.
    """
    previous_check_at = building.last_change_check_at
    descriptions = []
    max_confidence = 0.0

    footprint_result = footprint_extractor.extract_footprint_from_imagery(building.drone_image_path)
    if footprint_result is not None:
        points, _confidence = footprint_result
        new_area = _polygon_area(points)
        if building.last_change_check_footprint_geojson:
            old_area = _polygon_area(json.loads(building.last_change_check_footprint_geojson))
            if old_area > 0:
                pct_change = ((new_area - old_area) / old_area) * 100.0
                if abs(pct_change) >= AREA_CHANGE_THRESHOLD_PCT:
                    direction = "expanded" if pct_change > 0 else "reduced"
                    descriptions.append(
                        f"Footprint {direction} by {abs(pct_change):.0f}% "
                        f"({old_area:.0f} sqm -> {new_area:.0f} sqm)"
                    )
                    max_confidence = max(max_confidence, _change_confidence(pct_change))
        building.last_change_check_footprint_geojson = json.dumps(points)

    floor_result = floor_segmenter.segment_floors_from_point_cloud(
        building.point_cloud_path, expected_num_floors=building.num_floors
    )
    if floor_result is not None:
        floor_ranges, _floor_confidence = floor_result
        new_num_floors = len(floor_ranges)
        if building.last_change_check_num_floors is not None:
            floor_delta = new_num_floors - building.last_change_check_num_floors
            if floor_delta >= FLOOR_INCREASE_THRESHOLD:
                descriptions.append(
                    f"Floor count increased from {building.last_change_check_num_floors} to {new_num_floors} "
                    f"-- possible unauthorized vertical addition"
                )
                max_confidence = max(max_confidence, _change_confidence(floor_delta * 25))
        building.last_change_check_num_floors = new_num_floors

    building.last_change_check_at = datetime.utcnow()
    db.flush()

    if not descriptions:
        return None

    cd = models.ChangeDetection(
        parcel_id=building.parcel_id,
        date_before=previous_check_at.date().isoformat() if previous_check_at else "unknown",
        date_after=datetime.utcnow().date().isoformat(),
        description=f"[{building.building_code}] " + "; ".join(descriptions),
        confidence=max_confidence,
    )
    db.add(cd)
    db.flush()
    logger.info(f"Change flagged for building {building.id}: {cd.description}")
    return cd
