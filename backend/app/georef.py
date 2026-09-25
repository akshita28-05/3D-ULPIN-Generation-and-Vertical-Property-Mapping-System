"""
One place that answers "where on Earth is this building?".

Every Building/Unit footprint in this project is stored in a local-metre
frame (x east, y north). The bulk-import pipeline anchors that frame at the
south-west corner of the imported bounding box (see
ingestion/osm_overpass.py::latlon_polygon_to_local_meters); hand-created
parcels have no recorded origin, so their footprint is centred on the
parcel's own centroid instead (the same assumption tiles/build_tileset.py
documents).

Used by: routers/map_router.py (3D map layers), auto_pipeline.py (DEM
height lookup) and routers/interop_router.py (CityJSON export).
"""
import json
import math

M_PER_DEG_LAT = 111320.0


def _m_per_deg_lon(lat: float) -> float:
    return M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6)


def local_to_latlon(points, origin_lat: float, origin_lon: float):
    """[[x, y], ...] local metres -> [[lat, lon], ...]. Exact inverse of
    osm_overpass.latlon_polygon_to_local_meters."""
    m_lon = _m_per_deg_lon(origin_lat)
    return [
        [origin_lat + (p[1] / M_PER_DEG_LAT), origin_lon + (p[0] / m_lon)]
        for p in points
    ]


def _bbox_center(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


class OriginResolver:
    """Resolves a (lat, lon) origin for a parcel's local frame. Caches the
    per-job lookups so a 5,000-building map request doesn't run 5,000
    extra queries."""

    def __init__(self, db):
        self.db = db
        self._job_origin = {}

    def _origin_for_job(self, job_id):
        if job_id not in self._job_origin:
            from . import models
            job = self.db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job_id).first()
            self._job_origin[job_id] = (job.south, job.west) if job else None
        return self._job_origin[job_id]

    def origin_for(self, parcel, local_points):
        """Returns (origin_lat, origin_lon) such that local_to_latlon(points, *origin)
        lands on the real-world location, or None if the parcel has no usable
        coordinates."""
        if parcel is None:
            return None
        if parcel.bulk_import_job_id:
            origin = self._origin_for_job(parcel.bulk_import_job_id)
            if origin:
                return origin
        if parcel.centroid_lat is None or parcel.centroid_lon is None or not local_points:
            return None
        cx, cy = _bbox_center(local_points)
        return (
            parcel.centroid_lat - cy / M_PER_DEG_LAT,
            parcel.centroid_lon - cx / _m_per_deg_lon(parcel.centroid_lat),
        )

    def ring_latlon(self, parcel, local_points):
        """Closed [[lat, lon], ...] ring for a local-metre polygon, or None."""
        origin = self.origin_for(parcel, local_points)
        if origin is None or not local_points:
            return None
        ring = local_to_latlon(local_points, *origin)
        if ring[0] != ring[-1]:
            ring.append(list(ring[0]))
        return ring


def parse_points(geojson_text):
    """footprint_geojson columns hold a bare [[x, y], ...] list (occasionally
    a GeoJSON geometry dict) -> plain [[x, y], ...] or []."""
    if not geojson_text:
        return []
    try:
        data = json.loads(geojson_text)
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        coords = data.get("coordinates")
        data = coords[0] if coords and isinstance(coords[0], list) and coords[0] and isinstance(coords[0][0], list) else coords
    if not isinstance(data, list):
        return []
    return [[float(p[0]), float(p[1])] for p in data if isinstance(p, (list, tuple)) and len(p) >= 2]


def polygon_area(points) -> float:
    n = len(points)
    if n < 3:
        return 0.0
    s = sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))
    return abs(s) / 2.0
