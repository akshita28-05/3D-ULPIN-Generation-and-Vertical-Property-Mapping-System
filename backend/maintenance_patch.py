"""
NON-DESTRUCTIVE: renames existing buildings whose `name` still reads
"ML-detected building <id>" (the old display name used by the MS
Building Footprints bulk-import path in bulk_import_router.py) to the
new "<Type> Building <id>" scheme -- e.g. "Residential Building
7ec12feb" -- without touching anything else on the row.

Only ever run once needed: any building imported AFTER this session's
change to bulk_import_router.py already gets the new name at insert
time, so this only matters for rows created by an earlier server run.
Safe to re-run -- it only matches rows still starting with the old
prefix, so a second run is a no-op.

Usage:
    cd backend
    python maintenance_patch.py
"""
from app.database import SessionLocal
from app import models

OLD_PREFIX = "ML-detected building "


def main():
    db = SessionLocal()
    try:
        rows = db.query(models.Building).filter(models.Building.name.like(f"{OLD_PREFIX}%")).all()
        if not rows:
            print("No buildings with the old 'ML-detected building ...' name found -- nothing to do.")
            return
        for b in rows:
            id_slice = b.name[len(OLD_PREFIX):].strip()
            type_label = (b.building_type or "unsurveyed").capitalize()
            b.name = f"{type_label} Building {id_slice}"
        db.commit()
        print(f"Renamed {len(rows)} building(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
