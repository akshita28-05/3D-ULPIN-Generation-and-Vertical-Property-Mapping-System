"""
Automated 3D-ULPIN pipeline -- the "no manual steps" path.

Before this module, a bulk import created parcels + buildings and then a
surveyor still had to open each building and click "Generate 3D ULPINs".
Now, right after buildings are fetched (OSM live, or the local Microsoft
footprints table) this runs by itself, per building:

    floor evidence  ->  floors  ->  units (vertical parcels)  ->  3D ULPINs
                    ->  topology validation + anomaly flags  ->  review queue

Nothing is auto-approved. Every unit still lands in the verifier's queue --
the automation only removes the data-entry, not the human sign-off.

Floor-count evidence is always disclosed with one of three states
(same idea as the public BoundaryLens prototype, see the SIH26011 landscape
report), derived from what is already stored on the building -- no new
columns needed:

  OBSERVED          a real source stated it (OSM building:levels / height,
                    a surveyor's entry, a LiDAR point cloud).
  PREDICTED         estimated from evidence, with a confidence:
                      dem_estimated        Copernicus GLO-30 roof-minus-ground
                                           (ai/heights/ndsm_estimator.py)
                      predicted_knn        median of nearby OBSERVED buildings
                      predicted_area_prior low-confidence footprint-size prior,
                                           used only when nothing better exists
  NOT_DETERMINABLE  no usable evidence (e.g. a footprint too small to be a
                    dwelling). No floors/units are invented; it is left for a
                    surveyor.

None of the PREDICTED methods is a trained model, and none of it is presented
as a survey -- the source tag is stored in Building.floor_source and shown in
the UI next to the confidence.
"""
import logging
import math
import statistics
from collections import defaultdict

from sqlalchemy.orm import Session

from . import models, georef, validation as validation_service
from .ai.heights import ndsm_estimator
from .ai.vegetation import ndvi_check

logger = logging.getLogger("landsphere.auto_pipeline")

OBSERVED = "OBSERVED"
PREDICTED = "PREDICTED"
NOT_DETERMINABLE = "NOT_DETERMINABLE"

FLOOR_HEIGHT_M = 3.0
MIN_PREDICT_AREA_SQM = 12.0
DEM_MIN_AREA_SQM = 150.0
KNN_K = 7
KNN_MIN_NEIGHBOURS = 4
KNN_RADIUS_M = 600.0
MAX_PLAUSIBLE_FLOORS = 80



def floor_evidence_state(building) -> str:
    source = (building.floor_source or "").lower()
    has_floors = bool(building.num_floors and building.num_floors > 0)
    if source.startswith("predicted") or source == "dem_estimated":
        return PREDICTED if has_floors else NOT_DETERMINABLE
    if source in ("manual", "ml_model") and has_floors:
        return OBSERVED
    return NOT_DETERMINABLE


def floor_method_label(building) -> str:
    source = (building.floor_source or "").lower()
    return {
        "manual": "reported / surveyed",
        "ml_model": "point-cloud model",
        "dem_estimated": "Copernicus DEM (roof minus ground)",
        "predicted_knn": "median of nearby observed buildings",
        "predicted_area_prior": "footprint-size prior (low confidence)",
        "unsurveyed": "no evidence yet",
    }.get(source, source or "unknown")


def category_of(building_type) -> str:
    """Collapses OSM's long tail of building=* values into the handful of
    categories the map legend/filters use."""
    t = (building_type or "").lower()
    if t in ("residential", "apartments", "house", "detached", "semidetached_house", "terrace",
             "dormitory", "bungalow", "static_caravan"):
        return "residential"
    if t in ("commercial", "retail", "office", "supermarket", "hotel", "kiosk", "industrial", "warehouse"):
        return "commercial"
    if t == "mixed":
        return "mixed"
    if t in ("institutional", "school", "hospital", "university", "public", "government", "civic",
             "church", "temple", "mosque", "college", "religious"):
        return "institutional"
    return "other"



class NeighbourIndex:
    """Grid-bucketed lookup of OBSERVED buildings so predicting 5,000
    buildings doesn't cost 5,000 x N distance calculations."""

    CELL_DEG = 0.006

    def __init__(self, entries):
        self._cells = defaultdict(list)
        for lat, lon, floors in entries:
            self._cells[self._key(lat, lon)].append((lat, lon, floors))
        self.size = len(entries)

    def _key(self, lat, lon):
        return (int(math.floor(lat / self.CELL_DEG)), int(math.floor(lon / self.CELL_DEG)))

    def nearest(self, lat, lon, k=KNN_K, radius_m=KNN_RADIUS_M):
        ky, kx = self._key(lat, lon)
        m_lon = 111320.0 * max(math.cos(math.radians(lat)), 1e-6)
        found = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for (blat, blon, floors) in self._cells.get((ky + dy, kx + dx), ()):
                    dist = math.hypot((blat - lat) * 111320.0, (blon - lon) * m_lon)
                    if dist <= radius_m:
                        found.append((dist, floors))
        found.sort(key=lambda t: t[0])
        return found[:k]


