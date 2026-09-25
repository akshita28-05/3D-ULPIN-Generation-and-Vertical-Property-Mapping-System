"""
Building height estimation from open satellite elevation data (Copernicus
GLO-30 Digital Surface Model), for buildings that have neither a surveyed
height_m/num_floors (manual entry) nor an uploaded LiDAR point cloud.

This is a THIRD, lower-confidence tier -- consulted only when both of
those are unavailable. Order of trust in this codebase, highest first:
  1. Real LiDAR point cloud (ai/floors/segmenter.py) -- per-building survey
  2. Manually entered / OSM-tagged height_m / num_floors -- a human who
     measured or reported it
  3. THIS MODULE -- a public 30m-resolution satellite DSM, sampled under
     the building's own footprint. Never as good as 1 or 2: a 30m pixel
     can span several buildings in dense areas, and there is no separate
     bare-earth DEM by default (see below), so ground level is itself an
     estimate. Every value this module returns is written with
     floor_source="dem_estimated" wherever it lands in the DB, distinct
     from "manual"/"ml_model"/"unsurveyed", so nothing downstream can
     mistake it for a real survey.

Two ground-level strategies, in order of preference:
  A. True nDSM (DSM - bare-earth DEM) via OpenTopography's SRTM GL1 API,
     if OPENTOPOGRAPHY_API_KEY is configured (free registration required;
     see https://opentopography.org/developers). Higher confidence.
  B. "Annular ring" ground estimate (default, no key needed): sample the
     SAME DSM in a ring just outside the building footprint (~5-15m out)
     and use its median as a stand-in for local ground level. Works
     anywhere Copernicus GLO-30 covers. Assumes the immediate surroundings
     are close to true ground level, which is false in dense high-rise
     canyons -- disclosed via the lower confidence score returned
     alongside the estimate.

Nothing in this file invents a height when the data doesn't support one:
a missing dependency, a missing tile (a small number of countries aren't
yet released in Copernicus GLO-30 Public), too few valid pixels under a
small footprint, or a physically implausible result all return None with
a logged reason -- the caller keeps height_m/num_floors as None, exactly
like today.
"""
import logging
import math
import os
import tempfile

logger = logging.getLogger("landsphere.ai.heights")

DEM_HEIGHT_ESTIMATION_ENABLED = os.getenv("DEM_HEIGHT_ESTIMATION_ENABLED", "true").lower() in ("1", "true", "yes")
OPENTOPOGRAPHY_API_KEY = os.getenv("OPENTOPOGRAPHY_API_KEY", "")
DEM_CACHE_DIR = os.getenv("DEM_CACHE_DIR", os.path.join(tempfile.gettempdir(), "landsphere_dem_cache"))

DEFAULT_FLOOR_HEIGHT_M = 3.0

COPERNICUS_BUCKET = "copernicus-dem-30m"
COPERNICUS_REGION = "eu-central-1"

MIN_FOOTPRINT_AREA_SQM = 40.0


_DEPS_OK = None


def _deps_available():
    global _DEPS_OK
    if _DEPS_OK is not None:
        return _DEPS_OK
    try:
        import boto3
        import rasterio
        import shapely
        _DEPS_OK = True
    except ImportError as exc:
        logger.warning(
            f"DEM height estimation needs boto3+rasterio+shapely "
            f"(pip install -r requirements-dem.txt) -- missing: {exc}. The automated pipeline "
            f"will use neighbour-based prediction instead."
        )
        _DEPS_OK = False
    return _DEPS_OK


def _tile_key_for(lat: float, lon: float) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    lat_i = int(math.floor(abs(lat)))
    lon_i = int(math.floor(abs(lon)))
    name = f"Copernicus_DSM_COG_10_{ns}{lat_i:02d}_00_{ew}{lon_i:03d}_00_DEM"
    return f"{name}/{name}.tif"


