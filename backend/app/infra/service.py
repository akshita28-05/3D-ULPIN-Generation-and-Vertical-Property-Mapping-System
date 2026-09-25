"""Scan a map area for underground structures / air-right corridors, remember the
result, and attach it to the registered parcels it crosses.

    scan_bbox()        grid cells (~2 km) -> Overpass (cached on disk + in the DB) -> InfraFeature rows
    features_in_bbox() what the map layers draw
    link_to_parcels()  where a feature crosses a registered parcel, write the regular
                       UndergroundAsset / AirRightCorridor rows (source="osm_auto") so the
                       per-parcel 3D viewer and the rights registry show it too
    scan_and_link()    both, used by the one-click "Auto-map this view" job

No sensor, no upload, no form. If Overpass is unreachable the scan says so and the
map keeps working; a cell already fetched once keeps working offline (disk cache).
"""
import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta

from shapely.geometry import shape, Polygon, box as shp_box, mapping
from shapely.ops import transform as shp_transform
from shapely.strtree import STRtree

from .. import models, cache
from ..georef import OriginResolver, parse_points, M_PER_DEG_LAT, _m_per_deg_lon
from ..ingestion import osm_overpass
from ..ai.corridors import conflicts as corridor_conflicts
from . import osm_infra

logger = logging.getLogger("landsphere.infra")

CELL_DEG = 0.02
MAX_SCAN_CELLS = int(os.getenv("INFRA_MAX_SCAN_CELLS", "9"))
SCAN_BUDGET_S = float(os.getenv("INFRA_SCAN_BUDGET_S", "50"))
CELL_DELAY_S = float(os.getenv("INFRA_CELL_DELAY_S", "1.0"))
RETRY_FAILED_AFTER_S = 120
CACHE_DIR = os.getenv("INFRA_CACHE_DIR", "./infra_cache")
CACHE_MAX_AGE_DAYS = int(os.getenv("INFRA_CACHE_MAX_AGE_DAYS", "30"))

AUTO_SOURCE = "osm_auto"
_scan_lock = threading.Lock()

ASSET_TYPE = {"metro_tunnel": "metro_tunnel", "rail_tunnel": "metro_tunnel", "power_cable": "electricity",
              "storm_drain": "sewer", "pipeline": "other"}



def cells_for_bbox(south, west, north, east):
    i0, i1 = int(math.floor(south / CELL_DEG)), int(math.floor(north / CELL_DEG))
    j0, j1 = int(math.floor(west / CELL_DEG)), int(math.floor(east / CELL_DEG))
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


def cell_key(i, j):
    return f"{i}:{j}"


def cell_bounds(i, j):
    return i * CELL_DEG, j * CELL_DEG, (i + 1) * CELL_DEG, (j + 1) * CELL_DEG



def _cache_path(key):
    return os.path.join(CACHE_DIR, f"cell_{key.replace(':', '_')}.json")


