"""NON-DESTRUCTIVE: adds provenance columns to air_right_corridors on an EXISTING
SQLite DB (create_all() never alters existing tables):
    source, detection_confidence, height_source, detection_notes
    cd backend && python add_air_right_provenance_columns.py
PostgreSQL: run the equivalent ALTER TABLE ... ADD COLUMN IF NOT EXISTS yourself."""
import sqlite3, sys
sys.path.insert(0, __file__.rsplit("/add_air_right_provenance_columns.py", 1)[0])
from app.database import DATABASE_URL

if not DATABASE_URL.startswith("sqlite:///"):
    raise SystemExit("Not SQLite -- add the 4 columns with your own migration (see docstring).")
con = sqlite3.connect(DATABASE_URL.replace("sqlite:///", "", 1))
have = {r[1] for r in con.execute("PRAGMA table_info(air_right_corridors)")}
for col, ddl in [("source", "TEXT DEFAULT 'manual'"), ("detection_confidence", "REAL"),
                 ("height_source", "TEXT"), ("detection_notes", "TEXT")]:
    if col not in have:
        con.execute(f"ALTER TABLE air_right_corridors ADD COLUMN {col} {ddl}"); print("added", col)
con.commit(); con.close(); print("done")
