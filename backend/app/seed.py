"""
Seed script.

By default (`python -m app.seed`), this ONLY creates the 3 demo login
accounts (surveyor/verifier/admin) -- you need at least one account to
log in. It does NOT create any demo parcel, building, floors, units,
underground assets, conflicts, or grievances -- all of that is expected
to be created dynamically through the app (Create Parcel/Building page,
the AI pipeline, citizen grievance submissions, etc.), per the
"everything must be dynamic, not seeded" requirement.

If you specifically want the illustrative demo property dataset (useful
for a first look at the UI before you've created your own data), run:
    python -m app.seed --with-demo-data

If you want a larger, multi-state dataset for demo/testing purposes (many
parcels across different states, varied floor counts and verification
statuses) -- also purely additive/optional, see `app/seed_demo_states.py`
for details -- run:
    python -m app.seed --with-multi-state-demo

Usage:
    python -m app.seed                                        # users only (recommended)
    python -m app.seed --with-demo-data                        # users + 1 illustrative demo parcel/building/etc.
    python -m app.seed --with-multi-state-demo                 # users + ~15 parcels across many states
    python -m app.seed --with-demo-data --with-multi-state-demo  # users + both
"""
import sys
import json
import hashlib
from datetime import datetime, timedelta

from .database import SessionLocal, Base, engine
from . import models, auth, ulpin as ulpin_service

Base.metadata.create_all(bind=engine)
db = SessionLocal()

WITH_DEMO_DATA = "--with-demo-data" in sys.argv
WITH_MULTI_STATE_DEMO = "--with-multi-state-demo" in sys.argv

print("Seeding accounts...")

demo_users = [
    {"name": "Aditi Sharma", "email": "surveyor@sih.demo", "password": "Surveyor@123", "role": "surveyor"},
    {"name": "Rohan Verma", "email": "verifier@sih.demo", "password": "Verifier@123", "role": "verifier"},
    {"name": "Admin Officer", "email": "admin@sih.demo", "password": "Admin@123", "role": "admin"},
]
users = {}
for u in demo_users:
    existing = db.query(models.User).filter(models.User.email == u["email"]).first()
    if existing:
        users[u["role"]] = existing
        continue
    user = models.User(name=u["name"], email=u["email"], hashed_password=auth.hash_password(u["password"]), role=u["role"])
    db.add(user)
    db.flush()
    users[u["role"]] = user
print(f"  Users: {[u['email'] for u in demo_users]} (passwords in comment above)")

