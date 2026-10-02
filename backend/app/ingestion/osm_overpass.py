"""
Bounding-box building bulk-import from OpenStreetMap via the Overpass API.

"Select an area on the map -> fetch every building in it", additive to
the single-building AI-extraction pipeline in
routers/processing_router.py. A building created this way can still
separately go through the AI footprint/floor pipeline later if imagery
or point clouds are uploaded for it.

No trained model involved -- an HTTP query against a public API plus
deterministic geometry/unit conversion, same category as
geocode_router.py's Nominatim calls.

OSM height/building:levels tags are crowd-sourced and often missing or
wrong: a building with no usable tags is imported with height_m/
num_floors left null rather than a guessed value. The consistency check
(validation.check_height_floor_consistency) runs against whatever OSM
did report, to catch tag disagreements like a height that doesn't match
a levels count.
"""
import logging
import math
import time

from . import overpass_client

logger = logging.getLogger("landsphere.ingestion.osm")

# Endpoint list, timeouts, User-Agent, health tracking, retry/backoff and the on-disk tile cache all
# live in overpass_client.py (the single place every Overpass call goes through). These names are
# re-exported because other modules (infra/service.py, detection_router.py) import them from here.
OVERPASS_ENDPOINTS = overpass_client.OVERPASS_ENDPOINTS
REQUEST_HEADERS = overpass_client.REQUEST_HEADERS
REQUEST_TIMEOUT_S = overpass_client.READ_TIMEOUT_S
# Server-side budget written INTO the Overpass query (slightly under our HTTP read timeout so the
# server gives up and says so, instead of us cutting the connection mid-answer).
QL_TIMEOUT_S = max(10, REQUEST_TIMEOUT_S - 5)

# FIXED-GRID TILING. Every request is snapped to a global grid of GRID_DEG x GRID_DEG cells
# (0.01 deg ~ 1.1 km, ~1.2 sq km). Because the cell boundaries never move, a cell downloaded once is
# reused by every later view that touches it (panning back, "Map this view again", another officer),
# and a retry after a partial failure only fetches the cells that are still missing. Small cells also
# mean small, fast queries that the free servers rarely reject -- unlike one huge query per view.
GRID_DEG = 0.01
# Pause between successive LIVE tile requests (cache hits skip it) -- fair use of free public servers.
TILE_REQUEST_DELAY_S = 1.0
# Kept for older imports; the grid above supersedes the old "split if bigger than X sq km" rule.
MAX_TILE_AREA_SQKM = 25.0

# Real-world default per-storey height (m) used ONLY to estimate
# num_floors from a height tag when OSM has no building:levels tag at
# all (never the reverse -- if levels exists, it's used as-is; this is
# just a documented, disclosed estimate, not fabricated data).
DEFAULT_FLOOR_HEIGHT_M = 3.2


def _bbox_area_sqkm(south: float, west: float, north: float, east: float) -> float:
    lat_km = (north - south) * 111.0
    lon_km = (east - west) * 111.0 * math.cos(math.radians((north + south) / 2.0))
    return abs(lat_km * lon_km)


def _grid_tiles(south: float, west: float, north: float, east: float):
    """Fixed-grid cells covering the bbox -> [(s, w, n, e), ...]. Coordinates are computed from
    integer cell indexes (no float drift) so the same cell always yields the identical query text,
    which is what makes the on-disk cache hit across different views."""
    eps = 1e-9
    i0, i1 = math.floor(south / GRID_DEG), math.floor((north - eps) / GRID_DEG)
    j0, j1 = math.floor(west / GRID_DEG), math.floor((east - eps) / GRID_DEG)
    tiles = []
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            tiles.append((round(i * GRID_DEG, 6), round(j * GRID_DEG, 6),
                          round((i + 1) * GRID_DEG, 6), round((j + 1) * GRID_DEG, 6)))
    return tiles


def _split_bbox_into_tiles(south: float, west: float, north: float, east: float, max_area_sqkm: float = MAX_TILE_AREA_SQKM):
    """Backward-compatible name; now returns the fixed-grid cells (max_area_sqkm is ignored)."""
    return _grid_tiles(south, west, north, east)


def _overpass_query_for_bbox(south: float, west: float, north: float, east: float) -> str:
    """Overpass QL for building ways/relations in a bbox, with tags (out body) and node geometry
    (out geom) so we get real polygon coordinates back, not just centroids."""
    return f"""
    [out:json][timeout:{QL_TIMEOUT_S}];
    (
      way["building"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    );
    out body geom;
    """.strip()


