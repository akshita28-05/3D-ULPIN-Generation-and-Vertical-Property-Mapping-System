"""Detection of elevated corridors / air-right envelopes and parking for a parcel.

    POST /api/detect/parcels/{parcel_id}/corridors   (OSM + optional LiDAR, preview or commit)
    POST /api/detect/parcels/{parcel_id}/parking     (OSM parking areas around the parcel)
    POST /api/detect/buildings/{building_id}/parking-stalls   (painted stalls on the building's orthophoto)

Everything returned is a PROPOSAL for verifier review (see ai/corridors/__init__.py).
`commit=true` stores corridors as AirRightCorridor rows with source /
detection_confidence / height_source filled in, so the registry never shows a
detected value as if a surveyor had typed it.
"""
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..georef import OriginResolver, parse_points, M_PER_DEG_LAT, _m_per_deg_lon
from ..ingestion import osm_overpass
from ..ai.corridors import osm_detector, lidar_detector, parking_detector, conflicts, geom2d

logger = logging.getLogger("landsphere.detect")
router = APIRouter(prefix="/api/detect", tags=["detection"])

MAX_CLOUD_POINTS = int(os.getenv("CORRIDOR_MAX_CLOUD_POINTS", "3000000"))


class CorridorDetectRequest(BaseModel):
    use_osm: bool = True
    point_cloud_dataset_id: Optional[str] = None
    margin_m: float = 60.0
    commit: bool = False


def _parcel_frame(db, parcel_id):
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    fp = parse_points(parcel.footprint_geojson)
    if len(fp) < 3:
        raise HTTPException(status_code=400, detail="Parcel has no usable footprint")
    origin = OriginResolver(db).origin_for(parcel, fp)
    if origin is None:
        raise HTTPException(status_code=400, detail="Parcel has no lat/lon origin, cannot query OSM")
    return parcel, fp, origin


def _bbox_latlon(fp, origin, margin):
    xs = [p[0] for p in fp]; ys = [p[1] for p in fp]
    m_lon = _m_per_deg_lon(origin[0])
    return (origin[0] + (min(ys) - margin) / M_PER_DEG_LAT, origin[1] + (min(xs) - margin) / m_lon,
            origin[0] + (max(ys) + margin) / M_PER_DEG_LAT, origin[1] + (max(xs) + margin) / m_lon)


def _fetch_osm(bbox):
    query = osm_detector.build_query(*bbox, timeout=osm_overpass.REQUEST_TIMEOUT_S)
    errors = []
    for ep in osm_overpass.OVERPASS_ENDPOINTS:
        data, err = osm_overpass._query_one_endpoint(ep, query)
        if data is not None:
            return data.get("elements", []), None
        errors.append(err)
    return None, "; ".join(errors)


def _load_cloud(db, dataset_id):
    ds = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    if not ds or not ds.storage_path or not os.path.isfile(ds.storage_path):
        raise HTTPException(status_code=404, detail="Point-cloud dataset or its file not found")
    try:
        import laspy
        import numpy as np
    except ImportError:
        raise HTTPException(status_code=501, detail="laspy not installed (pip install -r requirements-ml.txt)")
    las = laspy.read(ds.storage_path)
    pts = np.column_stack([las.x, las.y, las.z]).astype(float)
    if len(pts) > MAX_CLOUD_POINTS:
        pts = pts[np.random.default_rng(0).choice(len(pts), MAX_CLOUD_POINTS, replace=False)]
    return pts