def _read_cache(key, allow_stale):
    path = _cache_path(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        fetched = datetime.fromisoformat(blob["fetched_at"])
        if allow_stale or datetime.utcnow() - fetched <= timedelta(days=CACHE_MAX_AGE_DAYS):
            return blob["elements"]
    except Exception:
        logger.warning("Ignoring unreadable infra cache file %s", path)
    return None


def _write_cache(key, elements):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": datetime.utcnow().isoformat(), "elements": elements}, fh)
    except OSError:
        logger.warning("Could not write infra cache for cell %s", key)


def fetch_cell_elements(key, bounds):
    """(elements, error, from_cache). Fresh disk cache -> live Overpass -> stale disk cache."""
    cached = _read_cache(key, allow_stale=False)
    if cached is not None:
        return cached, None, True
    if os.getenv("INFRA_OFFLINE", "false").lower() in ("1", "true", "yes"):
        return None, "offline mode (INFRA_OFFLINE=true) and this area has not been cached yet", False
    query = osm_infra.build_query(*bounds)
    data, error = osm_overpass._race_overpass_query(query)
    if data is not None:
        elements = data.get("elements", [])
        _write_cache(key, elements)
        return elements, None, False
    stale = _read_cache(key, allow_stale=True)
    if stale is not None:
        return stale, None, True
    return None, error, False



def _scan_one_cell(db, i, j):
    key = cell_key(i, j)
    bounds = cell_bounds(i, j)
    elements, error, from_cache = fetch_cell_elements(key, bounds)
    row = db.query(models.InfraScanCell).filter(models.InfraScanCell.cell_key == key).first()
    if row is None:
        row = models.InfraScanCell(cell_key=key)
        db.add(row)
    if elements is None:
        row.status, row.message, row.n_features, row.scanned_at = "failed", (error or "unknown error")[:480], 0, datetime.utcnow()
        db.commit()
        return {"status": "failed", "error": error, "added": 0}

    features = osm_infra.classify_elements(elements, origin=(bounds[0], bounds[1]))
    ids = [f["osm_id"] for f in features]
    have = set()
    for start in range(0, len(ids), 800):
        have.update(r[0] for r in db.query(models.InfraFeature.osm_id)
                    .filter(models.InfraFeature.osm_id.in_(ids[start:start + 800])).all())
    added = 0
    for f in features:
        if f["osm_id"] in have:
            continue
        s, w, n, e = f["bbox"]
        db.add(models.InfraFeature(
            kind=f["kind"], subtype=f["subtype"], name=f["name"], osm_id=f["osm_id"],
            geometry_geojson=json.dumps(f["geometry"]), width_m=f["width_m"],
            z_min_m=f["z_min_m"], z_max_m=f["z_max_m"], deck_top_m=f["deck_top_m"],
            z_source=f["z_source"], confidence=f["confidence"], source="osm",
            notes=json.dumps(f["notes"]), tags_json=json.dumps(f["tags"]), cell_key=key,
            bbox_south=s, bbox_west=w, bbox_north=n, bbox_east=e,
        ))
        have.add(f["osm_id"])
        added += 1
    row.status, row.message, row.n_features, row.scanned_at = "ok", ("from local cache" if from_cache else None), added, datetime.utcnow()
    db.commit()
    return {"status": "ok", "added": added, "from_cache": from_cache}


def scan_bbox(db, south, west, north, east):
    """Scan every not-yet-scanned grid cell under the view. Never raises."""
    cells = cells_for_bbox(south, west, north, east)
    if len(cells) > MAX_SCAN_CELLS:
        return {"status": "zoom_in", "cells": len(cells), "scanned": 0, "cached": 0, "failed": 0, "added": 0,
                "message": "Zoom in a little to scan this area for underground and elevated structures."}

    known = {r.cell_key: r for r in db.query(models.InfraScanCell)
             .filter(models.InfraScanCell.cell_key.in_([cell_key(i, j) for i, j in cells])).all()}
    now = datetime.utcnow()
    todo, recent_failed = [], []
    for i, j in cells:
        r = known.get(cell_key(i, j))
        if r and r.status == "ok":
            continue
        if r and r.status == "failed" and (now - r.scanned_at).total_seconds() < RETRY_FAILED_AFTER_S:
            recent_failed.append(r)
            continue
        todo.append((i, j))
    summary = {"status": "ok", "cells": len(cells), "scanned": 0, "cached": len(cells) - len(todo) - len(recent_failed),
               "failed": len(recent_failed), "added": 0, "message": None}
    if not todo:
        if recent_failed:
            summary.update(status="unavailable" if summary["cached"] == 0 else "partial",
                           message=(recent_failed[0].message or "Open-data service unreachable.")[:300])
        return summary

    if not _scan_lock.acquire(blocking=False):
        summary.update(status="busy", message="Another scan is running -- results will appear in a moment.")
        return summary
    try:
        started = time.time()
        first_error = None
        for n, (i, j) in enumerate(todo):
            if time.time() - started > SCAN_BUDGET_S:
                summary["status"] = "partial"
                break
            try:
                res = _scan_one_cell(db, i, j)
            except Exception as exc:
                logger.exception("Infra scan failed for cell %s:%s", i, j)
                db.rollback()
                res = {"status": "failed", "error": str(exc), "added": 0}
            if res["status"] == "ok":
                summary["scanned"] += 1
                summary["added"] += res["added"]
            else:
                summary["failed"] += 1
                first_error = first_error or res.get("error")
            if n < len(todo) - 1 and res["status"] == "ok" and not res.get("from_cache"):
                time.sleep(CELL_DELAY_S)
        if summary["failed"] and not summary["scanned"] and not summary["cached"]:
            summary.update(status="unavailable", message=(first_error or "Open-data service unreachable.")[:300])
        elif summary["failed"]:
            summary.update(status="partial", message="Some parts of this area could not be reached; showing what was found.")
    finally:
        _scan_lock.release()
    if summary["added"]:
        cache.cache_invalidate("map:stats")
    return summary



def features_in_bbox(db, south, west, north, east, limit=4000):
    F = models.InfraFeature
    return (db.query(F)
            .filter(F.bbox_south <= north, F.bbox_north >= south, F.bbox_west <= east, F.bbox_east >= west)
            .limit(limit).all())


def feature_to_geojson(f):
    air = f.kind == "air"
    try:
        notes = json.loads(f.notes) if f.notes else []
    except ValueError:
        notes = []
    props = {
        "id": f.id, "kind": f.kind, "subtype": f.subtype, "label": osm_infra.label_for(f.kind, f.subtype),
        "name": f.name, "osm_id": f.osm_id, "width_m": f.width_m,
        "z_min_m": f.z_min_m, "z_max_m": f.z_max_m, "deck_top_m": f.deck_top_m,
        "z_source": f.z_source, "confidence": f.confidence,
        "evidence": "OBSERVED" if f.z_source == "osm_tag" else "PREDICTED",
        "notes": notes,
        "lon": (f.bbox_west + f.bbox_east) / 2.0, "lat": (f.bbox_south + f.bbox_north) / 2.0,
        "base": (f.z_min_m or 0.0) if air else 0.0,
        "top": (f.z_max_m or 0.0) if air else 0.0,
        "deck_base": (f.z_min_m or 0.0) if air else 0.0,
        "deck_top": (f.deck_top_m or 0.0) if air else 0.0,
        "depth_min": (f.z_min_m or 0.0) if not air else 0.0,
        "depth_max": (f.z_max_m or 0.0) if not air else 0.0,
        "display_width": max(f.width_m or 0.0, osm_infra.DISPLAY_MIN_WIDTH_M) if not air else None,
    }
    return {"type": "Feature", "properties": props, "geometry": json.loads(f.geometry_geojson)}



def _to_local(geom, origin):
    olat, olon = origin
    m_lon = _m_per_deg_lon(olat)
    return shp_transform(lambda x, y, z=None: ((x - olon) * m_lon, (y - olat) * M_PER_DEG_LAT), geom)


def _ring_points(poly):
    return [[round(float(x), 3), round(float(y), 3)] for x, y in list(poly.exterior.coords)[:-1]]


def link_to_parcels(db, south, west, north, east, job_id=None):
    """Create the per-parcel UndergroundAsset / AirRightCorridor rows for every stored
    feature that crosses a registered parcel in this box. Re-running replaces the earlier
    osm_auto rows for those parcels (idempotent); anything a person entered is untouched."""
    feats = features_in_bbox(db, south, west, north, east, limit=8000)
    q = db.query(models.Parcel).filter(
        models.Parcel.centroid_lat.between(south, north), models.Parcel.centroid_lon.between(west, east))
    if job_id:
        q = q.filter(models.Parcel.bulk_import_job_id == job_id)
    parcels = q.all()
    counts = {"underground": 0, "air": 0, "parcels": 0, "conflicts": 0}
    if not parcels:
        return counts

    pids = [p.id for p in parcels]
    for start in range(0, len(pids), 800):
        chunk = pids[start:start + 800]
        db.query(models.UndergroundAsset).filter(
            models.UndergroundAsset.parcel_id.in_(chunk), models.UndergroundAsset.source == AUTO_SOURCE
        ).delete(synchronize_session=False)
        db.query(models.AirRightCorridor).filter(
            models.AirRightCorridor.parcel_id.in_(chunk), models.AirRightCorridor.source == AUTO_SOURCE
        ).delete(synchronize_session=False)
    db.flush()
    if not feats:
        db.commit()
        return counts

    geoms = [shape(json.loads(f.geometry_geojson)) for f in feats]
    tree = STRtree(geoms)
    resolver = OriginResolver(db)
    buildings_by_parcel = {}
    for b in db.query(models.Building).filter(models.Building.parcel_id.in_(pids[:5000])).all():
        buildings_by_parcel.setdefault(b.parcel_id, []).append(b)
    local_cache = {}
    touched = set()

    for parcel in parcels:
        fp = parse_points(parcel.footprint_geojson)
        origin = resolver.origin_for(parcel, fp)
        if origin is None or len(fp) < 3:
            continue
        ring_ll = resolver.ring_latlon(parcel, fp)
        try:
            parcel_ll = Polygon([(lon, lat) for lat, lon in ring_ll])
            if not parcel_ll.is_valid:
                parcel_ll = parcel_ll.buffer(0)
            parcel_local = Polygon(fp)
            if not parcel_local.is_valid:
                parcel_local = parcel_local.buffer(0)
        except Exception:
            continue
        hits = tree.query(parcel_ll.buffer(2.0 / M_PER_DEG_LAT), predicate="intersects")
        if len(hits) == 0:
            continue
        blds = [{"id": b.building_code, "footprint": parse_points(b.footprint_geojson), "height_m": b.height_m}
                for b in buildings_by_parcel.get(parcel.id, []) if b.footprint_geojson]

        for idx in hits:
            f = feats[int(idx)]
            ck = (origin, int(idx))
            local = local_cache.get(ck)
            if local is None:
                local = _to_local(geoms[int(idx)], origin)
                if local.geom_type == "LineString":
                    local = local.buffer(max(f.width_m or 1.0, 0.5) / 2.0, cap_style="flat", join_style="mitre")
                local_cache[ck] = local
            piece = local.intersection(parcel_local)
            if piece.is_empty:
                continue
            parts = [g for g in getattr(piece, "geoms", [piece]) if g.geom_type == "Polygon" and g.area >= 0.5]
            for part in parts:
                pts = _ring_points(part)
                if len(pts) < 3:
                    continue
                try:
                    notes = json.loads(f.notes) if f.notes else []
                except ValueError:
                    notes = []
                notes = notes + [f"osm:{f.osm_id}"]
                if f.kind == "air":
                    status, why = corridor_conflicts.assess(
                        pts + [pts[0]], 0.0 if f.subtype == "power_line" else (f.z_min_m or 0.0), f.z_max_m or 0.0, blds)
                    db.add(models.AirRightCorridor(
                        parcel_id=parcel.id, corridor_type=f.subtype, height_min_m=f.z_min_m, height_max_m=f.z_max_m,
                        geometry_geojson=json.dumps(pts), conflict_status=status, source=AUTO_SOURCE,
                        detection_confidence=f.confidence, height_source=f.z_source,
                        detection_notes=json.dumps(notes + why),
                    ))
                    counts["air"] += 1
                    counts["conflicts"] += 1 if status != "none" else 0
                else:
                    db.add(models.UndergroundAsset(
                        parcel_id=parcel.id, asset_type=_asset_type(f), depth_min_m=f.z_min_m, depth_max_m=f.z_max_m,
                        geometry_geojson=json.dumps(pts), source=AUTO_SOURCE,
                        quality_level=models.UtilityQualityLevel.QL_D,
                        detection_confidence=f.confidence,
                    ))
                    counts["underground"] += 1
                touched.add(parcel.id)
    db.commit()
    counts["parcels"] = len(touched)
    return counts


def _asset_type(f):
    if f.subtype == "pipeline":
        try:
            sub = (json.loads(f.tags_json or "{}")).get("substance")
        except ValueError:
            sub = None
        return {"water": "water", "gas": "gas", "sewage": "sewer"}.get(sub, "other")
    return ASSET_TYPE.get(f.subtype, f.subtype)


def scan_and_link(db, south, west, north, east, job_id=None):
    scan = scan_bbox(db, south, west, north, east)
    linked = link_to_parcels(db, south, west, north, east, job_id=job_id)
    return {"scan": scan, "linked": linked}


def counts_for_job(db, job):
    """Live numbers for the auto-map result card."""
    F = models.InfraFeature
    q = db.query(F).filter(F.bbox_south <= job.north, F.bbox_north >= job.south,
                           F.bbox_west <= job.east, F.bbox_east >= job.west)
    ug = q.filter(F.kind == "underground").count()
    air = q.filter(F.kind == "air").count()
    P = models.Parcel
    linked_ug = (db.query(models.UndergroundAsset).join(P, P.id == models.UndergroundAsset.parcel_id)
                 .filter(P.bulk_import_job_id == job.id, models.UndergroundAsset.source == AUTO_SOURCE).count())
    linked_air = (db.query(models.AirRightCorridor).join(P, P.id == models.AirRightCorridor.parcel_id)
                  .filter(P.bulk_import_job_id == job.id, models.AirRightCorridor.source == AUTO_SOURCE).count())
    return {"underground": ug, "air": air, "linked_underground": linked_ug, "linked_air": linked_air}




DISPLAY_MIN_LINE_M = 1.5
MAX_PARCEL_FEATURES = 60


def _rings_of(geom, min_area=0.5, max_parts=4):
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and g.area >= min_area]
    parts.sort(key=lambda g: g.area, reverse=True)
    return [_ring_points(g) for g in parts[:max_parts]]


