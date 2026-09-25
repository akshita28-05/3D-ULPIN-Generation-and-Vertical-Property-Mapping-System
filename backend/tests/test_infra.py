"""Underground + air-rights auto-discovery from open data (no sensor, no manual entry).
Synthetic OSM elements only -- proves the rules and the plumbing, not that Overpass is up:

    cd backend && pytest -q tests/test_infra.py
"""
import json
import math
import os
import tempfile

_DB = os.path.join(tempfile.mkdtemp(), "infra.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["INFRA_OFFLINE"] = "true"
os.environ["INFRA_CACHE_DIR"] = os.path.join(tempfile.mkdtemp(), "cache")
os.environ["INFRA_CELL_DELAY_S"] = "0"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app import models, auth
from app.infra import osm_infra, service

ORIGIN = (24.8474, 77.6939)
M_LAT = 111320.0
M_LON = M_LAT * math.cos(math.radians(ORIGIN[0]))


def ll(x, y):
    return {"lat": ORIGIN[0] + y / M_LAT, "lon": ORIGIN[1] + x / M_LON}


def way(i, pts, **tags):
    return {"type": "way", "id": i, "tags": tags, "geometry": [ll(x, y) for x, y in pts]}


def box(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


ELEMENTS = [
    way(1, [(0, 100), (400, 100)], railway="subway", tunnel="yes", name="Line 3"),
    way(2, [(0, 130), (400, 130)], railway="subway", tunnel="yes", depth="18"),
    way(3, box(20, 100, 60, 140), building="apartments", **{"building:levels:underground": "2"}),
    way(4, [(0, 300), (500, 300)], highway="primary", bridge="yes", lanes="4", name="Flyover"),
    way(5, [(0, 400), (20, 400)], highway="residential", bridge="yes"),
    way(6, [(0, 200), (800, 200)], power="line", voltage="220000"),
    way(7, [(0, 250), (300, 250)], power="cable"),
    way(8, [(0, 500), (60, 500)], highway="footway", tunnel="yes"),
    way(9, [(0, 600), (300, 600)], highway="primary"),
    way(10, [(0, 700), (300, 700)], railway="subway", bridge="yes", layer="1"),
    way(11, box(100, 100, 140, 140), amenity="parking", parking="underground"),
]


def _by_osm(features):
    return {f["osm_id"]: f for f in features}


def test_classification_rules_and_disclosure():
    feats = _by_osm(osm_infra.classify_elements(ELEMENTS, ORIGIN))
    assert set(feats) == {f"way/{i}" for i in (1, 2, 3, 4, 6, 7, 8, 10, 11)}

    m = feats["way/1"]
    assert (m["kind"], m["subtype"]) == ("underground", "metro_tunnel")
    assert m["z_source"] == "assumed_default" and m["confidence"] <= 0.45 and m["z_min_m"] < m["z_max_m"]
    assert any("typical" in n.lower() for n in m["notes"])
    assert feats["way/2"]["z_source"] == "osm_tag" and feats["way/2"]["z_max_m"] == 18.0

    b = feats["way/3"]
    assert b["subtype"] == "basement" and b["z_source"] == "osm_tag" and b["z_max_m"] == pytest.approx(6.4)
    assert b["geometry"]["type"] == "Polygon"
    assert feats["way/11"]["subtype"] == "underground_parking"
    assert feats["way/8"]["subtype"] == "pedestrian_subway"
    assert feats["way/7"]["subtype"] == "power_cable"

    f = feats["way/4"]
    assert (f["kind"], f["subtype"]) == ("air", "flyover") and f["z_min_m"] > 0 and f["deck_top_m"] > f["z_min_m"]
    assert feats["way/10"]["subtype"] == "metro"
    p = feats["way/6"]
    assert p["subtype"] == "power_line" and p["width_m"] == 35.0 and p["z_source"] == "osm_tag"

    lon, lat = m["geometry"]["coordinates"][0]
    assert abs(lat - ORIGIN[0]) < 0.01 and abs(lon - ORIGIN[1]) < 0.01


@pytest.fixture(scope="module")
def client():
    db = SessionLocal()
    db.add(models.User(name="Surveyor", email="s@t.demo", hashed_password=auth.hash_password("Surveyor@123"), role="surveyor"))
    db.commit()
    db.close()
    return TestClient(app)


def _reset_infra():
    """Other test modules share the process (and DB): start from a clean scan state."""
    db = SessionLocal()
    for m in (models.InfraFeature, models.InfraScanCell):
        db.query(m).delete()
    db.commit()
    db.close()


BBOX = dict(south=24.8420, west=77.6850, north=24.8540, east=77.6990)


def test_scan_persists_serves_layers_and_never_refetches(client, monkeypatch):
    _reset_infra()
    calls = []

    def fake_fetch(key, bounds):
        calls.append(key)
        return ELEMENTS, None, False

    monkeypatch.setattr(service, "fetch_cell_elements", fake_fetch)
    r = client.post("/api/infra/scan", json=BBOX)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok" and r.json()["scanned"] == 1 and r.json()["added"] == 9

    feats = client.get("/api/map/infrastructure", params=BBOX).json()["features"]
    kinds = {f["properties"]["kind"] for f in feats}
    assert kinds == {"underground", "air"} and len(feats) == 9
    air = next(f for f in feats if f["properties"]["subtype"] == "flyover")["properties"]
    assert air["top"] > air["base"] > 0 and air["evidence"] == "PREDICTED"
    ug = next(f for f in feats if f["properties"]["subtype"] == "metro_tunnel")["properties"]
    assert ug["depth_max"] > ug["depth_min"] > 0 and ug["display_width"] >= 3.0

    again = client.post("/api/infra/scan", json=BBOX).json()
    assert again["scanned"] == 0 and again["cached"] == 1 and calls == ["1242:3884"]

    stats = client.get("/api/map/stats").json()
    assert stats["infra_underground"] == 6 and stats["infra_air"] == 3


def test_unreachable_open_data_is_reported_not_faked(client, monkeypatch):
    _reset_infra()
    monkeypatch.setattr(service, "fetch_cell_elements", lambda key, bounds: (None, "Overpass unreachable", False))
    far = dict(south=19.06, west=72.86, north=19.07, east=72.87)
    r = client.post("/api/infra/scan", json=far).json()
    assert r["status"] == "unavailable" and "Overpass" in r["message"]
    assert client.get("/api/map/infrastructure", params=far).json()["features"] == []


def test_big_view_asks_to_zoom_in(client):
    r = client.post("/api/infra/scan", json=dict(south=20, west=70, north=22, east=72)).json()
    assert r["status"] == "zoom_in"


def test_link_creates_parcel_rows_for_the_3d_viewer(client, monkeypatch):
    fp = [[0, 90], [140, 90], [140, 310], [0, 310]]
    db = SessionLocal()
    parcel = models.Parcel(
        ulpin_2d="TESTINFRA0001", centroid_lat=ORIGIN[0] + 200 / M_LAT, centroid_lon=ORIGIN[1] + 70 / M_LON,
        footprint_geojson=json.dumps(fp), area_sqm=140 * 220,
    )
    db.add(parcel)
    db.flush()
    db.add(models.Building(parcel_id=parcel.id, building_code="B01", name="Tower", num_floors=8, height_m=24.0,
                           footprint_geojson=json.dumps([[20, 100], [60, 100], [60, 140], [20, 140]])))
    db.commit()
    pid = parcel.id
    db.close()
    _reset_infra()
    monkeypatch.setattr(service, "fetch_cell_elements", lambda key, bounds: (ELEMENTS, None, False))

    hdr = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "s@t.demo", "password": "Surveyor@123"}).json()["access_token"]}
    r = client.post("/api/infra/link", headers=hdr, json=BBOX)
    assert r.status_code == 200, r.text
    assert r.json()["linked"]["parcels"] >= 1

    ug = [a for a in client.get("/api/underground-assets").json() if a["parcel_id"] == pid]
    air = [a for a in client.get("/api/air-rights").json() if a["parcel_id"] == pid]
    assert ug and air
    assert all(a["depth_max_m"] > a["depth_min_m"] >= 0 for a in ug)
    pts = json.loads(ug[0]["geometry_geojson"])
    assert len(pts) >= 3 and all(len(p) == 2 for p in pts)
    for a in ug + air:
        for x, y in json.loads(a["geometry_geojson"]):
            assert -1 <= x <= 141 and 89 <= y <= 311, (a["id"], x, y)
    assert {"metro_tunnel", "basement"} <= {a["asset_type"] for a in ug}
    assert any(a["corridor_type"] == "flyover" for a in air)
    assert all(a["source"] == "osm_auto" and a["detection_confidence"] for a in air)
    assert all(json.loads(a["detection_notes"]) for a in air)

    n1 = len(ug)
    client.post("/api/infra/link", headers=hdr, json=BBOX)
    ug2 = [a for a in client.get("/api/underground-assets").json() if a["parcel_id"] == pid]
    assert len(ug2) == n1


