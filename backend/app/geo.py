"""
PostGIS sync helpers.

While footprint_geojson / geometry_geojson (Text) remain the columns every
existing router reads and writes, this module keeps the new `geom`
(geoalchemy2.Geometry) column on each spatial model consistent with them
on Postgres. Call sync_geom_from_geojson(obj) right after setting/updating
obj.footprint_geojson or obj.geometry_geojson and before commit.

No-op (and safe to call unconditionally) when not running against
Postgres, so callers don't need their own IS_POSTGIS branches.
"""
import json

from sqlalchemy import func

from .database import IS_POSTGIS

_GEOM_CONFIG = {
    "Parcel": ("footprint_geojson", "geom", "Polygon"),
    "Building": ("footprint_geojson", "geom", "Polygon"),
    "UndergroundAsset": ("geometry_geojson", "geom", "LineString"),
    "AirRightCorridor": ("geometry_geojson", "geom", "Polygon"),
}


def sync_geom_from_geojson(obj) -> None:
    """Set obj.geom from obj's existing GeoJSON text column. Safe to call
    on SQLite (no-op) or with missing/invalid GeoJSON (leaves geom untouched
    rather than raising -- geometry backfill failures shouldn't break a
    parcel/building/asset create or update)."""
    if not IS_POSTGIS:
        return

    config = _GEOM_CONFIG.get(type(obj).__name__)
    if not config:
        return
    geojson_attr, geom_attr, geom_type = config

    raw = getattr(obj, geojson_attr, None)
    if not raw:
        return

    try:
        coords = json.loads(raw)
    except (TypeError, ValueError):
        return
    if not coords:
        return

    if geom_type == "LineString":
        geometry = {"type": "LineString", "coordinates": coords}
    else:
        ring = coords if isinstance(coords[0][0], (int, float)) else coords[0]
        geometry = {"type": "Polygon", "coordinates": [ring]}

    setattr(obj, geom_attr, func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), 4326))
