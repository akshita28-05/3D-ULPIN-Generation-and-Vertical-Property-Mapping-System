"""
NDVI vegetation-vs-building disambiguation, for footprints the automated
pipeline detected or predicted rather than a human (a surveyor, or OSM's
own `building` tag) confirming -- the same technique the public
sujayghosh13/boundarylens-sih26011 SIH26011 prototype uses (see
SIH26011_Team_Landscape_and_Comparison_Report.pdf, "What these teams have
added that's worth naming").

Why this exists: tree canopy can look enough like a small building to a
footprint model or an area-based floor-count prior that some of what
auto_pipeline.py turns into a "building" is actually dense vegetation. A
real vegetation index over the footprint -- NDVI, from actual Sentinel-2
reflectance, not a guess -- gives a second, independent signal that has
nothing to do with shape: live vegetation reflects strongly in
near-infrared and absorbs red light, so real buildings/pavement/roofing
have NDVI well below what a stand of trees does, regardless of footprint
shape or size.

Data source: Sentinel-2 L2A surface reflectance, queried via the Earth
Search STAC API (Element84, https://earth-search.aws.element84.com/v1) and
read directly from the public `sentinel-cogs` AWS Open Data bucket --
anonymous HTTPS access, no API key, no AWS account, same "real public
satellite data, zero paid registration" posture as
ai/heights/ndsm_estimator.py's Copernicus GLO-30 DEM fetch.

Like every other AI/ML adapter in this codebase, this NEVER auto-rejects
or deletes a building -- it only raises (or fails to raise) an
anomaly_possible_vegetation ValidationResult for a human reviewer to look
at (see auto_pipeline.py's call site and validation.check_vegetation()).
A missing dependency, no cloud-free scene, a footprint too small for a
10m pixel to resolve, or any fetch/read failure all return None with a
logged reason -- nothing here invents an NDVI value.
"""
import logging
import math
import os

logger = logging.getLogger("landsphere.ai.vegetation")

NDVI_CHECK_ENABLED = os.getenv("NDVI_CHECK_ENABLED", "true").lower() in ("1", "true", "yes")

EARTH_SEARCH_URL = os.getenv("EARTH_SEARCH_STAC_URL", "https://earth-search.aws.element84.com/v1/search")
SENTINEL2_COLLECTION = "sentinel-2-l2a"
STAC_SEARCH_TIMEOUT_S = 15
STAC_MAX_CLOUD_COVER_PCT = float(os.getenv("NDVI_MAX_CLOUD_COVER_PCT", "20"))
STAC_LOOKBACK_DAYS = int(os.getenv("NDVI_SCENE_LOOKBACK_DAYS", "365"))

MIN_FOOTPRINT_AREA_SQM = float(os.getenv("NDVI_MIN_FOOTPRINT_AREA_SQM", "100"))
MIN_VALID_PIXELS = 3

VEGETATION_NDVI_THRESHOLD = float(os.getenv("NDVI_VEGETATION_THRESHOLD", "0.45"))


_DEPS_OK = None


def _deps_available():
    global _DEPS_OK
    if _DEPS_OK is not None:
        return _DEPS_OK
    try:
        import rasterio
        import numpy
        import requests
        import shapely
        _DEPS_OK = True
    except ImportError as exc:
        logger.warning(
            f"NDVI vegetation check needs rasterio+numpy+shapely "
            f"(pip install -r requirements-dem.txt) -- missing: {exc}. Auto-detected footprints "
            f"will not get a vegetation-plausibility check."
        )
        _DEPS_OK = False
    return _DEPS_OK


def _bbox_of(latlon_ring):
    lats = [p[0] for p in latlon_ring]
    lons = [p[1] for p in latlon_ring]
    return min(lons), min(lats), max(lons), max(lats)


