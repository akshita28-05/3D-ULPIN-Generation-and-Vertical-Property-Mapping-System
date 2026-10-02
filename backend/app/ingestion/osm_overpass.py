
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
import time
import concurrent.futures

import requests

logger = logging.getLogger("landsphere.ingestion.osm")

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
# Per-endpoint request timeout. Endpoints are queried IN PARALLEL (see
# fetch_buildings_in_bbox) and the first success wins, so the worst case
# to find out "nothing worked" is one timeout window, not
# len(OVERPASS_ENDPOINTS) of them stacked serially.
REQUEST_TIMEOUT_S = 30

# A single Overpass request over a very large box (a whole city -- hundreds
# of sq km, potentially tens of thousands of building ways) routinely times
# out or gets rejected by the free public instances even when they're
# otherwise healthy. Rather than blocking large areas outright, any area
# above this size is automatically split into a grid of tiles this size or
# smaller (see fetch_buildings_any_size) and queried tile-by-tile -- so any
# area the person draws is importable, it just takes longer for a big one.
MAX_TILE_AREA_SQKM = 25.0
# Pause between successive tile requests in a multi-tile fetch, purely to
# stay well within the free services' fair-use expectations -- these are
# public instances shared by everyone, not a dedicated backend.
TILE_REQUEST_DELAY_S = 2.0

# Overpass's public instances actively reject requests that don't
# identify the calling application (their usage policy requires a
# descriptive User-Agent) -- python-requests' default User-Agent
# ("python-requests/x.x") reads as anonymous/bot-like traffic and gets
# turned away, which is what an HTTP 406 from overpass-api.de actually
# is here: not a network block, the server declining an unidentified
# client. Every request below sends this instead.
REQUEST_HEADERS = {
    "User-Agent": "Vasudha3D-VPMS/1.0 (bulk building import; contact: admin@vasudha3d.example)",
}

# Real-world default per-storey height (m) used ONLY to estimate
# num_floors from a height tag when OSM has no building:levels tag at
# all (never the reverse -- if levels exists, it's used as-is; this is
# just a documented, disclosed estimate, not fabricated data).
DEFAULT_FLOOR_HEIGHT_M = 3.2


def _bbox_area_sqkm(south: float, west: float, north: float, east: float) -> float:
    import math
    lat_km = (north - south) * 111.0
    lon_km = (east - west) * 111.0 * math.cos(math.radians((north + south) / 2.0))
    return abs(lat_km * lon_km)


def _split_bbox_into_tiles(south: float, west: float, north: float, east: float, max_area_sqkm: float):
    """Splits a bbox into an n x n grid of roughly equal sub-tiles, each
    at or under max_area_sqkm, so a query of any size can be served as a
    sequence of requests the free Overpass instances can actually handle.
    Returns [(south, west, north, east), ...] -- a single-element list
    (the original bbox unchanged) if it's already small enough."""
    import math
    total_area = _bbox_area_sqkm(south, west, north, east)
    if total_area <= max_area_sqkm:
        return [(south, west, north, east)]

    n = max(1, math.ceil(math.sqrt(total_area / max_area_sqkm)))
    lat_step = (north - south) / n
    lon_step = (east - west) / n
    tiles = []
    for i in range(n):
        for j in range(n):
            s = south + i * lat_step
            n_ = south + (i + 1) * lat_step
            w = west + j * lon_step
            e = west + (j + 1) * lon_step
            tiles.append((s, w, n_, e))
    return tiles


def _overpass_query_for_bbox(south: float, west: float, north: float, east: float) -> str:
    """Standard Overpass QL query for building ways/relations within a
    bounding box, with tags (out body) and node geometry (out geom) so we
    get real polygon coordinates back, not just centroids."""
    return f"""
    [out:json][timeout:{REQUEST_TIMEOUT_S}];
    (
      way["building"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    );
    out body geom;
    """.strip()


