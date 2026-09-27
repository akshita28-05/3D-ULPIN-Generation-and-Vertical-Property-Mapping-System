import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from .database import Base, engine
from .routers import (
    auth_router, parcels_router, processing_router, review_router,
    grievances_router, misc_routers, assets_router, users_router, geocode_router,
    detection_router, rrr_router, underground_router, spatial_router, tiles_router, bulk_import_router,
    auto_router, map_router, lifecycle_router, interop_router, infra_router,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="3D ULPIN Generation & Vertical Property Mapping System",
    description=(
        "SIH26011 prototype API — Ministry of Rural Development / DoLR. "
        "2D ULPIN prefixes used throughout are representative/sample values "
        "in the real 14-digit format, not fetched from a live government system."
    ),
    version="1.0.0",
)

import os

# Set CORS_ALLOWED_ORIGINS on Render to your Vercel URL(s), comma-separated
# (e.g. "https://vasudha3d.vercel.app,https://vasudha3d-git-main.vercel.app").
# Falls back to "*" (any origin) so local dev and a first deploy work with nothing set.
_cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
_allowed_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip-compresses responses over 1KB -- meaningfully cuts bandwidth for
# larger JSON payloads (e.g. a parcel with many floors/units, or the
# audit log) under concurrent load, and speeds up response time for
# users on slower connections.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Never leak raw stack traces — return a clean, friendly error shape
    return JSONResponse(status_code=422, content={"detail": "Invalid request data", "errors": exc.errors()})


app.include_router(auth_router.router)
app.include_router(parcels_router.router)
app.include_router(processing_router.router)
app.include_router(review_router.router)
app.include_router(grievances_router.router)
app.include_router(misc_routers.audit_router)
app.include_router(misc_routers.export_router)
app.include_router(misc_routers.analytics_router)
app.include_router(misc_routers.notifications_router)
app.include_router(assets_router.router)
app.include_router(users_router.router)
app.include_router(users_router.system_router)
app.include_router(geocode_router.router)
app.include_router(rrr_router.router)
app.include_router(underground_router.router)
app.include_router(spatial_router.router)
app.include_router(tiles_router.router)
app.include_router(bulk_import_router.router)
app.include_router(auto_router.router)
app.include_router(map_router.router)
app.include_router(lifecycle_router.router)
app.include_router(interop_router.router)
app.include_router(detection_router.router)
app.include_router(infra_router.router)

# Serves generated 3D Tiles tilesets (tileset.json + per-building .glb)
# straight from disk -- a CesiumJS Cesium3DTileset can point directly at
# /tiles/{parcel_id}/tileset.json. Mounted after all API routers so it
# never shadows an /api/... path.
import os as _os  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from .routers.tiles_router import TILES_DIR  # noqa: E402

_os.makedirs(TILES_DIR, exist_ok=True)
app.mount("/tiles", StaticFiles(directory=TILES_DIR), name="tiles")

from . import change_detection_scheduler  # noqa: E402


@app.on_event("startup")
def _start_change_detection_scheduler():
    change_detection_scheduler.start()


@app.on_event("shutdown")
def _stop_change_detection_scheduler():
    change_detection_scheduler.stop()


@app.get("/")
def root():
    return {
        "system": "3D ULPIN Generation & Vertical Property Mapping System",
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}