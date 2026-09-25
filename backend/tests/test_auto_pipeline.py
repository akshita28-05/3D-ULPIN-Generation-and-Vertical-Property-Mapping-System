"""
End-to-end checks for the automated pipeline, the 3D-map feeds, the ownership
lifecycle and the CityJSON export. Runs against a throw-away SQLite file --
no Postgres, Redis or internet needed:

    cd backend && pytest -q tests
"""
import json
import math
import os
import tempfile
import time

_DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["DEM_HEIGHT_ESTIMATION_ENABLED"] = "false"
os.environ["INFRA_OFFLINE"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app import models, auth
from app.routers import bulk_import_router

CENTER = (24.8474, 77.6939)


@pytest.fixture(scope="module")
def client():
    db = SessionLocal()
    for name, email, pw, role in [
        ("Surveyor", "surveyor@t.demo", "Surveyor@123", "surveyor"),
        ("Verifier", "verifier@t.demo", "Verifier@123", "verifier"),
        ("Admin", "admin@t.demo", "Admin@123", "admin"),
    ]:
        db.add(models.User(name=name, email=email, hashed_password=auth.hash_password(pw), role=role))
    db.commit()
    db.close()
    return TestClient(app)


def _login(client, email, pw):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _wait_job(client, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/bulk-import/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _rect(lat, lon, w_m, d_m):
    dlat = d_m / 111320.0
    dlon = w_m / (111320.0 * math.cos(math.radians(lat)))
    return [[lat, lon], [lat, lon + dlon], [lat + dlat, lon + dlon], [lat + dlat, lon], [lat, lon]]


def test_region_footprints_auto_run_creates_units_without_any_manual_step(client):
    db = SessionLocal()
    n = 0
    for i in range(8):
        for j in range(8):
            ring = _rect(CENTER[0] + i * 0.0002, CENTER[1] + j * 0.0002, 12, 10)
            db.add(models.ExternalBuildingFootprint(
                confidence=0.9, height_m=None,
                centroid_lat=sum(p[0] for p in ring[:-1]) / 4, centroid_lon=sum(p[1] for p in ring[:-1]) / 4,
                footprint_latlon_geojson=json.dumps(ring),
            ))
            n += 1
    db.commit()
    db.close()

    fp = client.get("/api/map/footprints", params=dict(south=24.84, west=77.69, north=24.86, east=77.71)).json()
    assert len(fp["features"]) == n

    headers = _login(client, "surveyor@t.demo", "Surveyor@123")
    r = client.post("/api/auto/run", headers=headers, json=dict(south=24.84, west=77.69, north=24.86, east=77.71))
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "ms_footprints"
    job = _wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job

    s = job["summary"]
    assert s["buildings"] == n
    assert s["units"] > 0, "units + 3D ULPINs must be generated automatically"
    assert s["PREDICTED"] > 0 and s["OBSERVED"] == 0
    assert s["PREDICTED"] + s["NOT_DETERMINABLE"] == n

    feats = client.get("/api/map/buildings").json()["features"]
    assert len(feats) == n
    f = feats[0]["properties"]
    assert f["floor_state"] == "PREDICTED" and f["units"] > 0 and f["floor_method"]
    fp2 = client.get("/api/map/footprints", params=dict(south=24.84, west=77.69, north=24.86, east=77.71)).json()
    assert len(fp2["features"]) == 0

    lon, lat = feats[0]["geometry"]["coordinates"][0][0]
    assert abs(lat - CENTER[0]) < 0.01 and abs(lon - CENTER[1]) < 0.01

    stats = client.get("/api/map/stats").json()
    assert stats["buildings"] == n and stats["units"] == s["units"] and stats["floor_states"]["PREDICTED"] > 0
    assert client.get("/api/map/coverage").json()["has_data"] is True


def test_osm_path_observed_vs_predicted_from_neighbours(client, monkeypatch):
    lat0, lon0 = 19.0000, 72.8000
    buildings = []
    for k in range(12):
        buildings.append({"osm_id": f"9{k:03d}", "tags": {"building": "apartments", "building:levels": "5", "addr:street": "MG Road", "addr:housenumber": str(k)},
                          "geometry": [tuple(p) for p in _rect(lat0 + k * 0.0002, lon0, 20, 15)]})
    for k in range(4):
        buildings.append({"osm_id": f"8{k:03d}", "tags": {"building": "yes", "addr:street": "MG Road", "addr:housenumber": f"x{k}"},
                          "geometry": [tuple(p) for p in _rect(lat0 + k * 0.0002, lon0 + 0.0004, 20, 15)]})
    monkeypatch.setattr(bulk_import_router, "_call_fetch_buildings", lambda *a, **k: (buildings, None))
    monkeypatch.setattr(bulk_import_router, "REVERSE_GEOCODE_DELAY_S", 0)

    headers = _login(client, "surveyor@t.demo", "Surveyor@123")
    r = client.post("/api/auto/run", headers=headers, json=dict(south=lat0 - 0.001, west=lon0 - 0.001, north=lat0 + 0.004, east=lon0 + 0.002))
    assert r.json()["source"] == "osm"
    job = _wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["summary"]["OBSERVED"] == 12
    assert job["summary"]["PREDICTED"] == 4
    feats = client.get("/api/map/buildings", params=dict(south=lat0 - 0.01, west=lon0 - 0.01, north=lat0 + 0.01, east=lon0 + 0.01)).json()["features"]
    predicted = [f["properties"] for f in feats if f["properties"]["floor_state"] == "PREDICTED"]
    assert predicted and all(p["num_floors"] == 5 and "nearby" in p["floor_method"] for p in predicted)


def test_area_too_large_is_rejected(client):
    headers = _login(client, "surveyor@t.demo", "Surveyor@123")
    r = client.post("/api/auto/run", headers=headers, json=dict(south=20, west=70, north=22, east=72))
    assert r.status_code == 422


def test_ownership_lifecycle_lock_change_request_and_tamper_detection(client):
    verifier = _login(client, "verifier@t.demo", "Verifier@123")
    surveyor = _login(client, "surveyor@t.demo", "Surveyor@123")

    db = SessionLocal()
    building = db.query(models.Building).filter(models.Building.num_floors == 5).first()
    unit_id = db.query(models.Unit).join(models.Floor).filter(models.Floor.building_id == building.id).first().id
    building_id = building.id
    db.close()

    r = client.post("/api/lifecycle/change-requests", headers=surveyor, json=dict(unit_id=unit_id, proposed=dict(z_max=99)))
    assert r.status_code == 400

    r = client.post(f"/api/review/buildings/{building_id}/bulk-action", headers=verifier, json=dict(action="approve"))
    assert r.status_code == 200 and r.json()["units_updated"] > 0
    passport = client.get(f"/api/lifecycle/units/{unit_id}/passport").json()
    assert passport["integrity"]["locked"] and passport["integrity"]["has_baseline"] and not passport["integrity"]["tampered"]

    assert client.patch(f"/api/units/{unit_id}", headers=surveyor, json=dict(z_max=50)).status_code == 409
    assert client.post(f"/api/review/units/{unit_id}/action", headers=verifier, json=dict(action="approve", edited_z_max=50)).status_code == 409

    r = client.post("/api/lifecycle/change-requests", headers=surveyor, json=dict(unit_id=unit_id, proposed=dict(z_max=passport["z_max"] + 0.5), reason="mezzanine added"))
    assert r.status_code == 200, r.text
    req = r.json()
    token = req["owner_link_path"].rsplit("/", 1)[1]
    assert client.post(f"/api/lifecycle/change-requests/{req['id']}/apply", headers=verifier, json={}).status_code == 409
    assert client.get(f"/api/lifecycle/owner/{token}").json()["proposed"]["z_max"] == passport["z_max"] + 0.5
    assert client.get("/api/lifecycle/owner/not-a-real-token").status_code == 404
    assert client.post(f"/api/lifecycle/owner/{token}/decision", json=dict(approve=True)).json()["status"] == "owner_approved"
    assert client.post(f"/api/lifecycle/owner/{token}/decision", json=dict(approve=True)).status_code == 409
    assert client.post(f"/api/lifecycle/change-requests/{req['id']}/apply", headers=verifier, json=dict(note="ok")).json()["status"] == "applied"
    after = client.get(f"/api/lifecycle/units/{unit_id}/passport").json()
    assert after["z_max"] == passport["z_max"] + 0.5
    assert after["integrity"]["baseline_hash"] != passport["integrity"]["baseline_hash"] and not after["integrity"]["tampered"]

    db = SessionLocal()
    u = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    u.z_max = 123.0
    db.commit()
    db.close()
    assert client.get(f"/api/lifecycle/units/{unit_id}/passport").json()["integrity"]["tampered"] is True


def test_pdf_certificate_and_cityjson_export(client):
    db = SessionLocal()
    unit = db.query(models.Unit).first()
    parcel = db.query(models.Parcel).filter(models.Parcel.id == unit.floor.building.parcel_id).first()
    unit_id, parcel_id = unit.id, parcel.id
    db.close()

    pdf = client.get(f"/api/export/units/{unit_id}.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    doc = client.get(f"/api/interop/cityjson/parcels/{parcel_id}").json()
    assert doc["type"] == "CityJSON" and doc["version"] == "1.1"
    kinds = {o["type"] for o in doc["CityObjects"].values()}
    assert {"Building", "BuildingUnit"} <= kinds
    n = len(doc["vertices"])
    for obj in doc["CityObjects"].values():
        for geom in obj["geometry"]:
            for shell in geom["boundaries"]:
                for face in shell:
                    for ring in face:
                        assert all(0 <= i < n for i in ring)
    assert client.get("/api/interop/cityjson", params=dict(south=24.8, west=77.6, north=24.9, east=77.8)).status_code == 200
