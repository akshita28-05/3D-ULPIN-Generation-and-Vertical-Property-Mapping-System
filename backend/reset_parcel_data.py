"""
ONE-TIME, DESTRUCTIVE: wipes every parcel/building/floor/unit (and
everything that references them) from the database, so the app starts
completely fresh -- the next parcel you create manually or detect via the
YOLO/ML pipeline is the first row in a clean table.

This does NOT touch: users, location_codes, datasets, gnss_control_points,
parties, notifications, password_reset_tokens, audit_logs -- only the
land-record data tree rooted at parcels/buildings.

Why a separate script instead of just running it for you: this deletes
real rows from YOUR live database file, and I don't have access to your
actual running SQLite database (only the project's code was uploaded, not
its data) -- so this has to be something you run yourself, deliberately,
against your own dev.db. It asks for a typed confirmation before it
touches anything, and it will not run silently or automatically.

Usage:
    cd backend
    python reset_parcel_data.py
"""
import sys
sys.path.insert(0, __file__.rsplit("/reset_parcel_data.py", 1)[0])

from app.database import SessionLocal
from app import models


def main():
    db = SessionLocal()
    try:
        counts = {
            "parcels": db.query(models.Parcel).count(),
            "buildings": db.query(models.Building).count(),
            "floors": db.query(models.Floor).count(),
            "units": db.query(models.Unit).count(),
            "bulk_import_jobs": db.query(models.BulkImportJob).count(),
        }
        print("About to permanently delete:")
        for k, v in counts.items():
            print(f"  {k}: {v}")
        print("\nThis cannot be undone. Type 'yes' to proceed, anything else to abort.")
        if input("> ").strip().lower() != "yes":
            print("Aborted -- nothing was deleted.")
            return

        db.query(models.Grievance).filter(models.Grievance.unit_id.isnot(None)).delete(synchronize_session=False)
        db.query(models.Unit).delete(synchronize_session=False)
        db.query(models.Floor).delete(synchronize_session=False)
        db.query(models.ValidationResult).filter(models.ValidationResult.building_id.isnot(None)).delete(synchronize_session=False)
        db.query(models.ProcessingJob).filter(models.ProcessingJob.building_id.isnot(None)).delete(synchronize_session=False)
        db.query(models.Building).delete(synchronize_session=False)
        db.query(models.UndergroundAsset).delete(synchronize_session=False)
        db.query(models.AirRightCorridor).delete(synchronize_session=False)
        db.query(models.ChangeDetection).filter(models.ChangeDetection.parcel_id.isnot(None)).delete(synchronize_session=False)
        db.query(models.ExternalBuildingFootprint).delete(synchronize_session=False)
        db.query(models.Parcel).delete(synchronize_session=False)
        db.query(models.BulkImportJob).delete(synchronize_session=False)
        db.commit()
        print("Done -- all parcel/building data cleared. The manual parcel-creation form and the YOLO bulk-import pipeline are untouched and will write fresh rows into these same tables from here on.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
