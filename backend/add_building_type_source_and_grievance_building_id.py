"""
NON-DESTRUCTIVE: adds two new columns to your EXISTING SQLite database
without touching any existing rows.

This project uses Base.metadata.create_all() (see app/database.py /
app/main.py), which only creates tables that don't exist yet -- it will
NOT add a new column to a table that's already there. Two columns were
added to models.py in this session:
  - buildings.building_type_source  (TEXT, default 'manual')
  - grievances.building_id          (TEXT, nullable, FK -> buildings.id)

Run this once against your existing sih_ulpin.db so those columns exist
before the app starts using them -- otherwise every query touching
Building or Grievance will fail with "no such column".

If you'd rather start from a totally empty database instead, you can
skip this and use reset_parcel_data.py / just delete sih_ulpin.db --
Base.metadata.create_all() will create the new, complete schema from
scratch the next time the app starts. This script exists for the case
where you want to KEEP your existing parcels/buildings/grievances.

Usage:
    cd backend
    python add_building_type_source_and_grievance_building_id.py
"""
import sqlite3
import sys

sys.path.insert(0, __file__.rsplit("/add_building_type_source_and_grievance_building_id.py", 1)[0])

from app.database import DATABASE_URL


def _sqlite_path_from_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        raise SystemExit(
            f"DATABASE_URL is '{url}', not a local SQLite file. "
            "This script only handles SQLite -- if you're on PostgreSQL, "
            "add these two columns with a normal ALTER TABLE / your own "
            "migration tool instead:\n"
            "  ALTER TABLE buildings ADD COLUMN building_type_source VARCHAR DEFAULT 'manual';\n"
            "  ALTER TABLE grievances ADD COLUMN building_id VARCHAR REFERENCES buildings(id);"
        )
    return url[len("sqlite:///"):]


def _column_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def main():
    db_path = _sqlite_path_from_url(DATABASE_URL)
    print(f"Using database file: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        if _column_exists(cur, "buildings", "building_type_source"):
            print("buildings.building_type_source already exists -- skipping.")
        else:
            cur.execute("ALTER TABLE buildings ADD COLUMN building_type_source VARCHAR DEFAULT 'manual'")
            print("Added buildings.building_type_source")

        if _column_exists(cur, "grievances", "building_id"):
            print("grievances.building_id already exists -- skipping.")
        else:
            cur.execute("ALTER TABLE grievances ADD COLUMN building_id VARCHAR")
            print("Added grievances.building_id")

        conn.commit()
        print("Done -- existing rows are untouched, both columns default to NULL/'manual' as appropriate.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