@router.post("/parcels/{parcel_id}/corridors")
def detect_corridors(
    parcel_id: str, payload: CorridorDetectRequest, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    parcel, fp, origin = _parcel_frame(db, parcel_id)
    xs = [p[0] for p in fp]; ys = [p[1] for p in fp]
    m = payload.margin_m
    evidence = {"osm": "not_requested", "lidar": "not_requested"}

    osm_corr = []
    if payload.use_osm:
        elements, err = _fetch_osm(_bbox_latlon(fp, origin, m))
        if elements is None:
            evidence["osm"] = f"unavailable: {err}"
        else:
            evidence["osm"] = f"ok ({len(elements)} elements)"
            osm_corr = osm_detector.classify_elements(elements, origin)["corridors"]
            def _near(c):
                px = [q[0] for q in c["polygon_local"]]; py = [q[1] for q in c["polygon_local"]]
                return not (max(px) < min(xs) - m or min(px) > max(xs) + m or max(py) < min(ys) - m or min(py) > max(ys) + m)
            osm_corr = [c for c in osm_corr if _near(c)]

    lidar = []
    if payload.point_cloud_dataset_id:
        blds = db.query(models.Building).filter(models.Building.parcel_id == parcel.id).all()
        cloud = _load_cloud(db, payload.point_cloud_dataset_id)
        lidar = lidar_detector.detect_elevated_structures(cloud, building_footprints=[parse_points(b.footprint_geojson) for b in blds if b.footprint_geojson])
        evidence["lidar"] = f"ok ({len(lidar)} elevated structures; cloud assumed to be in the parcel's local metre frame)"
    if evidence["osm"].startswith("unavailable") and not lidar:
        raise HTTPException(status_code=503, detail=f"No evidence source available. OSM: {evidence['osm']}. Upload a point cloud or retry.")

    fused = lidar_detector.fuse(osm_corr, lidar)
    blds = [{"id": b.building_code, "footprint": parse_points(b.footprint_geojson), "height_m": b.height_m}
            for b in db.query(models.Building).filter(models.Building.parcel_id == parcel.id).all() if b.footprint_geojson]

    results = []
    for c in fused:
        poly = c["polygon_local"]
        if geom2d.is_convex(fp):
            on_parcel = geom2d.clip_polygon_convex(poly, fp)
        else:
            on_parcel = geom2d.clip_polygon_convex(poly, [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)]])
        overlap = geom2d.polygon_area(on_parcel) if on_parcel else 0.0
        status, why = conflicts.assess(poly, c["height_min_m"], c["height_max_m"], blds)
        rec = {**{k: v for k, v in c.items() if k not in ("centerline_local",)},
               "crosses_parcel": overlap > 1.0, "overlap_on_parcel_sqm": round(overlap, 1),
               "geometry_on_parcel": on_parcel, "conflict_status": status, "conflict_reasons": why}
        if payload.commit and rec["crosses_parcel"]:
            row = models.AirRightCorridor(
                parcel_id=parcel.id, corridor_type=c["corridor_type"],
                height_min_m=c["height_min_m"], height_max_m=c["height_max_m"],
                geometry_geojson=json.dumps(on_parcel), conflict_status=status,
                source=c["source"], detection_confidence=c["confidence"], height_source=c["height_source"],
                detection_notes=json.dumps(c["notes"] + why),
            )
            db.add(row); db.flush()
            rec["corridor_id"] = row.id
        results.append(rec)
    if payload.commit:
        db.commit()
    return {"parcel_id": parcel.id, "evidence": evidence, "committed": payload.commit,
            "proposals": results,
            "disclaimer": "Proposals for verifier review, not an official record. Heights marked assumed_default are planning defaults."}


@router.post("/parcels/{parcel_id}/parking")
def detect_parking(
    parcel_id: str, margin_m: float = 30.0, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    parcel, fp, origin = _parcel_frame(db, parcel_id)
    elements, err = _fetch_osm(_bbox_latlon(fp, origin, margin_m))
    if elements is None:
        raise HTTPException(status_code=503, detail=f"OSM unavailable: {err}")
    areas = osm_detector.classify_parking(elements, origin)
    xs = [p[0] for p in fp]; ys = [p[1] for p in fp]
    box = [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)], [min(xs), min(ys)]]
    for a in areas:
        a["touches_parcel"] = geom2d.overlap_area(a["polygon_local"], box) > 1.0
    return {"parcel_id": parcel.id, "parking_areas": areas}


@router.post("/buildings/{building_id}/parking-stalls")
def detect_stalls(
    building_id: str, gsd_m_per_px: float, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    b = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not b or not b.drone_image_path or not os.path.isfile(b.drone_image_path):
        raise HTTPException(status_code=404, detail="Building has no uploaded orthophoto")
    try:
        import cv2
    except ImportError:
        raise HTTPException(status_code=501, detail="opencv not installed (requirements-ml.txt)")
    img = cv2.imread(b.drone_image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image")
    return parking_detector.detect_painted_stalls(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), gsd_m_per_px)
