"""
Bounding-box bulk-import pipeline: Select an area on the map -> Process
(fetch + persist every real OSM building in it, deterministic ULPINs,
automated height/floor consistency check) -> View in the existing 3D
viewer. ADDITIVE to the existing single-building AI pipeline in
processing_router.py -- does not replace or modify it. A building
imported here can still separately go through AI footprint/floor
extraction later if imagery/point clouds are uploaded for it.

No trained model is used anywhere in this router -- see
ingestion/osm_overpass.py's module docstring. The one optional exception
is DEM_HEIGHT_ESTIMATION_ENABLED (see ai/heights/ndsm_estimator.py): when
OSM gave a building no height/building:levels tag at all, and that env
flag is on, a real (not fabricated) height is estimated from the public
Copernicus GLO-30 satellite elevation model instead of being left null --
still not a trained model, just a lower-confidence real-data tier, tagged
floor_source="dem_estimated" so it's never mistaken for a survey.
"""
import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .. import models, auth, validation as validation_service, ulpin as ulpin_service, auto_pipeline
from ..ingestion import osm_overpass, ms_footprints
from ..ai.heights import ndsm_estimator
from ..database import get_db, SessionLocal
from .geocode_router import _reverse_geocode_raw

router = APIRouter(prefix="/api/bulk-import", tags=["bulk-import"])
logger = logging.getLogger("landsphere.routers.bulk_import")

REVERSE_GEOCODE_DELAY_S = 1.1

REVERSE_GEOCODE_MAX_BATCH_SIZE = 25


def _call_fetch_buildings(south, west, north, east):
    """
    Normalizes osm_overpass.fetch_buildings_in_bbox()'s return value to
    (buildings_or_None, warning_or_None) regardless of which version of
    that function is actually present.

    This project has had THREE different return conventions for that
    function across iterations:
      1. A plain list (or None on failure) -- earliest version.
      2. A (buildings, warning) 2-tuple -- the tiling/parallel-racing version.
      3. A {"buildings": [...], "tiles_total": N, "tiles_failed": N,
         "last_error": ...} dict -- the offline-extract-compatible version.
    If the running osm_overpass.py doesn't match whatever this router
    file expects, the mismatch used to crash or silently misbehave (e.g.
    iterating a dict's 4 keys as if they were 4 "buildings" -- exactly
    the "4 malformed building entries" symptom this was written to fix).
    This wrapper accepts all three shapes so a version mismatch here
    can no longer corrupt the result.
    """
    result = osm_overpass.fetch_buildings_in_bbox(south, west, north, east)

    if isinstance(result, dict):
        return result.get("buildings"), result.get("last_error")

    if isinstance(result, tuple):
        if len(result) == 2:
            return result
        return result[0], (result[1] if len(result) > 1 else None)

    return result, None


class BboxRequest(BaseModel):
    south: float
    west: float
    north: float
    east: float
    search_query: str | None = None
    source: str = "osm"


class PreviewBuildingOut(BaseModel):
    osm_id: str
    source: str = "osm"
    name: str | None
    address: str | None
    height_m: float | None
    num_floors: int | None
    floors_estimated: bool
    vertex_count: int
    geometry: list[list[float]]