def _query_one_endpoint(endpoint: str, query: str):
    """Single Overpass HTTP call -> (json, None) | (None, error). Kept for older callers."""
    return overpass_client.query_one_endpoint(endpoint, query)


def _race_overpass_query_ex(query: str, use_cache: bool = True):
    """Cache -> health-ranked hedged live query with retry/backoff -> stale cache.
    Returns (data, info) or (None, short_user_message); info = {"source", "age_days"}."""
    return overpass_client.run_query(query, use_cache=use_cache)


def _race_overpass_query(query: str):
    """Older 2-tuple shape (data, error) used by infra/service.py."""
    data, info = _race_overpass_query_ex(query)
    return (data, None) if data is not None else (None, info)


def _bbox_intersects(geometry, south, west, north, east) -> bool:
    lats = [p[0] for p in geometry]
    lons = [p[1] for p in geometry]
    return not (max(lats) < south or min(lats) > north or max(lons) < west or min(lons) > east)


def _parse_buildings(data):
    out = []
    for element in data.get("elements", []):
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 3:
            continue  # not enough points to form a polygon -- skip rather than fabricate one
        out.append({
            "osm_id": str(element["id"]),
            "osm_type": element["type"],
            "tags": element.get("tags", {}),
            "geometry": [(pt["lat"], pt["lon"]) for pt in geometry],
        })
    return out


def _parse_roads(data):
    out = []
    for element in data.get("elements", []):
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 2:
            continue  # a line needs at least 2 points -- skip anything degenerate rather than fabricate one
        out.append({
            "osm_id": str(element["id"]),
            "tags": element.get("tags", {}),
            "highway_type": element.get("tags", {}).get("highway"),
            "geometry": [(pt["lat"], pt["lon"]) for pt in geometry],
        })
    return out


def _fetch_tiles(south, west, north, east, build_query, parse, label):
    """Shared tile loop for buildings and roads.
    Returns (items_by_id | None, warning | None). None only if EVERY tile failed."""
    tiles = _grid_tiles(south, west, north, east)
    items = {}
    failed = stale = 0
    last_error = None
    max_age = 0.0
    for idx, (s, w, n, e) in enumerate(tiles):
        data, info = _race_overpass_query_ex(build_query(s, w, n, e))
        if data is None:
            failed += 1
            last_error = info
            logger.warning("%s tile %d/%d (%s,%s,%s,%s) failed: %s", label, idx + 1, len(tiles), s, w, n, e, info)
        else:
            if info["source"] == "stale-cache":
                stale += 1
                max_age = max(max_age, info["age_days"] or 0.0)
            for it in parse(data):
                if _bbox_intersects(it["geometry"], south, west, north, east):
                    items[it["osm_id"]] = it            # de-dupe items straddling tile edges
        # only pause after a request that really hit the network
        if data is not None and info["source"] == "live" and idx < len(tiles) - 1:
            time.sleep(TILE_REQUEST_DELAY_S)

    if failed == len(tiles):
        return None, last_error or overpass_client.FRIENDLY_FAIL
    notes = []
    if failed:
        notes.append(f"{failed} of {len(tiles)} map areas could not be downloaded right now and were skipped - "
                     f"press the button again to fetch just the missing ones (the rest are saved).")
    if stale:
        notes.append(f"{stale} area(s) came from saved data up to {max_age:.0f} day(s) old because the live servers were unreachable.")
    return items, (" ".join(notes) or None)


def _fetch_one_tile(south: float, west: float, north: float, east: float):
    """One grid tile of buildings -> (buildings, None) | (None, error). Kept for older callers."""
    data, info = _race_overpass_query_ex(_overpass_query_for_bbox(south, west, north, east))
    if data is None:
        return None, info
    return _parse_buildings(data), None


def fetch_buildings_in_bbox(south: float, west: float, north: float, east: float):
    """
    Every OSM building in a bbox of ANY size, fetched tile-by-tile over the fixed grid (cache-first,
    health-ranked failover, retries, stale-if-error -- see overpass_client.py).

    Returns (buildings, warning_or_None) on success; warning is set (buildings still real and
    non-empty) if SOME tiles failed or came from older saved data, so callers can say so instead of
    pretending the result is complete.
    Returns (None, error_message) only if EVERY tile failed. The message is short and user-safe.
    """
    items, warning = _fetch_tiles(south, west, north, east, _overpass_query_for_bbox, _parse_buildings, "Building")
    if items is None:
        return None, warning
    return list(items.values()), warning


