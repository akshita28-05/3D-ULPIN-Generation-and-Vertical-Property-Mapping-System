"""
One-time migration: adds real PostGIS geometry columns to an existing
Postgres database and backfills them from the current *_geojson Text
columns. Run this once, after pointing DATABASE_URL at Postgres and
running `alembic upgrade head` / `Base.metadata.create_all()` (which adds
the new `geom` columns declared in models.py, since IS_POSTGIS is now
true) but before relying on any endpoint that queries `geom` directly.

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    pip install psycopg2-binary geoalchemy2
    python scripts/migrate_to_postgis.py

What this does NOT do: it does not touch or remove the *_geojson columns.
Every existing router keeps working unchanged against them. This is
additive -- run it as many times as you like; it only fills geom where
geom IS NULL and the geojson column has data.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text

from app.database import engine, DATABASE_URL, IS_POSTGIS
from app.models import Base


TABLES = [
    ("parcels", "footprint_geojson", "geom", "Polygon"),
    ("buildings", "footprint_geojson", "geom", "Polygon"),
    ("underground_assets", "geometry_geojson", "geom", "LineString"),
    ("air_right_corridors", "geometry_geojson", "geom", "Polygon"),
]


def main():
    if not IS_POSTGIS:
        print(f"DATABASE_URL is not Postgres ({DATABASE_URL!r}) -- nothing to do. "
              f"Set DATABASE_URL=postgresql://... before running this script.")
        return

    with engine.begin() as conn:
        print("Enabling postgis extension (no-op if already enabled)...")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

        print("Creating any tables/columns declared in models.py (including geom columns)...")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for table, geojson_col, geom_col, geom_type in TABLES:
            print(f"Backfilling {table}.{geom_col} from {table}.{geojson_col} ...")
            if geom_type == "LineString":
                conn.execute(text(f"""
                    UPDATE {table}
                    SET {geom_col} = ST_SetSRID(
                        ST_GeomFromGeoJSON(
                            json_build_object('type', 'LineString', 'coordinates', {geojson_col}::json)::text
                        ), 4326
                    )
                    WHERE {geom_col} IS NULL AND {geojson_col} IS NOT NULL AND {geojson_col} != '';
                """))
            else:
                conn.execute(text(f"""
                    UPDATE {table}
                    SET {geom_col} = ST_SetSRID(
                        ST_GeomFromGeoJSON(
                            json_build_object('type', 'Polygon', 'coordinates', json_build_array({geojson_col}::json))::text
                        ), 4326
                    )
                    WHERE {geom_col} IS NULL AND {geojson_col} IS NOT NULL AND {geojson_col} != '';
                """))

    print("Done. geom columns are now populated for rows that had valid GeoJSON. "
          "New writes should call app.geo.sync_geom_from_geojson(obj) before commit "
          "to keep geom in sync going forward.")


if __name__ == "__main__":
    main()
