"""Synthetic-data checks for app/ai/corridors (no DB, network, or GPU needed):
    cd backend && pytest -q tests/test_corridor_detection.py
Synthetic means: these prove the ALGORITHMS behave, not that they work on real
Indian drone/LiDAR data -- that still needs a real survey."""
import math
import numpy as np
import pytest

from app.ai.corridors import osm_detector, lidar_detector, parking_detector, conflicts, geom2d

ORIGIN = (22.7925, 86.1844)
M_LAT = 111320.0
M_LON = M_LAT * math.cos(math.radians(ORIGIN[0]))


def ll(x, y):
    return {"lat": ORIGIN[0] + y / M_LAT, "lon": ORIGIN[1] + x / M_LON}


def way(i, pts, **tags):
    return {"type": "way", "id": i, "tags": tags, "geometry": [ll(x, y) for x, y in pts]}


def test_osm_types_and_merge():
    els = [
        way(1, [(0, 90), (200, 90)], railway="subway", bridge="yes", layer="1"),
        way(2, [(0, 95), (200, 95)], railway="subway", bridge="yes", layer="1"),
        way(3, [(0, 10), (200, 10)], highway="primary", bridge="yes", lanes="4"),
        way(4, [(0, 50), (200, 50)], highway="primary"),
        way(5, [(0, 60), (200, 60)], railway="subway", tunnel="yes", layer="-1"),
        way(6, [(0, 70), (100, 70)], highway="footway", bridge="yes"),
    ]
    r = osm_detector.classify_elements(els, ORIGIN)
    types = sorted(c["corridor_type"] for c in r["corridors"])
    assert types == ["flyover", "metro"]
    metro = next(c for c in r["corridors"] if c["corridor_type"] == "metro")
    assert metro["height_source"] == "assumed_default" and metro["confidence"] <= 0.45
    assert len(metro["merged_osm_ids"]) == 2


def test_osm_height_tag_used():
    r = osm_detector.classify_elements([way(9, [(0, 0), (80, 0)], highway="motorway", bridge="yes", height="11", min_height="8")], ORIGIN)
    c = r["corridors"][0]
    assert c["height_source"] == "osm_tag" and c["height_min_m"] == 8.0 and c["deck_top_m"] == 11.0


def test_osm_parking():
    sq = [(0, 0), (40, 0), (40, 30), (0, 30), (0, 0)]
    els = [
        way(20, sq, amenity="parking", parking="multi-storey", **{"building:levels": "4"}, capacity="220"),
        way(21, [(100 + x, y) for x, y in sq], amenity="parking", parking="underground"),
        {"type": "node", "id": 30, "lat": ll(5, 5)["lat"], "lon": ll(5, 5)["lon"], "tags": {"amenity": "parking_space"}},
        {"type": "node", "id": 31, "lat": ll(8, 5)["lat"], "lon": ll(8, 5)["lon"], "tags": {"amenity": "parking_space"}},
    ]
    p = {a["osm_id"]: a for a in osm_detector.classify_elements(els, ORIGIN)["parking"]}
    assert p[20]["parking_kind"] == "multi_storey" and p[20]["levels"] == 4 and p[20]["mapped_stalls"] == 2
    assert p[21]["parking_kind"] == "underground" and p[21]["levels"] is None


def make_cloud(slab_returns, seed=0):
    rng = np.random.default_rng(seed)
    g = np.column_stack([rng.uniform(0, 200, 60000), rng.uniform(0, 160, 60000), rng.normal(0, 0.03, 60000)])
    bx = np.column_stack([rng.uniform(20, 50, 6000), rng.uniform(20, 42, 6000), rng.normal(15, 0.03, 6000)])
    t = rng.uniform(0, 200, 40000); y = 90 + 0.05 * t + rng.uniform(-4, 4, 40000)
    deck = np.column_stack([t, y, rng.normal(12, 0.03, 40000)])
    tr = np.column_stack([rng.normal(150, 4, 4000), rng.normal(30, 4, 4000), rng.uniform(0, 9, 4000)])
    parts = [g, bx, deck, tr]
    if slab_returns:
        parts.append(np.column_stack([t[:8000], y[:8000], rng.normal(9.5, 0.03, 8000)]))
    return np.vstack(parts)