if WITH_DEMO_DATA:
    print("Seeding illustrative demo property data...")
    ulpin_2d = ulpin_service.generate_2d_ulpin(db, "20", "01", "003", "045", "0231")
    parcel = db.query(models.Parcel).filter(models.Parcel.ulpin_2d == ulpin_2d).first()
    if not parcel:
        footprint = [[0, 0], [30, 0], [30, 22.5], [0, 22.5], [0, 0]]
        parcel = models.Parcel(
            ulpin_2d=ulpin_2d, state_code="20", district_code="01", subdistrict_code="003",
            village_code="045", plot_code="0231",
            address="Sample Plot, Bistupur, Jamshedpur, Jharkhand (representative demo address)",
            centroid_lat=22.7925, centroid_lon=86.1844,
            footprint_geojson=json.dumps(footprint), area_sqm=675.0,
        )
        db.add(parcel)
        db.flush()
    print(f"  Parcel: {ulpin_2d}")

    building = db.query(models.Building).filter(models.Building.parcel_id == parcel.id).first()
    if not building:
        building = models.Building(
            parcel_id=parcel.id, building_code="B01", name="Demo Residential Tower",
            building_type="residential", num_floors=5, height_m=15.0,
            footprint_geojson=json.dumps([[0, 0], [30, 0], [30, 22.5], [0, 22.5], [0, 0]]),
            ai_confidence=0.94,
        )
        db.add(building)
        db.flush()
    print(f"  Building: {building.building_code}")

    FLOOR_HEIGHT = 3.0
    existing_floors = db.query(models.Floor).filter(models.Floor.building_id == building.id).count()
    if existing_floors == 0:
        unit_types = ["residential_unit", "residential_unit", "commercial_unit", "parking_unit"]
        for i in range(1, 6):
            floor = models.Floor(
                building_id=building.id, floor_code=f"F{i:02d}", floor_number=i,
                z_min=(i - 1) * FLOOR_HEIGHT, z_max=i * FLOOR_HEIGHT, ai_confidence=0.91,
            )
            db.add(floor)
            db.flush()

            cell_w, cell_d = 15.0, 11.25
            idx = 1
            for r in range(2):
                for c in range(2):
                    x0, y0 = c * cell_w, r * cell_d
                    x1, y1 = x0 + cell_w * 0.9, y0 + cell_d * 0.9
                    unit_code = f"U{idx:02d}"
                    unit_ulpin = ulpin_service.generate_3d_ulpin(ulpin_2d, building.building_code, floor.floor_code, unit_code)
                    unit = models.Unit(
                        floor_id=floor.id, unit_code=unit_code, ulpin_3d=unit_ulpin,
                        parcel_type=unit_types[idx - 1],
                        footprint_geojson=json.dumps([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]),
                        area_sqm=round((x1 - x0) * (y1 - y0), 2),
                        volume_cum=round((x1 - x0) * (y1 - y0) * FLOOR_HEIGHT, 2),
                        z_min=floor.z_min, z_max=floor.z_max,
                        owner_reference=f"OWNER_{(i-1)*4+idx:03d}",
                        ai_confidence=round(0.85 + 0.02 * idx, 2),
                        verification_status=models.VerificationStatus.approved if i <= 3 else models.VerificationStatus.pending_review,
                        verified_by=users["verifier"].id if i <= 3 else None,
                        verified_at=datetime.utcnow() if i <= 3 else None,
                    )
                    db.add(unit)
                    idx += 1
        db.flush()
        print("  Floors: 5, Units: 20 (15 pre-verified, 5 pending review)")

    if db.query(models.UndergroundAsset).filter(models.UndergroundAsset.parcel_id == parcel.id).count() == 0:
        assets = [
            {"asset_type": "water", "depth_min_m": 1.5, "depth_max_m": 3, "geom": [[5, 5], [25, 5], [25, 7], [5, 7], [5, 5]]},
            {"asset_type": "electricity", "depth_min_m": 1, "depth_max_m": 2, "geom": [[2, 2], [4, 2], [4, 20], [2, 20], [2, 2]]},
            {"asset_type": "sewer", "depth_min_m": 2.5, "depth_max_m": 4, "geom": [[10, 10], [20, 10], [20, 12], [10, 12], [10, 10]]},
        ]
        for a in assets:
            db.add(models.UndergroundAsset(
                parcel_id=parcel.id, asset_type=a["asset_type"],
                depth_min_m=a["depth_min_m"], depth_max_m=a["depth_max_m"],
                geometry_geojson=json.dumps(a["geom"]),
            ))
        db.flush()
        print("  Underground assets: water, electricity, sewer")

    if db.query(models.AirRightCorridor).filter(models.AirRightCorridor.parcel_id == parcel.id).count() == 0:
        db.add(models.AirRightCorridor(
            parcel_id=parcel.id, corridor_type="metro", height_min_m=18, height_max_m=24,
            geometry_geojson=json.dumps([[0, 8], [30, 8], [30, 11], [0, 11], [0, 8]]),
            conflict_status="potential",
        ))
        db.flush()
        print("  Air-rights corridor: metro (potential conflict flagged)")

    if db.query(models.ValidationResult).count() == 0:
        first_unit = db.query(models.Unit).first()
        db.add(models.ValidationResult(
            unit_id=first_unit.id if first_unit else None, building_id=building.id,
            check_type="underground_conflict", severity="HIGH",
            message="HIGH — Water pipeline intersects basement volume (demo flagged conflict)",
        ))
        db.add(models.ValidationResult(
            building_id=building.id, check_type="floor_overlap", severity="MEDIUM",
            message="MEDIUM — Minor vertical overlap detected between Floor 2 and Floor 3 boundary (demo flagged conflict)",
        ))
        db.flush()
        print("  Validation conflicts: 2 sample flags")

    if db.query(models.Grievance).count() == 0:
        sample_unit = db.query(models.Unit).first()
        db.add(models.Grievance(
            grievance_number="GRV-2026-00001", unit_id=sample_unit.id if sample_unit else None,
            category="boundary_discrepancy", description="Reported boundary does not match physical wall location (demo grievance).",
            status=models.GrievanceStatus.under_review,
        ))
        db.add(models.Grievance(
            grievance_number="GRV-2026-00002", unit_id=sample_unit.id if sample_unit else None,
            category="ownership_discrepancy", description="Owner reference appears incorrect for this unit (demo grievance).",
            status=models.GrievanceStatus.submitted,
        ))
        db.flush()
        print("  Grievances: 2 sample records")

    if db.query(models.ChangeDetection).count() == 0:
        db.add(models.ChangeDetection(
            parcel_id=parcel.id, date_before="2020-10-29", date_after="2020-12-28",
            description="Potential additional construction detected on rooftop level (demo sample)",
            confidence=0.87,
        ))
        db.flush()
        print("  Change detection: 1 sample record")

    if db.query(models.AuditLog).count() == 0:
        for i in range(1, 4):
            raw = f"{users['verifier'].id}|unit.approve|unit|demo-{i}|pending|approved|{datetime.utcnow().isoformat()}"
            db.add(models.AuditLog(
                user_id=users["verifier"].id, action="unit.approve", entity_type="unit", entity_id=f"demo-{i}",
                previous_value=json.dumps({"verification_status": "pending_review"}),
                new_value=json.dumps({"verification_status": "approved"}),
                record_hash=hashlib.sha256(raw.encode()).hexdigest(),
            ))
        db.flush()
        print("  Audit log: 3 sample entries")

db.commit()

if WITH_MULTI_STATE_DEMO:
    from . import seed_demo_states
    print("Seeding multi-state demo dataset (additive, idempotent)...")
    n = seed_demo_states.seed_multi_state_demo(db, verifier_user=users.get("verifier"))
    print(f"  {n} new state parcel(s) added out of {len(seed_demo_states.STATE_ENTRIES)} total entries defined.")

db.close()
print("\nSeed complete.")
print("Demo login credentials:")
for u in demo_users:
    print(f"  {u['role']:10s} -> {u['email']} / {u['password']}")
