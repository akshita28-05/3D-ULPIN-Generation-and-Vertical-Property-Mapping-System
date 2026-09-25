"""
Real spatial queries, enabled once DATABASE_URL points at Postgres+PostGIS
and scripts/migrate_to_postgis.py has been run (see app/geo.py and
app/models.py -- the `geom` columns this router queries only exist under
IS_POSTGIS). On SQLite (the zero-setup demo default) every endpoint here
returns 501, rather than silently returning wrong/empty results.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db, IS_POSTGIS

try:
    from geoalchemy2.types import Geography
except ImportError:
    Geography = None

router = APIRouter(prefix="/api/spatial", tags=["spatial"])


def _require_postgis():
    if not IS_POSTGIS:
        raise HTTPException(
            status_code=501,
            detail="Spatial queries require Postgres+PostGIS. This server is running on SQLite "
                   "(the zero-setup demo backend). Set DATABASE_URL to a Postgres connection string, "
                   "run scripts/migrate_to_postgis.py, and restart.",
        )


@router.get("/parcels/near")
def parcels_within_radius(
    lat: float = Query(..., description="Center latitude, WGS84"),
    lon: float = Query(..., description="Center longitude, WGS84"),
    radius_m: float = Query(500, gt=0, le=20000, description="Search radius in meters"),
    db: Session = Depends(get_db),
):
    """
    Real spatial query: every parcel whose stored geometry is within
    radius_m meters of (lat, lon). Uses ST_DWithin on the geography cast of
    both sides so the distance is measured in meters on the ellipsoid, not
    in degrees -- the bug you'd get comparing raw SRID-4326 geometries
    directly with a "distance" filter.
    """
    _require_postgis()

    point = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography)
    parcel_geog = cast(models.Parcel.geom, Geography)

    results = (
        db.query(models.Parcel, func.ST_Distance(parcel_geog, point).label("distance_m"))
        .filter(func.ST_DWithin(parcel_geog, point, radius_m))
        .order_by("distance_m")
        .all()
    )

    return [
        {
            "parcel_id": p.id,
            "ulpin_2d": p.ulpin_2d,
            "address": p.address,
            "distance_m": round(float(dist), 1) if dist is not None else None,
        }
        for p, dist in results
    ]


@router.post("/underground-assets/intersecting")
def underground_assets_intersecting(
    zone_geojson: dict,
    db: Session = Depends(get_db),
):
    """
    Real spatial query: every underground utility whose stored geometry
    intersects the given excavation-zone polygon (POST body: a raw GeoJSON
    Polygon/MultiPolygon geometry object, e.g.
    {"type": "Polygon", "coordinates": [[[lon,lat], ...]]}).
    """
    _require_postgis()

    zone = func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(zone_geojson)), 4326)
    assets = (
        db.query(models.UndergroundAsset)
        .filter(func.ST_Intersects(models.UndergroundAsset.geom, zone))
        .all()
    )

    return [
        {
            "id": a.id,
            "parcel_id": a.parcel_id,
            "asset_type": a.asset_type,
            "depth_min_m": a.depth_min_m,
            "depth_max_m": a.depth_max_m,
            "quality_level": a.quality_level.value if a.quality_level else None,
        }
        for a in assets
    ]