def test_one_click_auto_map_also_discovers_underground_and_air_rights(client, monkeypatch):
    """The whole point: press 'Auto-map this view' and the vertical layers appear by themselves."""
    import time
    lat0, lon0 = 12.9700, 77.5900
    m_lon = M_LAT * math.cos(math.radians(lat0))

    def p(x, y):
        return {"lat": lat0 + y / M_LAT, "lon": lon0 + x / m_lon}

    def w(i, pts, **tags):
        return {"type": "way", "id": i, "tags": tags, "geometry": [p(x, y) for x, y in pts]}

    elements = [
        w(501, [(-50, 60), (300, 60)], railway="subway", tunnel="yes"),
        w(502, [(-50, 130), (300, 130)], highway="primary", bridge="yes", lanes="4"),
    ]
    _reset_infra()
    monkeypatch.setattr(service, "fetch_cell_elements", lambda key, bounds: (elements, None, False))

    db = SessionLocal()
    for i in range(4):
        for j in range(4):
            x, y = j * 60, i * 45
            ring = [[lat0 + (y) / M_LAT, lon0 + x / m_lon], [lat0 + y / M_LAT, lon0 + (x + 40) / m_lon],
                    [lat0 + (y + 30) / M_LAT, lon0 + (x + 40) / m_lon], [lat0 + (y + 30) / M_LAT, lon0 + x / m_lon],
                    [lat0 + y / M_LAT, lon0 + x / m_lon]]
            db.add(models.ExternalBuildingFootprint(
                confidence=0.9, height_m=None, centroid_lat=sum(q[0] for q in ring[:-1]) / 4,
                centroid_lon=sum(q[1] for q in ring[:-1]) / 4, footprint_latlon_geojson=json.dumps(ring)))
    db.commit()
    db.close()

    hdr = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "s@t.demo", "password": "Surveyor@123"}).json()["access_token"]}
    r = client.post("/api/auto/run", headers=hdr, json=dict(south=lat0 - 0.001, west=lon0 - 0.001, north=lat0 + 0.003, east=lon0 + 0.004))
    assert r.status_code == 200, r.text
    end = time.time() + 60
    while time.time() < end:
        job = client.get(f"/api/bulk-import/jobs/{r.json()['job_id']}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "done", job
    infra = job["summary"]["infra"]
    assert infra["underground"] == 1 and infra["air"] == 1
    assert infra["linked_underground"] >= 1 and infra["linked_air"] >= 1
    assert not job["error_message"]


def test_parcel_3d_feed_shows_nearby_structures_in_the_parcels_own_frame(client, monkeypatch):
    """The per-parcel 3D viewer must show the same real features the map shows, including ones that
    run NEXT TO the parcel (not only ones that cross it), in the parcel's local-metre frame."""
    fp = [[0, 90], [30, 90], [30, 140], [0, 140]]
    db = SessionLocal()
    parcel = models.Parcel(
        ulpin_2d="TESTINFRA0002", centroid_lat=ORIGIN[0] + 115 / M_LAT, centroid_lon=ORIGIN[1] + 15 / M_LON,
        footprint_geojson=json.dumps(fp), area_sqm=30 * 50,
    )
    db.add(parcel)
    db.commit()
    pid = parcel.id
    db.close()
    _reset_infra()
    monkeypatch.setattr(service, "fetch_cell_elements", lambda key, bounds: (ELEMENTS, None, False))

    r = client.get(f"/api/infra/parcel/{pid}", params={"radius_m": 250})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] and body["scan"]["status"] == "ok"
    subtypes = {f["subtype"] for f in body["features"]}
    assert {"metro_tunnel", "basement"} <= subtypes
    assert "flyover" in subtypes or "power_line" in subtypes
    metro = next(f for f in body["features"] if f["subtype"] == "metro_tunnel")
    assert metro["z_source"] in ("osm_tag", "assumed_default") and metro["z_max_m"] > metro["z_min_m"] > 0
    assert metro["polygons"] and metro["centerlines"] and metro["source"] == "OpenStreetMap"
    for f in body["features"]:
        for ring in f["polygons"]:
            for x, y in ring:
                assert -251 <= x <= 281 and -161 <= y <= 391
    far = next((f for f in body["features"] if f["subtype"] in ("flyover", "power_line")), None)
    assert far and far["on_parcel"] is False and far["distance_m"] > 0
    assert body["counts"]["underground"] >= 2 and body["counts"]["air"] >= 1

    _reset_infra()
    monkeypatch.setattr(service, "fetch_cell_elements", lambda key, bounds: ([], None, False))
    empty = client.get(f"/api/infra/parcel/{pid}").json()
    assert empty["features"] == [] and empty["counts"]["underground"] == 0

    assert client.get("/api/infra/parcel/does-not-exist").status_code == 404
