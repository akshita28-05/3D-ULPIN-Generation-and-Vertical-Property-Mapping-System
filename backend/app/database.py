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

# This file lives at <backend>/app/database.py -- BACKEND_DIR is always
# <backend>, regardless of which directory the CURRENT PROCESS happened
# to be launched/run from.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default: local Postgres+PostGIS via docker-compose.yml at the repo root
# (POSTGRES_USER=sih_user, POSTGRES_PASSWORD=sih_password, POSTGRES_DB=sih_ulpin,
# published on the default port 5432 -- see that file / README "Database" section).
_DEFAULT_DATABASE_URL = "postgresql://sih_user:sih_password@localhost:5432/sih_ulpin"

_raw_database_url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)

# Render (and Heroku before it) hand out managed Postgres URLs starting "postgres://",
# a scheme SQLAlchemy 1.4+ no longer recognises on its own (raises NoSuchModuleError).
# Normalise it to "postgresql://" so pasting Render's "External Database URL" straight
# into DATABASE_URL just works.
if _raw_database_url.startswith("postgres://"):
    _raw_database_url = "postgresql://" + _raw_database_url[len("postgres://"):]

if _raw_database_url.startswith("sqlite:///.") and not _raw_database_url.startswith("sqlite:////"):
    # A RELATIVE sqlite path resolves against the process's current
    # working directory -- which silently differs between "cd backend
    # && uvicorn app.main:app" and "python scripts/load_ms_footprints.py"
    # run from a different folder (or a different terminal/IDE run
    # config). Two different physical .db files result, so anything a
    # script loads never appears in the running app -- indistinguishable,
    # from the app's side, from "that quadkey file doesn't cover this
    # area". Anchoring the relative part to BACKEND_DIR instead makes
    # every process resolve to the exact same file no matter its own cwd.
    # (An explicit absolute DATABASE_URL, sqlite:////abs/path, or a
    # non-sqlite URL bypasses this and is used exactly as given.)
    relative_part = _raw_database_url.split("sqlite:///", 1)[1]  # e.g. "./sih_ulpin.db" -> keep as given
    DATABASE_URL = f"sqlite:///{os.path.normpath(os.path.join(BACKEND_DIR, relative_part))}"
else:
    DATABASE_URL = _raw_database_url

# Whether this process is running against a Postgres+PostGIS backend. Used
# by models.py to conditionally attach real geoalchemy2.Geometry columns
# (SQLite has no PostGIS DDL support, so the fallback path keeps using the
# plain JSON-text geometry columns instead). See ARCHITECTURE.md /
# scripts/migrate_to_postgis.py for the full migration notes.
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
    except Exception as exc:  # noqa: BLE001 -- deliberately non-fatal, see docstring
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