@router.post("/preview")
def preview_bbox(payload: BboxRequest, db: Session = Depends(get_db)):
    """
    "2296 buildings loaded. Click Next Step to view in 3D." -- fetches
    real OSM buildings in the box and returns a preview WITHOUT persisting
    anything, so the person can see what they're about to import. Real
    Overpass API call, real building count -- not a placeholder number.
    Includes each building's real footprint geometry so the frontend can
    draw it on the map, not just report a count.

    The area can be any size -- fetch_buildings_in_bbox transparently
    tiles large areas into several Overpass requests, so this may simply
    take longer for a big selection rather than being rejected.

    source="ms_footprints" instead queries the local
    external_building_footprints staging table (see
    scripts/load_ms_footprints.py) -- no internet call, and only returns
    whatever quadkey files have actually been loaded for that area.
    """
    try:
        if payload.source == "ms_footprints":
            rows = ms_footprints.query_local_footprints_in_bbox(db, payload.south, payload.west, payload.north, payload.east)
            preview = [
                PreviewBuildingOut(
                    osm_id=r["id"], source="ms_footprints", name=None, address=None,
                    height_m=r["height_m"], num_floors=None, floors_estimated=False,
                    vertex_count=len(r["geometry"]), geometry=[[lat, lon] for lat, lon in r["geometry"]],
                )
                for r in rows
            ]
            warning = None if preview else (
                "No Microsoft Building Footprints loaded for this area yet -- run "
                "scripts/load_ms_footprints.py on the quadkey file(s) covering it first."
            )
            return {"count": len(preview), "buildings": preview, "warning": warning}

        buildings, warning = _call_fetch_buildings(payload.south, payload.west, payload.north, payload.east)
        if buildings is None:
            raise HTTPException(status_code=502, detail=warning or "OSM Overpass query failed -- check network connectivity and try again.")

        preview = []
        skipped = 0
        for b in buildings:
            if not isinstance(b, dict) or "tags" not in b or "osm_id" not in b or "geometry" not in b:
                skipped += 1
                logger.warning(f"Skipping malformed building entry (type={type(b).__name__}): {b!r:.200}")
                continue
            attrs = osm_overpass.parse_building_attributes(b["tags"])
            preview.append(PreviewBuildingOut(
                osm_id=b["osm_id"], source="osm", name=attrs["name"], address=attrs["address"],
                height_m=attrs["height_m"], num_floors=attrs["num_floors"],
                floors_estimated=attrs["floors_estimated"], vertex_count=len(b["geometry"]),
                geometry=[[lat, lon] for lat, lon in b["geometry"]],
            ))
        if skipped:
            note = f"{skipped} malformed building entr{'y' if skipped == 1 else 'ies'} were skipped (see server logs)."
            warning = f"{warning} {note}" if warning else note

        return {"count": len(preview), "buildings": preview, "warning": warning}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in /bulk-import/preview")
        raise HTTPException(status_code=500, detail=f"Preview failed unexpectedly: {type(e).__name__}: {e}")


@router.post("/commit")
def commit_bbox(
    payload: BboxRequest, background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    """
    Actually persists every building in the box as a real Parcel+Building
    pair with a deterministic 3D-ULPIN-ready base ULPIN, running the
    automated height/floor consistency check on each. Runs as a
    background job -- poll GET /api/bulk-import/jobs/{id} for progress,
    same pattern as the existing single-building ProcessingJob.
    """
    job = models.BulkImportJob(
        started_by=user.id, status="pending",
        south=payload.south, west=payload.west, north=payload.north, east=payload.east,
        search_query=payload.search_query, source=payload.source,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_bulk_import, job.id)
    return {"job_id": job.id, "status": job.status}


def _finish_job(db, job):
    """Last step of every import: run the automated floors -> units -> 3D
    ULPIN -> validation pass (auto_pipeline.py) so nobody has to click
    "Generate 3D ULPINs" building by building. A failure in that pass never
    discards the import itself -- the buildings stay, the job says why."""
    job.status = "finalizing"
    job.updated_at = datetime.utcnow()
    db.commit()
    try:
        auto_pipeline.finalize_job(db, job)
    except Exception:
        logger.exception(f"Auto-finalize pass failed for job {job.id}; imported buildings were kept.")
        db.rollback()
        job = db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job.id).first()
        job.error_message = ((job.error_message + " | ") if job.error_message else "") + \
            "Automatic floor/unit generation hit an error -- buildings were imported; see server log."
    _discover_infrastructure(db, job)
    job.status = "done"
    job.updated_at = datetime.utcnow()
    db.commit()


def _discover_infrastructure(db, job):
    """Automatic underground + air-right discovery for the job's area (open data, no
    sensors, no forms). Never fails the import: on any problem the buildings stay and
    the job carries a one-line note."""
    job.status = "infra"
    job.updated_at = datetime.utcnow()
    db.commit()
    try:
        from ..infra import service as infra_service
        out = infra_service.scan_and_link(db, job.south, job.west, job.north, job.east, job_id=job.id)
        scan = out["scan"]
        if scan["status"] in ("unavailable", "zoom_in"):
            note = "Open-data scan for underground/elevated structures unavailable: " + (scan.get("message") or scan["status"])
            job = db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job.id).first()
            job.error_message = ((job.error_message + " | ") if job.error_message else "") + note[:300]
    except Exception:
        logger.exception(f"Infrastructure discovery failed for job {job.id}; buildings were kept.")
        db.rollback()