def _query_one_endpoint(endpoint: str, query: str):
    """Single Overpass HTTP call. Returns (parsed_json, None) on success
    or (None, human-readable error) on failure -- never raises, so the
    parallel racer below can just collect results."""
    try:
        resp = requests.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, f"{endpoint} timed out after {REQUEST_TIMEOUT_S}s"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        return None, f"{endpoint} returned HTTP {status}"
    except requests.exceptions.ConnectionError:
        return None, f"could not connect to {endpoint} (DNS/network/firewall)"
    except Exception as e:
        logger.exception(f"Overpass query failed via {endpoint}")
        return None, f"{endpoint} failed: {e}"


def _race_overpass_query(query: str):
    """
    Queries every endpoint in OVERPASS_ENDPOINTS IN PARALLEL for one
    already-built Overpass QL query and returns as soon as the first
    succeeds -- shared racing core for both building and road fetches, so
    the endpoint list, timeout, and error-message wording live in exactly
    one place instead of being duplicated per data type. Returns
    (parsed_json, None) or (None, error_message).
    """
    data = None
    errors = []
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(OVERPASS_ENDPOINTS))
    try:
        futures = {executor.submit(_query_one_endpoint, ep, query): ep for ep in OVERPASS_ENDPOINTS}
        for future in concurrent.futures.as_completed(futures):
            result, error = future.result()
            if result is not None:
                data = result
                break
            errors.append(error)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if data is None:
        combined = "; ".join(errors) if errors else "unknown error"
        return None, (
            f"All Overpass endpoints failed ({combined}). A 406/403 usually means a request got rejected "
            f"outbound before reaching Overpass at all; 429 means rate-limited (these are shared free "
            f"instances -- try again in a minute, or draw a smaller area to need fewer tile requests); a "
            f"timeout on every endpoint at once, repeated across attempts on a network you know is open, "
            f"points at a firewall/proxy blocking these hosts outbound rather than the servers themselves."
        )
    return data, None


def _fetch_one_tile(south: float, west: float, north: float, east: float):
    """
    Fetches buildings for one tile, racing all OVERPASS_ENDPOINTS in
    parallel via _race_overpass_query. Returns (buildings, None) or
    (None, error_message).
    """
    query = _overpass_query_for_bbox(south, west, north, east)
    data, error = _race_overpass_query(query)
    if data is None:
        return None, error

    buildings = []
    for element in data.get("elements", []):
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 3:
            continue  # not enough points to form a polygon -- skip rather than fabricate one
        buildings.append({
            "osm_id": str(element["id"]),
            "osm_type": element["type"],
            "tags": element.get("tags", {}),
            "geometry": [(pt["lat"], pt["lon"]) for pt in geometry],
        })
    return buildings, None


def fetch_buildings_in_bbox(south: float, west: float, north: float, east: float):
    """
    Fetches every OSM building in a bbox of ANY size: queried directly if
    it's already at or under MAX_TILE_AREA_SQKM, otherwise automatically
    split into a grid of tiles that size and fetched tile-by-tile (each
    tile racing all OVERPASS_ENDPOINTS in parallel), with results merged
    and de-duplicated by osm_id (a building can be returned by more than
    one tile if it straddles a tile boundary).

    Returns (buildings, warning_or_None) on success -- warning is set
    (but buildings is still a real, non-empty result) if SOME tiles
    failed while others succeeded, so the caller can show "N buildings
    found, but M areas within your selection could not be reached" rather
    than silently returning an incomplete result as if it were complete.

    Returns (None, error_message) only if EVERY tile failed -- nothing
    usable came back at all.
    """
    tiles = _split_bbox_into_tiles(south, west, north, east, MAX_TILE_AREA_SQKM)

    buildings_by_id = {}
    failed_tiles = 0
    last_error = None
    for idx, (s, w, n, e) in enumerate(tiles):
        tile_buildings, error = _fetch_one_tile(s, w, n, e)
        if tile_buildings is None:
            failed_tiles += 1
            last_error = error
            logger.warning(f"Tile {idx + 1}/{len(tiles)} ({s},{w},{n},{e}) failed: {error}")
        else:
            for b in tile_buildings:
                buildings_by_id[b["osm_id"]] = b  # de-dupe buildings that straddle tile edges
        if idx < len(tiles) - 1:
            time.sleep(TILE_REQUEST_DELAY_S)

    buildings = list(buildings_by_id.values())

    if failed_tiles == len(tiles):
        return None, last_error or "All area tiles failed."

    warning = None
    if failed_tiles > 0:
        warning = (
            f"{failed_tiles} of {len(tiles)} area tiles could not be reached and were skipped -- "
            f"results below are incomplete for your selected area. Last error: {last_error}"
        )
    return buildings, warning


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
    """Overpass QL for every road/street way within a bbox. Roads are
    open polylines (not closed polygons like buildings), so this only
    needs 'way', not 'relation' -- a small number of roads are mapped as
    route relations, but the vast majority of drivable/walkable geometry
    is plain ways, which is enough for a visual road-network overlay."""
    return f"""
    [out:json][timeout:{REQUEST_TIMEOUT_S}];
    (
      way["highway"]({south},{west},{north},{east});
    );
    out body geom;
    """.strip()