BLDG = [[[20, 20], [50, 20], [50, 42], [20, 42], [20, 20]]]


def test_lidar_finds_deck_not_building_or_trees():
    s = lidar_detector.detect_elevated_structures(make_cloud(False), building_footprints=BLDG)
    assert len(s) == 1
    d = s[0]
    assert abs(d["deck_top_m"] - 12.0) < 0.3 and 6 < d["width_m"] < 11 and d["length_m"] > 180
    assert d["underside_source"] == "assumed_structural_depth"
    assert d["open_underneath"] > 0.8


def test_lidar_measures_underside_when_returns_beneath():
    s = lidar_detector.detect_elevated_structures(make_cloud(True), building_footprints=BLDG)
    assert len(s) == 1 and s[0]["underside_source"] == "lidar_measured_underside"
    assert abs(s[0]["deck_underside_m"] - 9.5) < 0.3


def test_fusion_replaces_assumed_heights():
    osm = osm_detector.classify_elements([way(1, [(0, 90), (200, 100)], railway="subway", bridge="yes", layer="1")], ORIGIN)["corridors"]
    lid = lidar_detector.detect_elevated_structures(make_cloud(False), building_footprints=BLDG)
    f = lidar_detector.fuse(osm, lid)
    assert len(f) == 1 and f[0]["source"] == "osm+lidar" and f[0]["height_source"].startswith("lidar_measured")
    assert abs(f[0]["deck_top_m"] - 12.0) < 0.3 and f[0]["confidence"] > 0.45


def test_lidar_only_structure_needs_review():
    f = lidar_detector.fuse([], lidar_detector.detect_elevated_structures(make_cloud(False), building_footprints=BLDG))
    assert f[0]["corridor_type"] == "unclassified_elevated" and f[0]["confidence"] <= 0.6


def test_conflicts():
    corr = [[0, 8], [30, 8], [30, 11], [0, 11], [0, 8]]
    b = [{"id": "B01", "footprint": [[0, 0], [30, 0], [30, 22.5], [0, 22.5], [0, 0]], "height_m": 15.0}]
    assert conflicts.assess(corr, 18, 24, b)[0] == "none"
    assert conflicts.assess(corr, 12, 20, b)[0] == "confirmed"
    far = [{"id": "B02", "footprint": [[0, 13], [30, 13], [30, 30], [0, 30], [0, 13]], "height_m": 15.0}]
    assert conflicts.assess(corr, 12, 20, far)[0] == "potential"


def test_clip_and_buffer():
    poly = geom2d.buffer_polyline([[0, 0], [100, 0]], 8)
    assert abs(geom2d.polygon_area(poly) - 800) < 1
    clipped = geom2d.clip_polygon_convex(poly, [[10, -10], [40, -10], [40, 10], [10, 10], [10, -10]])
    assert abs(geom2d.polygon_area(clipped) - 240) < 1


def test_painted_stalls():
    cv2 = pytest.importorskip("cv2")
    gsd = 0.05
    img = np.full((500, 700), 70, np.uint8)
    rng = np.random.default_rng(1)
    img = np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    for k in range(9):
        x = 40 + int(k * 2.5 / gsd)
        cv2.line(img, (x, 60), (x, 60 + int(5.0 / gsd)), 235, 3)
    r = parking_detector.detect_painted_stalls(img, gsd)
    assert r["n_stalls"] == 8
    assert abs(r["rows"][0]["stalls"][0]["width_m"] - 2.5) < 0.15


def test_stall_geometry_rule():
    car = [[0, 0], [2.5, 0], [2.5, 5.0], [0, 5.0], [0, 0]]
    flat = [[0, 0], [10, 0], [10, 8], [0, 8], [0, 0]]
    r = parking_detector.classify_stall_units([car, flat])
    assert r[0]["is_stall"] and not r[1]["is_stall"]