def _fetch_copernicus_dsm_tile(lat: float, lon: float):
    """
    Downloads (and caches locally under DEM_CACHE_DIR) the single
    1x1-degree Copernicus GLO-30 DSM tile covering (lat, lon). Returns a
    local file path, or None if the tile doesn't exist (unreleased
    country / open ocean -- GLO-30 has no land tiles there) or the
    download failed for any other reason.
    """
    key = _tile_key_for(lat, lon)
    os.makedirs(DEM_CACHE_DIR, exist_ok=True)
    local_path = os.path.join(DEM_CACHE_DIR, key.split("/")[-1])
    if os.path.isfile(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    try:
        import boto3
        from botocore.client import Config
        from botocore import UNSIGNED
        from botocore.exceptions import ClientError

        s3 = boto3.client("s3", region_name=COPERNICUS_REGION, config=Config(signature_version=UNSIGNED))
        s3.download_file(COPERNICUS_BUCKET, key, local_path)
        return local_path
    except ClientError as exc:
        logger.info(
            f"No Copernicus GLO-30 tile at '{key}' for ({lat},{lon}) -- {exc}. Expected over "
            f"ocean or in the small set of countries GLO-30 Public hasn't released yet."
        )
        if os.path.isfile(local_path):
            os.remove(local_path)
        return None
    except Exception:
        logger.exception(f"Failed to fetch Copernicus GLO-30 tile '{key}' for ({lat},{lon}).")
        if os.path.isfile(local_path):
            os.remove(local_path)
        return None


def _footprint_polygon_latlon(latlon_points):
    from shapely.geometry import Polygon

    coords = [(lon, lat) for (lat, lon) in latlon_points]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    try:
        poly = Polygon(coords)
    except Exception:
        return None
    return poly if poly.is_valid and poly.area > 0 else None


def _sample_polygon_elevation(dsm_path, polygon, percentile: float):
    """Masks the DSM raster to `polygon` (assumed already in the raster's
    own CRS -- true for Copernicus GLO-30's plain EPSG:4326 tiles) and
    returns the given percentile of valid (non-nodata) pixel values, or
    None if no valid pixels fall inside it."""
    import numpy as np
    import rasterio
    from rasterio.mask import mask

    with rasterio.open(dsm_path) as src:
        try:
            out_image, _ = mask(src, [polygon], crop=True, filled=True, nodata=src.nodata)
        except ValueError:
            return None
        data = out_image[0].astype(float)
        nodata = src.nodata
    if nodata is not None:
        data = data[data != nodata]
    data = data[~np.isnan(data)]
    if data.size == 0:
        return None
    return float(np.percentile(data, percentile))


def _opentopography_ground_level(polygon, centroid_lat, centroid_lon):
    """Real bare-earth DEM (SRTM GL1, 30m) from OpenTopography's public
    REST API, for a small bbox around the footprint. Requires a free API
    key (https://opentopography.org/developers) -- returns None (not an
    error) when unavailable, exactly like every other optional tier here."""
    import requests

    minx, miny, maxx, maxy = polygon.bounds
    pad = 0.001
    tmp_path = None
    try:
        resp = requests.get(
            "https://portal.opentopography.org/API/globaldem",
            params={
                "demtype": "SRTMGL1",
                "south": miny - pad, "north": maxy + pad,
                "west": minx - pad, "east": maxx + pad,
                "outputFormat": "GTiff",
                "API_Key": OPENTOPOGRAPHY_API_KEY,
            },
            timeout=20,
        )
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        return _sample_polygon_elevation(tmp_path, polygon, percentile=50)
    except Exception:
        logger.exception(f"OpenTopography DEM fetch failed for bbox around ({centroid_lat},{centroid_lon}).")
        return None
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            os.remove(tmp_path)


def _estimate_ground_level(dsm_path, polygon, centroid_lat, centroid_lon):
    """Tier A: real bare-earth DEM via OpenTopography, if configured.
    Tier B (default): annular-ring estimate from the DSM itself. Returns
    (ground_z, confidence, source_tag) or (None, None, None)."""
    if OPENTOPOGRAPHY_API_KEY:
        dem_ground = _opentopography_ground_level(polygon, centroid_lat, centroid_lon)
        if dem_ground is not None:
            return dem_ground, 0.7, "copernicus_dsm_minus_srtm_dem"
        logger.info("OpenTopography bare-earth DEM lookup failed -- falling back to the DSM annular-ring ground estimate.")

    deg_per_m = 1 / 111320.0
    ring = polygon.buffer(15 * deg_per_m).difference(polygon.buffer(5 * deg_per_m))
    ground_z = _sample_polygon_elevation(dsm_path, ring, percentile=50)
    if ground_z is None:
        logger.warning("DEM height estimation: no valid DSM pixels in the annular ring around the footprint.")
        return None, None, None
    return ground_z, 0.55, "copernicus_dsm_annular_ring"


def estimate_building_height_from_dem(latlon_points, centroid_lat: float, centroid_lon: float):
    """
    Estimates {height_m, num_floors, confidence, source, roof_elevation_m,
    ground_elevation_m} for a building from Copernicus GLO-30 alone, for
    use ONLY when there is no surveyed height_m/num_floors and no LiDAR
    point cloud for this building (see module docstring for the trust
    ordering).

    latlon_points: the building's real-world footprint as [(lat, lon), ...].

    Returns None (never a fabricated number) if: the feature is disabled,
    dependencies are missing, no DSM tile covers this location, the
    footprint is too small to sample reliably, or the computed height
    isn't physically plausible (<= 0 or > 400m -- more likely a sampling
    error than an actual unverifiable skyscraper).
    """
    if not DEM_HEIGHT_ESTIMATION_ENABLED:
        return None
    if not latlon_points or len(latlon_points) < 3:
        return None
    if not _deps_available():
        return None

    polygon = _footprint_polygon_latlon(latlon_points)
    if polygon is None:
        logger.warning("DEM height estimation: building footprint is not a valid polygon -- skipped.")
        return None

    lat_m = 111320.0
    lon_m = 111320.0 * math.cos(math.radians(centroid_lat))
    area_sqm = abs(polygon.area) * lat_m * lon_m
    if area_sqm < MIN_FOOTPRINT_AREA_SQM:
        logger.info(
            f"DEM height estimation: footprint ~{area_sqm:.0f} sqm is smaller than one DSM "
            f"pixel (~900 sqm) -- too unreliable to sample, skipped."
        )
        return None

    dsm_path = _fetch_copernicus_dsm_tile(centroid_lat, centroid_lon)
    if dsm_path is None:
        return None

    roof_z = _sample_polygon_elevation(dsm_path, polygon, percentile=90)
    if roof_z is None:
        logger.warning(f"DEM height estimation: no valid DSM pixels under footprint at ({centroid_lat},{centroid_lon}).")
        return None

    ground_z, confidence, source = _estimate_ground_level(dsm_path, polygon, centroid_lat, centroid_lon)
    if ground_z is None:
        return None

    height_m = round(roof_z - ground_z, 1)
    if height_m <= 0 or height_m > 400:
        logger.warning(
            f"DEM height estimation produced an implausible height ({height_m}m) at "
            f"({centroid_lat},{centroid_lon}) -- discarded rather than stored."
        )
        return None

    num_floors = max(1, round(height_m / DEFAULT_FLOOR_HEIGHT_M))
    return {
        "height_m": height_m,
        "num_floors": num_floors,
        "confidence": confidence,
        "source": source,
        "roof_elevation_m": round(roof_z, 1),
        "ground_elevation_m": round(ground_z, 1),
    }