def _find_scene(bbox):
    """
    Searches Earth Search for the least-cloudy Sentinel-2 L2A scene over
    bbox in the last STAC_LOOKBACK_DAYS days. Returns the STAC item dict,
    or None if the search failed or nothing usable was found (e.g. no
    scene under STAC_MAX_CLOUD_COVER_PCT cloud cover in the window).
    """
    import requests
    from datetime import datetime, timedelta, timezone

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=STAC_LOOKBACK_DAYS)
    body = {
        "collections": [SENTINEL2_COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "query": {"eo:cloud_cover": {"lt": STAC_MAX_CLOUD_COVER_PCT}},
        "sortby": [{"field": "eo:cloud_cover", "direction": "asc"}],
        "limit": 1,
    }
    try:
        resp = requests.post(EARTH_SEARCH_URL, json=body, timeout=STAC_SEARCH_TIMEOUT_S)
        resp.raise_for_status()
        features = resp.json().get("features") or []
    except Exception:
        logger.exception(f"Sentinel-2 STAC search failed for bbox={bbox}.")
        return None
    if not features:
        logger.info(
            f"No Sentinel-2 L2A scene under {STAC_MAX_CLOUD_COVER_PCT}% cloud cover for bbox={bbox} "
            f"in the last {STAC_LOOKBACK_DAYS} days -- skipping NDVI check for this footprint."
        )
        return None
    return features[0]


def _sample_ndvi(item, latlon_ring):
    """
    Opens the scene's real red (B04) and NIR (B08) COG assets directly
    (anonymous HTTPS, no download/caching needed -- rasterio windowed
    reads only pull the small region covering the footprint) and returns
    the mean NDVI over pixels actually inside the footprint polygon (not
    just its bounding box). Returns (ndvi_mean, valid_pixel_count) or
    (None, 0) on any failure -- a missing asset, a read error, or the
    window landing entirely outside the tile (e.g. footprint at a UTM
    zone boundary).
    """
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.features import geometry_mask
    from shapely.geometry import Polygon

    assets = item.get("assets", {})
    red_href = (assets.get("red") or assets.get("B04") or {}).get("href")
    nir_href = (assets.get("nir") or assets.get("B08") or {}).get("href")
    if not red_href or not nir_href:
        logger.warning(f"Sentinel-2 item {item.get('id')} is missing a red/nir asset href -- cannot compute NDVI.")
        return None, 0

    try:
        with rasterio.open(f"/vsicurl/{red_href}") as red_ds, rasterio.open(f"/vsicurl/{nir_href}") as nir_ds:
            poly_lonlat = Polygon([(lon, lat) for lat, lon in latlon_ring])
            west, south, east, north = transform_bounds("EPSG:4326", red_ds.crs, *poly_lonlat.bounds)
            window = rasterio.windows.from_bounds(west, south, east, north, transform=red_ds.transform)
            window = window.round_offsets().round_lengths()
            if window.width < 1 or window.height < 1:
                logger.info(f"Sentinel-2 window for item {item.get('id')} degenerated to zero pixels -- skipping.")
                return None, 0

            red = red_ds.read(1, window=window).astype("float32")
            nir = nir_ds.read(1, window=window).astype("float32")
            win_transform = red_ds.window_transform(window)

            from rasterio.warp import transform_geom
            poly_native = transform_geom("EPSG:4326", red_ds.crs, poly_lonlat.__geo_interface__)
            mask = geometry_mask([poly_native], out_shape=red.shape, transform=win_transform, invert=True)

        denom = red + nir
        valid = mask & (denom > 0) & np.isfinite(red) & np.isfinite(nir)
        n_valid = int(valid.sum())
        if n_valid < MIN_VALID_PIXELS:
            return None, n_valid
        ndvi = (nir[valid] - red[valid]) / denom[valid]
        return float(np.mean(ndvi)), n_valid
    except Exception:
        logger.exception(f"Failed to read/compute NDVI from Sentinel-2 item {item.get('id')}.")
        return None, 0


def check_vegetation_ndvi(latlon_ring, footprint_area_sqm):
    """
    Public entry point. latlon_ring: closed [[lat, lon], ...] ring (same
    convention as georef.OriginResolver.ring_latlon()). Returns:

      {"ndvi_mean": float, "likely_vegetation": bool, "confidence": float,
       "scene_date": str, "cloud_cover_pct": float,
       "source": "Sentinel-2 L2A (Earth Search, AWS Open Data)"}

    or None if the check could not run at all (disabled, missing deps, no
    usable scene, footprint too small, or a read failure) -- callers must
    treat None as "no signal either way", never as "not vegetation".
    """
    if not NDVI_CHECK_ENABLED:
        return None
    if not latlon_ring or len(latlon_ring) < 3:
        return None
    if not footprint_area_sqm or footprint_area_sqm < MIN_FOOTPRINT_AREA_SQM:
        return None
    if not _deps_available():
        return None

    bbox = _bbox_of(latlon_ring)
    item = _find_scene(bbox)
    if item is None:
        return None

    ndvi_mean, n_valid = _sample_ndvi(item, latlon_ring)
    if ndvi_mean is None:
        return None

    cloud_cover = float(item.get("properties", {}).get("eo:cloud_cover", 0.0))
    scene_date = item.get("properties", {}).get("datetime", "")
    pixel_conf = min(1.0, n_valid / 20.0)
    cloud_conf = max(0.0, 1.0 - cloud_cover / 100.0)
    confidence = round(0.5 * pixel_conf + 0.5 * cloud_conf, 2)

    return {
        "ndvi_mean": round(ndvi_mean, 3),
        "likely_vegetation": ndvi_mean >= VEGETATION_NDVI_THRESHOLD,
        "confidence": confidence,
        "scene_date": scene_date,
        "cloud_cover_pct": cloud_cover,
        "valid_pixels": n_valid,
        "source": "Sentinel-2 L2A (Earth Search, AWS Open Data)",
    }