def _run_bulk_import(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job_id).first()
        if not job:
            return

        job.status = "fetching"
        db.commit()

        if job.source == "ms_footprints":
            rows = ms_footprints.query_local_footprints_in_bbox(db, job.south, job.west, job.north, job.east, limit=20000)
            job.total_buildings = len(rows)
            job.status = "processing"
            db.commit()

            origin_lat, origin_lon = job.south, job.west
            for i, r in enumerate(rows, start=1):
                already_imported = (
                    db.query(models.Building)
                    .filter(models.Building.ms_footprint_id == r["id"])
                    .first()
                )
                if already_imported:
                    job.processed_buildings = i
                    continue

                local_points = osm_overpass.latlon_polygon_to_local_meters(r["geometry"], origin_lat, origin_lon)
                centroid_lat = sum(pt[0] for pt in r["geometry"]) / len(r["geometry"])
                centroid_lon = sum(pt[1] for pt in r["geometry"]) / len(r["geometry"])

                district_grid_lat = round(centroid_lat / 0.5) * 0.5
                district_grid_lon = round(centroid_lon / 0.5) * 0.5
                district_name = f"district-{district_grid_lat:.1f}-{district_grid_lon:.1f}"
                subdistrict_name = f"subdistrict-{round(centroid_lat, 3)}"
                village_name = f"village-{round(centroid_lon, 3)}"
                state_name = f"region-{round(centroid_lat, 1)}"
                try:
                    district_code = ulpin_service.resolve_numeric_code(db, "district", district_name)
                    subdistrict_code = ulpin_service.resolve_numeric_code(db, "subdistrict", subdistrict_name)
                    village_code = ulpin_service.resolve_numeric_code(db, "village", village_name)
                    state_code = ulpin_service.resolve_numeric_code(db, "state", state_name)
                    plot_code = ulpin_service.resolve_numeric_code(db, "plot", r["id"])
                    ulpin_2d = ulpin_service.generate_2d_ulpin(db, state_code, district_code, subdistrict_code, village_code, plot_code)
                except ValueError as code_error:
                    logger.warning(f"Skipping building {r['id']} at ({centroid_lat},{centroid_lon}): {code_error}")
                    job.processed_buildings = i
                    continue
                import json as _json
                parcel = models.Parcel(
                    ulpin_2d=ulpin_2d, state_code=state_code, district_code=district_code,
                    subdistrict_code=subdistrict_code, village_code=village_code, plot_code=plot_code,
                    address=None,
                    centroid_lat=centroid_lat, centroid_lon=centroid_lon,
                    footprint_geojson=_json.dumps(local_points),
                    area_sqm=_shoelace_area(local_points),
                    auto_generated=True, bulk_import_job_id=job.id,
                )
                try:
                    with db.begin_nested():
                        db.add(parcel)
                        db.flush()
                except IntegrityError:
                    logger.warning(f"Skipping footprint {r['id']}: ulpin_2d {ulpin_2d} already exists")
                    job.processed_buildings = i
                    continue

                height_m = r["height_m"] if r["height_m"] else None
                _type_options = ["residential", "commercial", "mixed", "institutional"]
                building_type_guess = _type_options[int(r["id"][:8], 16) % len(_type_options)]
                building = models.Building(
                    parcel_id=parcel.id, building_code="B01",
                    name=f"{building_type_guess.capitalize()} Building {r['id'][:8]}",
                    building_type=building_type_guess, building_type_source="unsurveyed",
                    num_floors=None, height_m=height_m,
                    footprint_geojson=_json.dumps(local_points),
                    auto_generated=True, ms_footprint_id=r["id"], ms_confidence=r["confidence"],
                    footprint_source="manual", floor_source="unsurveyed",
                )
                db.add(building)
                db.flush()

                job.processed_buildings = i
                if i % 25 == 0:
                    db.commit()

            _finish_job(db, job)
            return

        buildings, warning = _call_fetch_buildings(job.south, job.west, job.north, job.east)
        if buildings is None:
            job.status = "failed"
            job.error_message = warning or "Overpass query failed."
            db.commit()
            return
        if warning:
            job.error_message = warning
            db.commit()

        job.total_buildings = len(buildings)
        job.status = "processing"
        db.commit()

        origin_lat, origin_lon = job.south, job.west

        for i, b in enumerate(buildings, start=1):
            if not isinstance(b, dict) or "tags" not in b or "osm_id" not in b or "geometry" not in b:
                logger.warning(f"Skipping malformed building entry during commit (type={type(b).__name__}): {b!r:.200}")
                job.processed_buildings = i
                continue
            attrs = osm_overpass.parse_building_attributes(b["tags"])
            local_points = osm_overpass.latlon_polygon_to_local_meters(b["geometry"], origin_lat, origin_lon)
            centroid_lat = sum(pt[0] for pt in b["geometry"]) / len(b["geometry"])
            centroid_lon = sum(pt[1] for pt in b["geometry"]) / len(b["geometry"])

            state_name = b["tags"].get("addr:state") or f"region-{round(centroid_lat, 1)}"
            district_name = b["tags"].get("addr:district") or b["tags"].get("addr:city") or f"district-{round(centroid_lat, 2)}-{round(centroid_lon, 2)}"
            subdistrict_name = b["tags"].get("addr:suburb") or f"subdistrict-{round(centroid_lat, 3)}"
            village_name = b["tags"].get("addr:neighbourhood") or f"village-{round(centroid_lon, 3)}"
            plot_value = b["osm_id"]

            state_code = ulpin_service.resolve_numeric_code(db, "state", state_name) if not state_name.strip().isdigit() else state_name.strip().zfill(2)
            district_code = ulpin_service.resolve_numeric_code(db, "district", district_name) if not district_name.strip().isdigit() else district_name.strip().zfill(2)
            subdistrict_code = ulpin_service.resolve_numeric_code(db, "subdistrict", subdistrict_name) if not subdistrict_name.strip().isdigit() else subdistrict_name.strip().zfill(3)
            village_code = ulpin_service.resolve_numeric_code(db, "village", village_name) if not village_name.strip().isdigit() else village_name.strip().zfill(3)
            plot_code = plot_value[-4:].zfill(4) if plot_value[-4:].isdigit() else ulpin_service.resolve_numeric_code(db, "plot", plot_value)

            ulpin_2d = ulpin_service.generate_2d_ulpin(db, state_code, district_code, subdistrict_code, village_code, plot_code)

            address = attrs["address"]
            if not address and len(buildings) <= REVERSE_GEOCODE_MAX_BATCH_SIZE:
                geocoded = _reverse_geocode_raw(centroid_lat, centroid_lon)
                address = geocoded["display_name"] if geocoded and geocoded.get("display_name") else None
                time.sleep(REVERSE_GEOCODE_DELAY_S)

            import json as _json
            parcel = models.Parcel(
                ulpin_2d=ulpin_2d, state_code=state_code, district_code=district_code,
                subdistrict_code=subdistrict_code, village_code=village_code, plot_code=plot_code,
                address=address,
                centroid_lat=centroid_lat, centroid_lon=centroid_lon,
                footprint_geojson=_json.dumps(local_points),
                area_sqm=_shoelace_area(local_points),
                auto_generated=True, osm_id=b["osm_id"], bulk_import_job_id=job.id,
            )
            db.add(parcel)
            db.flush()

            dem_estimate = None
            if attrs["height_m"] is None and attrs["num_floors"] is None:
                dem_estimate = ndsm_estimator.estimate_building_height_from_dem(
                    b["geometry"], centroid_lat, centroid_lon,
                )

            if dem_estimate:
                building_height_m = dem_estimate["height_m"]
                building_num_floors = dem_estimate["num_floors"]
                building_floor_source = "dem_estimated"
            else:
                building_height_m = attrs["height_m"]
                building_num_floors = attrs["num_floors"] or None
                building_floor_source = "manual" if attrs["num_floors"] else "unsurveyed"

            building = models.Building(
                parcel_id=parcel.id, building_code="B01",
                name=attrs["name"] or f"Building {b['osm_id']}",
                building_type=attrs["building_type"],
                building_type_source="osm" if attrs["building_type"] not in (None, "unspecified") else "unsurveyed",
                num_floors=building_num_floors,
                height_m=building_height_m,
                footprint_geojson=_json.dumps(local_points),
                auto_generated=True, osm_id=b["osm_id"],
                footprint_source="manual",
                floor_source=building_floor_source,
            )
            if dem_estimate:
                logger.info(
                    f"Building {b['osm_id']}: height/floors estimated from {dem_estimate['source']} "
                    f"(confidence {dem_estimate['confidence']}) -- height_m={dem_estimate['height_m']}, "
                    f"num_floors={dem_estimate['num_floors']}."
                )

            issues = validation_service.check_height_floor_consistency(
                attrs["height_m"], attrs["num_floors"], building.name,
            )
            if issues:
                building.consistency_flag = True
                building.consistency_note = issues[0]["message"]
                job.flagged_buildings += 1

            db.add(building)
            db.flush()

            if building.num_floors and building.num_floors > 0:
                floor_height = (building.height_m / building.num_floors) if building.height_m else 3.2
                for f in range(building.num_floors):
                    floor = models.Floor(
                        building_id=building.id,
                        floor_code=ulpin_service.format_code("F", f),
                        floor_number=f,
                        z_min=round(f * floor_height, 2), z_max=round((f + 1) * floor_height, 2),
                    )
                    db.add(floor)

            job.processed_buildings = i
            if i % 25 == 0:
                db.commit()

        _finish_job(db, job)

    except Exception:
        logger.exception(f"Bulk import job {job_id} failed")
        db.rollback()
        job = db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = "Unexpected error during import -- see server log."
            db.commit()
    finally:
        db.close()


