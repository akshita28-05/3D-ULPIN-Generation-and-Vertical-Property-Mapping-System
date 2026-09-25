"""
Local-database counterpart to ingestion/osm_overpass.py, for the
Microsoft Global ML Building Footprints dataset (see
scripts/load_ms_footprints.py for how rows get into
external_building_footprints in the first place -- this module only
QUERIES what's already loaded, since unlike OSM/Overpass there's no live
API to call per-request; the dataset is only distributed as bulk
per-quadkey downloads).

Every footprint here came from a satellite-imagery ML detector, not a
community mapper or a surveyor: there is no name, address, or real
height/floor-count for any of these rows in the source dataset itself
(height is a documented -1 "unknown" sentinel for the vast majority of
tiles). Callers must not treat these buildings as more verified than
that -- see bulk_import_router.py's handling of source="ms_footprints"
for the disclosed placeholder convention it applies.
"""
import json


def query_local_footprints_in_bbox(db, south: float, west: float, north: float, east: float, limit: int = 5000):
    """
    Returns every loaded footprint whose centroid falls inside the given
    bbox, as plain dicts. Centroid-based, not true polygon-intersection --
    fine for a bbox drawn by hand on a map (the same imprecision at the
    very edge of the box that Overpass's own bbox filter has), and far
    cheaper than a real spatial query without requiring PostGIS on the
    SQLite dev path.
    """
    from .. import models

    rows = (
        db.query(models.ExternalBuildingFootprint)
        .filter(
            models.ExternalBuildingFootprint.centroid_lat.between(south, north),
            models.ExternalBuildingFootprint.centroid_lon.between(west, east),
        )
        .limit(limit)
        .all()
    )

    results = []
    for r in rows:
        try:
            ring = json.loads(r.footprint_latlon_geojson)
        except (TypeError, ValueError):
            continue
        if not ring or len(ring) < 3:
            continue
        results.append({
            "id": r.id,
            "confidence": r.confidence,
            "height_m": r.height_m,
            "geometry": ring,
        })
    return results