def build_neighbour_index(db: Session, south, west, north, east, pad_deg=0.01) -> NeighbourIndex:
    rows = (
        db.query(models.Building.num_floors, models.Parcel.centroid_lat, models.Parcel.centroid_lon)
        .join(models.Parcel, models.Parcel.id == models.Building.parcel_id)
        .filter(
            models.Building.floor_source.in_(["manual", "ml_model"]),
            models.Building.num_floors.isnot(None),
            models.Building.num_floors > 0,
            models.Building.num_floors <= MAX_PLAUSIBLE_FLOORS,
            models.Parcel.centroid_lat.between(south - pad_deg, north + pad_deg),
            models.Parcel.centroid_lon.between(west - pad_deg, east + pad_deg),
        )
        .all()
    )
    return NeighbourIndex([(lat, lon, floors) for floors, lat, lon in rows if lat is not None and lon is not None])


def _knn_candidate(index: NeighbourIndex, lat, lon):
    neighbours = index.nearest(lat, lon)
    if len(neighbours) < KNN_MIN_NEIGHBOURS:
        return None
    floors_seen = [f for _, f in neighbours]
    median = int(round(statistics.median(floors_seen)))
    median = max(1, median)
    agreement = sum(1 for f in floors_seen if abs(f - median) <= 1) / len(floors_seen)
    confidence = round(0.30 + 0.50 * agreement * min(1.0, len(floors_seen) / KNN_K), 2)
    return {
        "num_floors": median, "height_m": round(median * FLOOR_HEIGHT_M, 1),
        "confidence": confidence, "source": "predicted_knn",
        "note": f"median of {len(floors_seen)} observed buildings within {KNN_RADIUS_M:.0f} m",
    }


def _dem_candidate(area_sqm, latlon_ring, lat, lon):
    if area_sqm < DEM_MIN_AREA_SQM or not latlon_ring:
        return None
    if not ndsm_estimator.DEM_HEIGHT_ESTIMATION_ENABLED:
        return None
    est = ndsm_estimator.estimate_building_height_from_dem([(p[0], p[1]) for p in latlon_ring], lat, lon)
    if not est:
        return None
    return {
        "num_floors": est["num_floors"], "height_m": est["height_m"],
        "confidence": est["confidence"], "source": "dem_estimated", "note": est["source"],
    }


def _prior_candidate(area_sqm):
    floors = 1 if area_sqm < 400 else 2
    return {
        "num_floors": floors, "height_m": round(floors * FLOOR_HEIGHT_M, 1),
        "confidence": 0.30 if area_sqm < 400 else 0.25, "source": "predicted_area_prior",
        "note": "footprint-size prior -- nothing better available",
    }


def predict_floors(area_sqm, lat, lon, latlon_ring, index: NeighbourIndex):
    """Best-confidence PREDICTED candidate, or None (NOT_DETERMINABLE)."""
    if area_sqm < MIN_PREDICT_AREA_SQM:
        return None
    candidates = [
        c for c in (
            _knn_candidate(index, lat, lon),
            _dem_candidate(area_sqm, latlon_ring, lat, lon),
        ) if c
    ]
    if not candidates:
        candidates = [_prior_candidate(area_sqm)]
    return max(candidates, key=lambda c: c["confidence"])



def _persist_validation(db, building, results):
    for r in results:
        db.add(models.ValidationResult(
            building_id=building.id, check_type=r["check_type"],
            severity=r["severity"], message=r["message"],
        ))


_NDVI_TRUSTED_TYPE_SOURCES = {"manual", "osm"}


def _ndvi_check_if_untrusted(building, parcel, points, area_sqm, resolver):
    """
    Returns ndvi_check.check_vegetation_ndvi()'s result dict (or None) for
    this building's footprint, but only bothers calling it at all when the
    footprint's source is NOT already human/OSM-confirmed -- running a
    satellite vegetation check against a surveyor's own entry or a real
    OSM building tag would be second-guessing a stronger source with a
    weaker one, backwards from what this check is for.
    """
    type_source = (building.building_type_source or "").lower()
    if type_source in _NDVI_TRUSTED_TYPE_SOURCES:
        return None
    ring = resolver.ring_latlon(parcel, points)
    if ring is None:
        return None
    return ndvi_check.check_vegetation_ndvi(ring, area_sqm)