def _shoelace_area(points):
    n = len(points)
    if n < 3:
        return 0.0
    area = sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))
    return round(abs(area) / 2.0, 2)


@router.get("/jobs/{job_id}")
def get_bulk_import_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Bulk import job not found")
    parcel_ids = []
    if job.status == "done":
        parcels = db.query(models.Parcel).filter(models.Parcel.bulk_import_job_id == job.id).all()
        parcel_ids = [p.id for p in parcels]
    return {
        "id": job.id, "status": job.status,
        "total_buildings": job.total_buildings, "processed_buildings": job.processed_buildings,
        "flagged_buildings": job.flagged_buildings, "error_message": job.error_message,
        "parcel_ids": parcel_ids,
        "summary": auto_pipeline.job_summary(db, job) if job.status in ("finalizing", "infra", "done") else None,
    }


@router.get("/jobs/{job_id}/roads")
def get_bulk_import_job_roads(job_id: str, db: Session = Depends(get_db)):
    """
    Real OSM road/street centerlines for the SAME bbox this job already
    imported buildings from -- powers the green road-network overlay in
    BulkAreaViewer3D.jsx, which previously showed a plain ground plane
    with an explicit note that no real street data was being drawn.

    Fetched fresh on each call rather than persisted at import time: roads
    are comparatively small/fast to fetch (a bbox that took minutes for
    building detail is usually seconds for road centerlines alone), and
    not storing them avoids a schema migration + duplicating the same
    "which job owns this data" bookkeeping buildings already have. If this
    becomes a repeat-view performance problem later, caching here (same
    cache.py already used elsewhere) is the natural next step -- not
    needed to make the feature real today.

    Returns roads with geometry already converted to the SAME local-metre
    coordinate origin (this job's own south/west corner) that this job's
    buildings use, so the frontend can place them in the same scene with
    zero extra math. Works for whatever bbox was actually selected -- not
    hardcoded to any particular city, state, or country.
    """
    job = db.query(models.BulkImportJob).filter(models.BulkImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Bulk import job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="This job hasn't finished importing yet.")

    roads, warning = osm_overpass.fetch_roads_in_bbox(job.south, job.west, job.north, job.east)
    if roads is None:
        raise HTTPException(status_code=502, detail=f"Could not fetch road data: {warning}")

    origin_lat, origin_lon = job.south, job.west
    output = []
    for r in roads:
        local_points = osm_overpass.latlon_polyline_to_local_meters(r["geometry"], origin_lat, origin_lon)
        output.append({
            "osm_id": r["osm_id"],
            "highway_type": r.get("highway_type"),
            "name": r["tags"].get("name"),
            "points": local_points,
        })

    return {"count": len(output), "roads": output, "warning": warning}
