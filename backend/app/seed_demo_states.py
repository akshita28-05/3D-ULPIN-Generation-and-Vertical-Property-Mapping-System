"""
Multi-state demo/testing dataset — OPTIONAL, additive, separate from seed.py.

What this is:
  A larger set of illustrative parcels/buildings/floors/units spread across
  many different Indian states, for demoing or load-testing the review
  queue, search, GIS map, and 3D viewer with more than one property to look
  at. Every record is created through the exact same SQLAlchemy models
  (`Parcel`, `Building`, `Floor`, `Unit`, ...) and the exact same
  `app.ulpin` ID-generation service that the real dynamic Create
  Parcel/Building flow and the AI pipeline use — this script does not add,
  bypass, or alter any API endpoint, router, or validation rule. Nothing
  about how a surveyor creates a parcel, how the pipeline generates 3D
  ULPINs, or how a verifier reviews a unit is touched by this file.

What this is NOT:
  It is not run automatically and is not part of `python -m app.seed`'s
  default (no-args) behaviour, so the "nothing pre-seeded by default"
  guarantee described in the README is unchanged. It exists purely so a
  demo/test environment can be populated with realistic-looking, varied
  data across many states in one command, instead of manually creating
  20+ parcels by hand through the UI first.

Usage:
    python -m app.seed_demo_states
Or combined with the base seed:
    python -m app.seed --with-demo-data --with-multi-state-demo

Honesty note (same as the rest of the app): state/district/sub-district/
village/plot codes below are representative/sample values in the real
government digit format — not fetched from a live DoLR system. Building
footprint, floor count, and height are fixed per entry (not randomized)
so re-running this script is deterministic and idempotent (it skips a
state entry if its ULPIN already exists).
"""
import json
from datetime import datetime, timedelta

from . import models, ulpin as ulpin_service

FLOOR_HEIGHT = 3.0