def finalize_building(db: Session, building, parcel, index: NeighbourIndex, batch_median_area, resolver):
    """
    Floors -> units -> 3D ULPINs -> validation for ONE building. Returns a
    small dict describing what happened (used for the job summary/tests).
    Idempotent: a building that already has units is left alone.
    """
    from .routers import processing_router as pr

    already = (
        db.query(models.Unit.id).join(models.Floor).filter(models.Floor.building_id == building.id).first()
    )
    if already:
        return {"state": floor_evidence_state(building), "units": 0, "skipped": True, "flags": 0}

    points = georef.parse_points(building.footprint_geojson)
    if len(points) < 3:
        return {"state": NOT_DETERMINABLE, "units": 0, "skipped": True, "flags": 0}

    area = georef.polygon_area(points)
    state = floor_evidence_state(building)
    floor_confidence = None

    if state == NOT_DETERMINABLE:
        lat, lon = parcel.centroid_lat, parcel.centroid_lon
        ring = resolver.ring_latlon(parcel, points)
        prediction = predict_floors(area, lat, lon, ring, index) if lat is not None and lon is not None else None
        if prediction is None:
            return {"state": NOT_DETERMINABLE, "units": 0, "skipped": False, "flags": 0}
        building.num_floors = prediction["num_floors"]
        building.height_m = prediction["height_m"]
        building.floor_source = prediction["source"]
        floor_confidence = prediction["confidence"]
        state = PREDICTED

    if not building.num_floors or building.num_floors < 1:
        return {"state": NOT_DETERMINABLE, "units": 0, "skipped": False, "flags": 0}

    for old in db.query(models.Floor).filter(models.Floor.building_id == building.id).all():
        db.delete(old)
    db.flush()

    height_m = building.height_m if building.height_m and building.height_m > 0 else building.num_floors * FLOOR_HEIGHT_M
    building.height_m = height_m
    floor_height = height_m / building.num_floors
    footprint_confidence = pr.geometric_regularity_score(points)
    if building.ai_confidence is None:
        building.ai_confidence = footprint_confidence

    floors = []
    for i in range(1, building.num_floors + 1):
        floor = models.Floor(
            building_id=building.id,
            floor_code=f"F{i:02d}", floor_number=i,
            z_min=round((i - 1) * floor_height, 2), z_max=round(i * floor_height, 2),
            ai_confidence=floor_confidence if floor_confidence is not None else footprint_confidence,
        )
        db.add(floor)
        floors.append(floor)
    db.flush()

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    units = pr.delineate_units(building, floors, w, d, (min(xs), min(ys)), db, parcel.ulpin_2d, floor_height)
    if floor_confidence is not None:
        for u in units:
            u.ai_confidence = min(u.ai_confidence or 1.0, floor_confidence)

    results = pr.run_topology_validation(building, floors, units, db)
    anomalies = (
        validation_service.check_slenderness(height_m, w, d, building.name or building.building_code)
        + validation_service.check_area_outlier(area, batch_median_area, building.name or building.building_code)
        + validation_service.check_vegetation_ndvi(
            _ndvi_check_if_untrusted(building, parcel, points, area, resolver),
            building.name or building.building_code,
        )
    )
    _persist_validation(db, building, anomalies)
    db.flush()
    return {"state": state, "units": len(units), "skipped": False, "flags": len(results) + len(anomalies)}


def finalize_job(db: Session, job) -> dict:
    """Runs finalize_building over every building a BulkImportJob created."""
    from .georef import OriginResolver

    rows = (
        db.query(models.Building, models.Parcel)
        .join(models.Parcel, models.Parcel.id == models.Building.parcel_id)
        .filter(models.Parcel.bulk_import_job_id == job.id)
        .all()
    )
    areas = []
    for b, _ in rows:
        a = georef.polygon_area(georef.parse_points(b.footprint_geojson))
        if a > 0:
            areas.append(a)
    batch_median = statistics.median(areas) if areas else None

    index = build_neighbour_index(db, job.south, job.west, job.north, job.east)
    resolver = OriginResolver(db)
    counts = {"buildings": len(rows), OBSERVED: 0, PREDICTED: 0, NOT_DETERMINABLE: 0, "units": 0, "flags": 0, "failed": 0}

    for i, (building, parcel) in enumerate(rows, start=1):
        try:
            with db.begin_nested():
                out = finalize_building(db, building, parcel, index, batch_median, resolver)
            counts[out["state"]] += 1
            counts["units"] += out["units"]
            counts["flags"] += out["flags"]
        except Exception:
            logger.exception(f"Auto-finalize failed for building {building.id}; it keeps its imported state.")
            counts["failed"] += 1
        if i % 50 == 0:
            db.commit()
    job.flagged_buildings = (job.flagged_buildings or 0) + counts["flags"]
    db.commit()
    return counts


def job_summary(db: Session, job) -> dict:
    """Live counts for the UI's 'what did the automation just do' card."""
    rows = (
        db.query(models.Building)
        .join(models.Parcel, models.Parcel.id == models.Building.parcel_id)
        .filter(models.Parcel.bulk_import_job_id == job.id)
        .all()
    )
    summary = {"buildings": len(rows), OBSERVED: 0, PREDICTED: 0, NOT_DETERMINABLE: 0, "units": 0}
    for b in rows:
        summary[floor_evidence_state(b)] += 1
    if rows:
        summary["units"] = (
            db.query(models.Unit.id).join(models.Floor).join(models.Building, models.Building.id == models.Floor.building_id)
            .join(models.Parcel, models.Parcel.id == models.Building.parcel_id)
            .filter(models.Parcel.bulk_import_job_id == job.id).count()
        )
    try:
        from .infra import service as infra_service
        summary["infra"] = infra_service.counts_for_job(db, job)
    except Exception:
        summary["infra"] = None
    return summary
