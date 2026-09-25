"""
One-time loader: reads a downloaded Microsoft Global ML Building
Footprints quadkey file (the .csv.gz you get from a Url in
dataset-links.csv -- see https://github.com/microsoft/GlobalMLBuildingFootprints)
and inserts every real footprint into external_building_footprints, ready
for bulk_import_router.py to query by bbox.

Despite the .csv.gz extension, the file's actual content is
newline-delimited GeoJSON Features (one per line), not comma-separated
columns -- this loader reads it as such directly; no separate CSV parsing
needed.

Usage:
    python scripts/load_ms_footprints.py /path/to/part-00124-...csv.gz --quadkey 122002231001

--quadkey is optional but recommended -- it's just a label for tracing
which download file a row came from later; pass whatever QuadKey column
value that file corresponds to in dataset-links.csv (or its Location
name, e.g. "IndiaAndBhutan", if you don't have the exact quadkey handy).

This only loads the staging table -- it does NOT create any Parcel/
Building/ULPIN records by itself. Actually importing rows from a bbox
into real records happens via POST /api/bulk-import/commit with
source="ms_footprints", same as the existing OSM path.
"""
import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import func
from app.database import SessionLocal, engine, Base, DATABASE_URL
from app import models

BATCH_SIZE = 2000


def _open(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path, "r")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="Path to the downloaded quadkey file (.csv.gz or already-decompressed)")
    parser.add_argument("--quadkey", default=None, help="Label for tracing which download this came from (optional)")
    parser.add_argument("--source", default="ms_building_footprints")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    resolved_db_path = os.path.abspath(engine.url.database) if engine.url.database else "(in-memory)"
    print(f"Writing to database: {DATABASE_URL} -> resolved path: {resolved_db_path}")
    print("If this is NOT the same .db file your `uvicorn`/backend server is running against, nothing you load here will show up in the app.\n")

    db = SessionLocal()
    inserted = 0
    skipped = 0
    batch = []

    try:
        with _open(args.file) as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    feature = json.loads(line)
                    geometry = feature["geometry"]
                    if geometry["type"] != "Polygon":
                        skipped += 1
                        continue
                    ring = geometry["coordinates"][0]
                    if len(ring) < 3:
                        skipped += 1
                        continue

                    lats = [pt[1] for pt in ring]
                    lons = [pt[0] for pt in ring]
                    centroid_lat = sum(lats) / len(lats)
                    centroid_lon = sum(lons) / len(lons)

                    raw_height = feature.get("properties", {}).get("height")
                    height_m = raw_height if (raw_height is not None and raw_height > 0) else None

                    batch.append(models.ExternalBuildingFootprint(
                        source=args.source,
                        quadkey=args.quadkey,
                        confidence=feature.get("properties", {}).get("confidence"),
                        height_m=height_m,
                        centroid_lat=centroid_lat,
                        centroid_lon=centroid_lon,
                        footprint_latlon_geojson=json.dumps([[lat, lon] for lon, lat in ring]),
                    ))
                    inserted += 1
                except (KeyError, ValueError, IndexError, TypeError) as e:
                    skipped += 1
                    if skipped <= 5:
                        print(f"  [line {line_num}] skipped (malformed): {e}")

                if len(batch) >= BATCH_SIZE:
                    db.bulk_save_objects(batch)
                    db.commit()
                    print(f"  ...{inserted} loaded so far")
                    batch = []

        if batch:
            db.bulk_save_objects(batch)
            db.commit()

        print(f"\nDone: {inserted} footprints loaded, {skipped} lines skipped (malformed or non-Polygon).")
        print("These are staged in external_building_footprints -- nothing is a real Parcel/Building yet.")
        print("Draw a bbox covering this area and use POST /api/bulk-import/commit with source=\"ms_footprints\" to actually import them.")

        total = db.query(models.ExternalBuildingFootprint).count()
        bounds = db.query(
            func.min(models.ExternalBuildingFootprint.centroid_lat),
            func.max(models.ExternalBuildingFootprint.centroid_lat),
            func.min(models.ExternalBuildingFootprint.centroid_lon),
            func.max(models.ExternalBuildingFootprint.centroid_lon),
        ).first()
        print(f"\nTotal footprints in this database now (all quadkeys combined): {total}")
        if total and bounds and bounds[0] is not None:
            print(f"Real coverage of everything loaded so far -- lat {bounds[0]:.4f} to {bounds[1]:.4f}, lon {bounds[2]:.4f} to {bounds[3]:.4f}")
            print("Draw your bbox on the GIS Map inside that range -- anywhere outside it will always show 0 buildings (correctly -- there's no data there, not a bug).")

    finally:
        db.close()


if __name__ == "__main__":
    main()