def parse_building_attributes(tags: dict):
    """
    Extracts real height/floor-count/address from OSM tags -- never
    invents a value for a tag that isn't present.

    Returns {height_m, num_floors, name, address, building_type} with any
    field set to None if OSM didn't tag it.
    """
    height_m = None
    if "height" in tags:
        try:
            height_m = float(str(tags["height"]).replace("m", "").strip())
        except ValueError:
            height_m = None

    num_floors = None
    for levels_key in ("building:levels", "levels"):
        if levels_key in tags:
            try:
                num_floors = int(float(tags[levels_key]))
                break
            except ValueError:
                continue

    # If OSM gave a height but no levels, ESTIMATE floors from the
    # disclosed default -- clearly a different confidence tier than a
    # real building:levels tag, so the caller should track how this
    # number was derived if it matters downstream.
    floors_estimated = False
    if num_floors is None and height_m is not None:
        num_floors = max(1, round(height_m / DEFAULT_FLOOR_HEIGHT_M))
        floors_estimated = True

    housenumber = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    postcode = tags.get("addr:postcode", "")
    address_parts = [p for p in [f"{housenumber} {street}".strip(), postcode] if p]
    address = ", ".join(address_parts) if address_parts else None

    return {
        "height_m": height_m,
        "num_floors": num_floors,
        "floors_estimated": floors_estimated,
        "name": tags.get("name"),
        "address": address,
        "building_type": tags.get("building") if tags.get("building") not in (None, "yes") else "unspecified",
    }


def latlon_polygon_to_local_meters(latlon_points, origin_lat, origin_lon):
    """Converts an OSM way's real lat/lon polygon into the same local-metre
    coordinate convention used throughout the rest of this project (see
    ai/registration/alignment.py::latlon_alt_to_local_meters -- duplicated
    here rather than imported, to keep this ingestion module free of any
    dependency on the ai/ package, since it does no ML)."""
    import math
    lat_rad = math.radians(origin_lat)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(lat_rad)
    return [
        [round((lon - origin_lon) * m_per_deg_lon, 3), round((lat - origin_lat) * m_per_deg_lat, 3)]
        for lat, lon in latlon_points
    ]


# ---------------------------------------------------------------------------
# Roads -- for the road-network overlay in the city-scale 3D viewer
# (BulkAreaViewer3D.jsx), which previously drew a plain ground plane with
# an explicit note that no real street data was being shown. This closes
# that gap with real OSM way["highway"] centerlines for whatever bbox was
# actually selected -- generic to any place in the world, not hardcoded to
# any particular city, state, or country.
# ---------------------------------------------------------------------------

def _overpass_query_for_roads_bbox(south: float, west: float, north: float, east: float) -> str:
    """Overpass QL for every road/street way within a bbox. Roads are open polylines, so only 'way'
    is needed (a few roads are route relations, but plain ways are enough for the overlay)."""
    return f"""
    [out:json][timeout:{QL_TIMEOUT_S}];
    (
      way["highway"]({south},{west},{north},{east});
    );
    out body geom;
    """.strip()


def _fetch_roads_one_tile(south: float, west: float, north: float, east: float):
    data, info = _race_overpass_query_ex(_overpass_query_for_roads_bbox(south, west, north, east))
    if data is None:
        return None, info
    return _parse_roads(data), None


def fetch_roads_in_bbox(south: float, west: float, north: float, east: float):
    """Road centerlines for a bbox of any size, same fixed-grid / cache / failover strategy as
    fetch_buildings_in_bbox. Returns (roads, warning_or_None) or (None, error_message)."""
    items, warning = _fetch_tiles(south, west, north, east, _overpass_query_for_roads_bbox, _parse_roads, "Road")
    if items is None:
        return None, warning
    return list(items.values()), warning


def latlon_polyline_to_local_meters(latlon_points, origin_lat, origin_lon):
    """Same conversion as latlon_polygon_to_local_meters, named separately
    for callers dealing with an open road polyline rather than a closed
    building polygon -- the math is identical, this just documents intent
    at the call site."""
    return latlon_polygon_to_local_meters(latlon_points, origin_lat, origin_lon)