STATE_ENTRIES = [
    dict(label="Maharashtra", state="27", district="01", subdistrict="002", village="118", plot="0044",
         address="Plot 44, Andheri West, Mumbai, Maharashtra (representative demo address)",
         lat=19.1197, lon=72.8468, width=24, depth=18, building_type="residential",
         num_floors=8, name="Sea Breeze Residency"),
    dict(label="Delhi (NCT)", state="07", district="03", subdistrict="005", village="027", plot="0119",
         address="Plot 119, Dwarka Sector 12, New Delhi (representative demo address)",
         lat=28.5921, lon=77.0460, width=20, depth=15, building_type="mixed",
         num_floors=5, name="Dwarka Business Chambers"),
    dict(label="Karnataka", state="29", district="02", subdistrict="004", village="061", plot="0087",
         address="Plot 87, Whitefield, Bengaluru, Karnataka (representative demo address)",
         lat=12.9698, lon=77.7500, width=28, depth=20, building_type="commercial",
         num_floors=10, name="Whitefield Tech Park"),
    dict(label="Tamil Nadu", state="33", district="01", subdistrict="003", village="094", plot="0056",
         address="Plot 56, T. Nagar, Chennai, Tamil Nadu (representative demo address)",
         lat=13.0418, lon=80.2341, width=18, depth=14, building_type="residential",
         num_floors=4, name="Kaveri Apartments"),
    dict(label="West Bengal", state="19", district="05", subdistrict="002", village="033", plot="0210",
         address="Plot 210, Salt Lake Sector V, Kolkata, West Bengal (representative demo address)",
         lat=22.5697, lon=88.4295, width=22, depth=16, building_type="commercial",
         num_floors=6, name="Salt Lake IT Tower"),
    dict(label="Gujarat", state="24", district="02", subdistrict="001", village="075", plot="0032",
         address="Plot 32, Satellite, Ahmedabad, Gujarat (representative demo address)",
         lat=23.0300, lon=72.5297, width=20, depth=15, building_type="residential",
         num_floors=5, name="Sabarmati Heights"),
    dict(label="Rajasthan", state="08", district="04", subdistrict="002", village="048", plot="0067",
         address="Plot 67, Malviya Nagar, Jaipur, Rajasthan (representative demo address)",
         lat=26.8515, lon=75.8054, width=19, depth=14, building_type="residential",
         num_floors=3, name="Pink City Residency"),
    dict(label="Uttar Pradesh", state="09", district="06", subdistrict="003", village="102", plot="0091",
         address="Plot 91, Gomti Nagar, Lucknow, Uttar Pradesh (representative demo address)",
         lat=26.8500, lon=81.0000, width=21, depth=16, building_type="mixed",
         num_floors=7, name="Gomti Business Square"),
    dict(label="Kerala", state="32", district="01", subdistrict="002", village="019", plot="0013",
         address="Plot 13, Kakkanad, Kochi, Kerala (representative demo address)",
         lat=10.0159, lon=76.3419, width=17, depth=13, building_type="residential",
         num_floors=4, name="Backwater View Residency"),
    dict(label="Punjab", state="03", district="02", subdistrict="001", village="041", plot="0028",
         address="Plot 28, Sector 17, Chandigarh (Punjab region, representative demo address)",
         lat=30.7410, lon=76.7828, width=18, depth=14, building_type="commercial",
         num_floors=4, name="Sector 17 Trade Centre"),
    dict(label="Telangana", state="36", district="01", subdistrict="004", village="066", plot="0155",
         address="Plot 155, HITEC City, Hyderabad, Telangana (representative demo address)",
         lat=17.4435, lon=78.3772, width=26, depth=20, building_type="commercial",
         num_floors=12, name="HITEC Skyline Tower"),
    dict(label="Assam", state="18", district="01", subdistrict="001", village="022", plot="0009",
         address="Plot 9, Zoo Road, Guwahati, Assam (representative demo address)",
         lat=26.1445, lon=91.7362, width=16, depth=12, building_type="residential",
         num_floors=3, name="Brahmaputra View Apartments"),
    dict(label="Madhya Pradesh", state="23", district="03", subdistrict="002", village="058", plot="0074",
         address="Plot 74, Arera Colony, Bhopal, Madhya Pradesh (representative demo address)",
         lat=23.2156, lon=77.4098, width=19, depth=15, building_type="residential",
         num_floors=5, name="Arera Green Residency"),
    dict(label="Bihar", state="10", district="01", subdistrict="003", village="037", plot="0121",
         address="Plot 121, Boring Road, Patna, Bihar (representative demo address)",
         lat=25.6127, lon=85.1197, width=25, depth=19, building_type="mixed",
         num_floors=15, name="Ganga Vista Towers"),
    dict(label="Odisha", state="21", district="02", subdistrict="001", village="014", plot="0046",
         address="Plot 46, Saheed Nagar, Bhubaneswar, Odisha (representative demo address)",
         lat=20.2833, lon=85.8333, width=17, depth=13, building_type="residential",
         num_floors=4, name="Kalinga Residency"),
]

UNIT_TYPE_CYCLE = ["residential_unit", "residential_unit", "commercial_unit", "parking_unit"]


def _verification_for(floor_idx, num_floors, unit_idx):
    """Deterministic, varied spread of verification states so the review
    queue, search, and analytics all have something interesting to show:
    every 4th unit rejected, the top ~30% of floors left pending review
    (as if the surveyor just ran the pipeline and no one's reviewed the
    upper floors yet), and everything else approved."""
    if unit_idx % 4 == 0 and floor_idx == 0:
        return models.VerificationStatus.rejected
    if floor_idx >= max(1, int(num_floors * 0.7)):
        return models.VerificationStatus.pending_review
    return models.VerificationStatus.approved


