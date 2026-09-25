"""
Database connection.

Uses PostgreSQL + PostGIS by default (see docker-compose.yml for a
ready-to-run local Postgres+PostGIS container, and .env.example for the
connection string). SQLite is still supported as a zero-setup fallback
(e.g. quick offline scripting) -- set DATABASE_URL="sqlite:///./sih_ulpin.db"
to opt back into it; the schema and every router run identically either
way, just without the real geometry columns/spatial queries described
below.

Moving to (or confirming) PostgreSQL + PostGIS:
  1. pip install -r requirements.txt (psycopg2-binary + geoalchemy2 are
     required dependencies, not optional, since Postgres is the default).
  2. Set DATABASE_URL="postgresql://user:pass@host:5432/dbname" (already
     the default -- see .env.example / docker-compose.yml).
  3. Nothing else to run by hand: on startup this module enables the
     PostGIS extension and Base.metadata.create_all() (in main.py) creates
     the real geoalchemy2.Geometry columns itself; models.py attaches them
     automatically whenever IS_POSTGIS is true. The plain lat/lon/JSON-text
     columns are kept alongside them (not removed) so existing data and
     every router keep working unchanged -- run
     `python scripts/migrate_to_postgis.py` once after switching an
     *existing* SQLite deployment's data over, to backfill `geom` from
     the JSON columns already on disk.
"""
import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_DATABASE_URL = "postgresql://sih_user:sih_password@localhost:5432/sih_ulpin"

_raw_database_url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)

if _raw_database_url.startswith("sqlite:///.") and not _raw_database_url.startswith("sqlite:////"):
    relative_part = _raw_database_url.split("sqlite:///", 1)[1]
    DATABASE_URL = f"sqlite:///{os.path.normpath(os.path.join(BACKEND_DIR, relative_part))}"
else:
    DATABASE_URL = _raw_database_url

IS_POSTGIS = DATABASE_URL.startswith("postgresql")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _ensure_postgis_extension():
    """Best-effort `CREATE EXTENSION IF NOT EXISTS postgis;` on startup so a
    fresh Postgres database (e.g. the docker-compose one) doesn't need a
    manual psql step before Base.metadata.create_all() can add the
    geoalchemy2.Geometry columns declared in models.py. Only runs when
    DATABASE_URL is Postgres; silently skipped on SQLite. Failures are
    logged, not raised, so a DB user without CREATE EXTENSION privilege
    (extension already enabled by a DBA) doesn't block app startup.
    """
    if not IS_POSTGIS:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
    except Exception as exc:
        logger.warning(
            "Could not auto-enable the postgis extension (%s). If it isn't already "
            "enabled on this database, spatial columns/queries will fail -- run "
            "`CREATE EXTENSION postgis;` yourself as a superuser.",
            exc,
        )


_ensure_postgis_extension()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