def _fetch_roads_one_tile(south: float, west: float, north: float, east: float):
    """Fetches road centerlines for one tile. Returns (roads, None) or
    (None, error_message) -- same shape as _fetch_one_tile's buildings."""
    query = _overpass_query_for_roads_bbox(south, west, north, east)
    data, error = _race_overpass_query(query)
    if data is None:
        return None, error

    roads = []
    for element in data.get("elements", []):
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 2:
            continue  # a line needs at least 2 points -- skip anything degenerate rather than fabricate one
        roads.append({
            "osm_id": str(element["id"]),
            "tags": element.get("tags", {}),
            "highway_type": element.get("tags", {}).get("highway"),
            "geometry": [(pt["lat"], pt["lon"]) for pt in geometry],
        })
    return roads, None


def fetch_roads_in_bbox(south: float, west: float, north: float, east: float):
    """
    Fetches every OSM road/street in a bbox of ANY size, same any-size
    tiling + parallel-endpoint-racing strategy as fetch_buildings_in_bbox
    (same MAX_TILE_AREA_SQKM, same de-duplication-by-id for roads that
    straddle a tile boundary). Returns (roads, warning_or_None) on success
    (warning set if some tiles failed but others succeeded), or
    (None, error_message) if every tile failed.
    """
    tiles = _split_bbox_into_tiles(south, west, north, east, MAX_TILE_AREA_SQKM)

    roads_by_id = {}
    failed_tiles = 0
    last_error = None
    for idx, (s, w, n, e) in enumerate(tiles):
        tile_roads, error = _fetch_roads_one_tile(s, w, n, e)
        if tile_roads is None:
            failed_tiles += 1
            last_error = error
            logger.warning(f"Road tile {idx + 1}/{len(tiles)} ({s},{w},{n},{e}) failed: {error}")
        else:
            for r in tile_roads:
                roads_by_id[r["osm_id"]] = r  # de-dupe roads that straddle tile edges
        if idx < len(tiles) - 1:
            time.sleep(TILE_REQUEST_DELAY_S)

    roads = list(roads_by_id.values())

    if failed_tiles == len(tiles):
        return None, last_error or "All area tiles failed."

    warning = None
    if failed_tiles > 0:
        warning = f"{failed_tiles} of {len(tiles)} area tiles could not be reached for road data -- overlay may be incomplete."
    return roads, warning


def latlon_polyline_to_local_meters(latlon_points, origin_lat, origin_lon):
    """Same conversion as latlon_polygon_to_local_meters, named separately
    for callers dealing with an open road polyline rather than a closed
    building polygon -- the math is identical, this just documents intent
    at the call site."""
    return latlon_polygon_to_local_meters(latlon_points, origin_lat, origin_lon)
