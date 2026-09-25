"""
Read-only data feeds for the 3D map (frontend/src/components/Map3D.jsx).

  GET /api/map/buildings   registered buildings (parcel -> building -> units) as
                           lat/lon GeoJSON, ready to extrude.
  GET /api/map/footprints  the region's own pre-loaded footprints (Microsoft
                           Building Footprints table) that haven't been
                           registered yet -- so the map shows the data you
                           loaded straight away, with no import click.
  GET /api/map/infrastructure  underground structures + elevated / air-right corridors found
                           automatically in open data (see app/infra/), as lon/lat GeoJSON.
  GET /api/map/stats       the headline numbers (buildings / 3D units / tallest ...).
  GET /api/map/coverage    where the loaded data actually is ("Zoom to data").

All public and read-only, same as GET /api/parcels.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, cast, Numeric
from sqlalchemy.orm import Session

from .. import models, georef, cache
from ..infra import service as infra_service
from ..auto_pipeline import floor_evidence_state, floor_method_label, category_of, FLOOR_HEIGHT_M
from ..database import get_db

router = APIRouter(prefix="/api/map", tags=["map"])

PLACEHOLDER_HEIGHT_M = 6.0


def _feature(ring_latlon, props):
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring_latlon]]},
    }


@router.get("/buildings")
def map_buildings(
    south: float | None = None, west: float | None = None, north: float | None = None, east: float | None = None,
    limit: int = Query(5000, le=10000),
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.Building, models.Parcel)
        .join(models.Parcel, models.Parcel.id == models.Building.parcel_id)
        .filter(models.Parcel.centroid_lat.isnot(None), models.Parcel.centroid_lon.isnot(None))
    )
    if None not in (south, west, north, east):
        q = q.filter(models.Parcel.centroid_lat.between(south, north), models.Parcel.centroid_lon.between(west, east))
    rows = q.order_by(func.coalesce(models.Building.num_floors, 0).desc()).limit(limit).all()
    if not rows:
        return {"type": "FeatureCollection", "features": []}

    ids = [b.id for b, _ in rows]
    unit_counts, approved_counts = {}, {}
    for start in range(0, len(ids), 800):
        chunk = ids[start:start + 800]
        for building_id, status, n in (
            db.query(models.Floor.building_id, models.Unit.verification_status, func.count(models.Unit.id))
            .join(models.Unit, models.Unit.floor_id == models.Floor.id)
            .filter(models.Floor.building_id.in_(chunk))
            .group_by(models.Floor.building_id, models.Unit.verification_status)
            .all()
        ):
            unit_counts[building_id] = unit_counts.get(building_id, 0) + n
            if status == models.VerificationStatus.approved:
                approved_counts[building_id] = approved_counts.get(building_id, 0) + n

    resolver = georef.OriginResolver(db)
    features = []
    for b, p in rows:
        points = georef.parse_points(b.footprint_geojson)
        ring = resolver.ring_latlon(p, points)
        if not ring:
            continue
        height = b.height_m or (b.num_floors * FLOOR_HEIGHT_M if b.num_floors else None)
        features.append(_feature(ring, {
            "id": b.id, "parcel_id": p.id, "ulpin_2d": p.ulpin_2d,
            "name": b.name or f"Building {b.building_code}",
            "address": p.address,
            "building_type": b.building_type or "unspecified",
            "category": category_of(b.building_type),
            "num_floors": b.num_floors, "height_m": height,
            "render_height": height if height else PLACEHOLDER_HEIGHT_M,
            "height_known": bool(height),
            "floor_state": floor_evidence_state(b),
            "floor_method": floor_method_label(b),
            "units": unit_counts.get(b.id, 0),
            "approved_units": approved_counts.get(b.id, 0),
            "consistency_flag": bool(b.consistency_flag),
            "lat": p.centroid_lat, "lon": p.centroid_lon,
        }))
    return {"type": "FeatureCollection", "features": features}


@router.get("/footprints")
def map_region_footprints(
    south: float, west: float, north: float, east: float,
    limit: int = Query(4000, le=8000),
    db: Session = Depends(get_db),
):
    """Pre-loaded region footprints inside the viewport that are NOT yet
    registered (registered ones come from /buildings, so nothing is drawn twice)."""
    registered = db.query(models.Building.ms_footprint_id).filter(models.Building.ms_footprint_id.isnot(None))
    rows = (
        db.query(models.ExternalBuildingFootprint)
        .filter(
            models.ExternalBuildingFootprint.centroid_lat.between(south, north),
            models.ExternalBuildingFootprint.centroid_lon.between(west, east),
            ~models.ExternalBuildingFootprint.id.in_(registered),
        )
        .limit(limit)
        .all()
    )
    features = []
    for r in rows:
        try:
            ring = json.loads(r.footprint_latlon_geojson)
        except (TypeError, ValueError):
            continue
        if not ring or len(ring) < 3:
            continue
        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]
        features.append(_feature(ring, {
            "id": r.id,
            "render_height": r.height_m if r.height_m and r.height_m > 0 else PLACEHOLDER_HEIGHT_M,
            "height_known": bool(r.height_m and r.height_m > 0),
            "confidence": r.confidence,
        }))
    return {"type": "FeatureCollection", "features": features, "truncated": len(rows) >= limit}


@router.get("/infrastructure")
def map_infrastructure(
    south: float, west: float, north: float, east: float,
    limit: int = Query(4000, le=8000),
    db: Session = Depends(get_db),
):
    """Underground + air-right features inside the viewport (already scanned cells only --
    POST /api/infra/scan fills them in)."""
    rows = infra_service.features_in_bbox(db, south, west, north, east, limit=limit)
    return {"type": "FeatureCollection", "features": [infra_service.feature_to_geojson(r) for r in rows],
            "truncated": len(rows) >= limit}


@router.get("/stats")
def map_stats(db: Session = Depends(get_db)):
    cached = cache.cache_get("map:stats")
    if cached:
        return cached
    buildings = db.query(models.Building).all()
    categories = {"residential": 0, "commercial": 0, "mixed": 0, "institutional": 0, "other": 0}
    states = {"OBSERVED": 0, "PREDICTED": 0, "NOT_DETERMINABLE": 0}
    max_floors = 0
    for b in buildings:
        categories[category_of(b.building_type)] += 1
        states[floor_evidence_state(b)] += 1
        max_floors = max(max_floors, b.num_floors or 0)
    result = {
        "buildings": len(buildings),
        "units": db.query(models.Unit).count(),
        "approved_units": db.query(models.Unit).filter(models.Unit.verification_status == models.VerificationStatus.approved).count(),
        "max_floors": max_floors,
        "areas": db.query(models.Parcel.district_code).distinct().count(),
        "categories": categories,
        "floor_states": states,
        "region_footprints": db.query(models.ExternalBuildingFootprint).count(),
        "underground_assets": db.query(models.UndergroundAsset).count(),
        "infra_underground": db.query(models.InfraFeature).filter(models.InfraFeature.kind == "underground").count(),
        "infra_air": db.query(models.InfraFeature).filter(models.InfraFeature.kind == "air").count(),
        "air_right_corridors": db.query(models.AirRightCorridor).count(),
    }
    cache.cache_set("map:stats", result, ttl_seconds=10)
    return result


@router.get("/coverage")
def map_coverage(db: Session = Depends(get_db)):
    """Where the loaded region data is densest, so the map can offer a
    'Zoom to data' button WITHOUT moving the default map location."""
    cached = cache.cache_get("map:coverage")
    if cached is not None:
        return cached
    E = models.ExternalBuildingFootprint
    cell_lat = func.round(cast(E.centroid_lat, Numeric), 2)
    cell_lon = func.round(cast(E.centroid_lon, Numeric), 2)
    top = (
        db.query(cell_lat, cell_lon, func.count(E.id))
        .group_by(cell_lat, cell_lon).order_by(func.count(E.id).desc()).first()
    )
    if top is None:
        p = db.query(func.avg(models.Parcel.centroid_lat), func.avg(models.Parcel.centroid_lon)).first()
        result = {"has_data": bool(p and p[0]), "lat": p[0] if p else None, "lon": p[1] if p else None, "count": 0}
    else:
        result = {"has_data": True, "lat": float(top[0]), "lon": float(top[1]), "count": int(top[2])}
    cache.cache_set("map:coverage", result, ttl_seconds=600)
    return result