def seed_multi_state_demo(db, verifier_user=None):
    """Idempotent: skips any entry whose ULPIN already exists, so running
    this alongside repeated `python -m app.seed` calls never duplicates
    data. Returns the number of NEW parcels created."""
    created = 0
    for entry in STATE_ENTRIES:
        ulpin_2d = ulpin_service.generate_2d_ulpin(
            db, entry["state"], entry["district"], entry["subdistrict"], entry["village"], entry["plot"]
        )
        existing = db.query(models.Parcel).filter(models.Parcel.ulpin_2d == ulpin_2d).first()
        if existing:
            continue

        w, d = entry["width"], entry["depth"]
        footprint = [[0, 0], [w, 0], [w, d], [0, d], [0, 0]]
        parcel = models.Parcel(
            ulpin_2d=ulpin_2d, state_code=entry["state"], district_code=entry["district"],
            subdistrict_code=entry["subdistrict"], village_code=entry["village"], plot_code=entry["plot"],
            address=entry["address"], centroid_lat=entry["lat"], centroid_lon=entry["lon"],
            footprint_geojson=json.dumps(footprint), area_sqm=round(w * d, 2),
        )
        db.add(parcel)
        db.flush()

        num_floors = entry["num_floors"]
        building_height = num_floors * FLOOR_HEIGHT
        building = models.Building(
            parcel_id=parcel.id, building_code="B01", name=entry["name"],
            building_type=entry["building_type"], num_floors=num_floors, height_m=building_height,
            footprint_geojson=json.dumps(footprint),
            ai_confidence=round(min(0.97, 0.88 + 0.005 * num_floors), 2),
        )
        db.add(building)
        db.flush()

        cell_w, cell_d = w / 2 * 0.9, d / 2 * 0.9
        for i in range(1, num_floors + 1):
            floor = models.Floor(
                building_id=building.id, floor_code=f"F{i:02d}", floor_number=i,
                z_min=(i - 1) * FLOOR_HEIGHT, z_max=i * FLOOR_HEIGHT,
                ai_confidence=round(min(0.96, 0.87 + 0.004 * i), 2),
            )
            db.add(floor)
            db.flush()

            idx = 1
            for r in range(2):
                for c in range(2):
                    x0, y0 = c * (w / 2), r * (d / 2)
                    x1, y1 = x0 + cell_w, y0 + cell_d
                    unit_code = f"U{idx:02d}"
                    unit_ulpin = ulpin_service.generate_3d_ulpin(ulpin_2d, building.building_code, floor.floor_code, unit_code)
                    status = _verification_for(i - 1, num_floors, idx)
                    unit = models.Unit(
                        floor_id=floor.id, unit_code=unit_code, ulpin_3d=unit_ulpin,
                        parcel_type=UNIT_TYPE_CYCLE[idx - 1],
                        footprint_geojson=json.dumps([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]),
                        area_sqm=round((x1 - x0) * (y1 - y0), 2),
                        volume_cum=round((x1 - x0) * (y1 - y0) * FLOOR_HEIGHT, 2),
                        z_min=floor.z_min, z_max=floor.z_max,
                        owner_reference=f"OWNER_{entry['state']}_{i:02d}{idx:02d}",
                        ai_confidence=round(0.84 + 0.02 * idx, 2),
                        verification_status=status,
                        verified_by=(verifier_user.id if verifier_user and status == models.VerificationStatus.approved else None),
                        verified_at=(datetime.utcnow() if status == models.VerificationStatus.approved else None),
                    )
                    db.add(unit)
                    idx += 1
        db.flush()
        created += 1
        print(f"  [{entry['label']}] Parcel {ulpin_2d} — {entry['name']} ({num_floors} floors, 4 units/floor)")

    db.commit()
    return created


if __name__ == "__main__":
    from .database import SessionLocal, Base, engine

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        verifier = db.query(models.User).filter(models.User.role == models.RoleEnum.verifier).first()
        print("Seeding multi-state demo dataset (additive, idempotent)...")
        n = seed_multi_state_demo(db, verifier_user=verifier)
        print(f"\nDone. {n} new state parcel(s) added out of {len(STATE_ENTRIES)} total entries defined.")
        if n < len(STATE_ENTRIES):
            print(f"({len(STATE_ENTRIES) - n} already existed and were left untouched.)")
    finally:
        db.close()