def _lines_of(geom, max_parts=4):
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "LineString" and g.length > 0.5]
    parts.sort(key=lambda g: g.length, reverse=True)
    return [[[round(float(x), 3), round(float(y), 3)] for x, y in g.coords] for g in parts[:max_parts]]


def parcel_infrastructure(db, parcel, radius_m=120.0, scan=True):
    """Underground structures + air-right corridors around ONE parcel, already in the
    parcel's own local-metre frame (x east, y north -- the same frame its buildings use),
    ready for the 3D viewer. Everything comes from the same InfraFeature store the map
    layer draws; nothing is invented. A feature does not have to cross the parcel: a metro
    running 30 m away is still shown (flagged on_parcel=false, with its distance).
    Depth / height ranges keep their z_source so the viewer can say which are typical
    values rather than measurements."""
    fp = parse_points(parcel.footprint_geojson)
    origin = OriginResolver(db).origin_for(parcel, fp)
    if origin is None or len(fp) < 3:
        return {"available": False, "reason": "This parcel has no map position, so nearby structures cannot be located.",
                "features": [], "counts": {"underground": 0, "air": 0}, "radius_m": radius_m, "scan": None}
    parcel_local = Polygon(fp)
    if not parcel_local.is_valid:
        parcel_local = parcel_local.buffer(0)
    minx, miny, maxx, maxy = parcel_local.bounds
    window = shp_box(minx - radius_m, miny - radius_m, maxx + radius_m, maxy + radius_m)
    olat, olon = origin
    m_lon = _m_per_deg_lon(olat)
    south, north = olat + (miny - radius_m) / M_PER_DEG_LAT, olat + (maxy + radius_m) / M_PER_DEG_LAT
    west, east = olon + (minx - radius_m) / m_lon, olon + (maxx + radius_m) / m_lon

    scan_summary = None
    if scan:
        try:
            scan_summary = scan_bbox(db, south, west, north, east)
        except Exception as exc:
            logger.warning("parcel infra scan failed: %s", exc)
            db.rollback()
            scan_summary = {"status": "unavailable", "message": "Open-data scan could not run."}

    feats = features_in_bbox(db, south, west, north, east, limit=3000)
    buildings = db.query(models.Building).filter(models.Building.parcel_id == parcel.id).all()
    blds = [{"id": b.building_code, "footprint": parse_points(b.footprint_geojson), "height_m": b.height_m}
            for b in buildings if b.footprint_geojson]
    basements = []
    for b in buildings:
        fpb = parse_points(b.footprint_geojson)
        for fl in b.floors:
            if fl.z_min is not None and fl.z_min < 0 and len(fpb) >= 3:
                basements.append((b.building_code, fpb, max(0.0, -min(fl.z_max or 0.0, 0.0)), -fl.z_min))

    out = []
    for f in feats:
        try:
            geom = _to_local(shape(json.loads(f.geometry_geojson)), origin)
        except Exception:
            continue
        air = f.kind == "air"
        centerlines = []
        if geom.geom_type in ("LineString", "MultiLineString"):
            clipped_line = geom.intersection(window)
            if clipped_line.is_empty:
                continue
            centerlines = _lines_of(clipped_line)
            drawn_w = max(f.width_m or 1.0, DISPLAY_MIN_LINE_M)
            poly = clipped_line.buffer(drawn_w / 2.0, cap_style="flat", join_style="mitre")
        else:
            poly = geom.intersection(window) if geom.is_valid else geom.buffer(0).intersection(window)
            drawn_w = f.width_m
        if poly.is_empty:
            continue
        rings = _rings_of(poly)
        if not rings:
            continue
        dist = float(poly.distance(parcel_local))
        on_parcel = dist < 0.01

        status, why = "none", []
        if air:
            pts = rings[0] + [rings[0][0]]
            status, why = corridor_conflicts.assess(
                pts, 0.0 if f.subtype == "power_line" else (f.z_min_m or 0.0), f.z_max_m or 0.0, blds)
        elif basements and f.z_min_m is not None and f.z_max_m is not None:
            for code, fpb, d0, d1 in basements:
                if d0 < f.z_max_m and d1 > f.z_min_m and poly.intersection(Polygon(fpb)).area > 0.5:
                    status = "confirmed"
                    why.append(f"Passes through the basement volume of building {code} ({d0:.1f}-{d1:.1f} m below ground).")
        try:
            notes = json.loads(f.notes) if f.notes else []
        except ValueError:
            notes = []
        try:
            substance = (json.loads(f.tags_json or "{}")).get("substance")
        except ValueError:
            substance = None
        out.append({
            "id": f.id, "kind": f.kind, "substance": substance, "subtype": f.subtype, "label": osm_infra.label_for(f.kind, f.subtype),
            "name": f.name, "osm_id": f.osm_id,
            "polygons": rings, "centerlines": centerlines,
            "width_m": f.width_m, "display_width_m": None if drawn_w is None else round(float(drawn_w), 2),
            "z_min_m": f.z_min_m, "z_max_m": f.z_max_m, "deck_top_m": f.deck_top_m,
            "z_source": f.z_source, "evidence": "OBSERVED" if f.z_source == "osm_tag" else "PREDICTED",
            "confidence": f.confidence, "source": "OpenStreetMap", "notes": notes,
            "on_parcel": on_parcel, "distance_m": round(dist, 1),
            "conflict_status": status, "conflict_reasons": why,
        })
    out.sort(key=lambda r: (not r["on_parcel"], r["distance_m"]))
    out = out[:MAX_PARCEL_FEATURES]
    return {
        "available": True, "radius_m": radius_m, "scan": scan_summary, "features": out,
        "counts": {"underground": sum(1 for r in out if r["kind"] == "underground"),
                   "air": sum(1 for r in out if r["kind"] == "air"),
                   "on_parcel": sum(1 for r in out if r["on_parcel"])},
    }
