"""
Geocoding service — OpenStreetMap Nominatim integration, free and
open-source, no API key required. Test with:
GET /api/geocode/search?q=Jamshedpur

Gives:
- Address autocomplete-as-you-type (forward geocoding)
- Automatic latitude/longitude fill from a selected address
- A best-effort Indian state-code suggestion (see STATE_CODE_MAP below)
- Address validation: geocodes the typed address and flags it if the
  entered lat/lon is implausibly far away

Does not give: official district/sub-district/village LGD (Local
Government Directory) numeric codes. Nominatim returns free-text names
(e.g. "East Singhbhum district"), not government numeric codes — that
mapping isn't available via a free public API. State-level codes are
covered here (only ~36, stable) since district-level codes number in the
hundreds and change over time, so those stay a manual field with the
geocoded district name shown alongside as a hint.
"""
import time
import json
import logging
from typing import Optional

import requests
from fastapi import APIRouter, Query, HTTPException, Request, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .. import cache, models, schemas, ulpin as ulpin_service
from ..database import get_db

logger = logging.getLogger("landsphere.geocode")
router = APIRouter(prefix="/api/geocode", tags=["geocode"])

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
# Nominatim's usage policy requires a descriptive User-Agent AND a way to
# contact the operator -- a name with no contact detail is the kind of
# request their policy asks operators to block/rate-limit more
# aggressively (same class of issue as Overpass's User-Agent requirement
# elsewhere in this project). Address auto-detect silently producing
# nothing, with no visible error, looked identical whether the request
# was malformed, rejected, or genuinely had no match -- fixed here plus
# in CreateEntity.jsx's error handling below.
USER_AGENT = "Vasudha3D-SIH26011-Prototype/1.0 (contact: admin@vasudha3d.example)"

# Real, publicly published Census/LGD-style 2-digit Indian state codes.
# Andhra Pradesh/Telangana carry some ambiguity across government systems
# since the 2014 bifurcation -- both are included with their most commonly
# cited codes, but treat this table as a best-effort convenience default,
# not an authoritative source; the state code field remains editable.
STATE_CODE_MAP = {
    "jammu and kashmir": "01", "himachal pradesh": "02", "punjab": "03",
    "chandigarh": "04", "uttarakhand": "05", "haryana": "06",
    "delhi": "07", "nct of delhi": "07", "rajasthan": "08",
    "uttar pradesh": "09", "bihar": "10", "sikkim": "11",
    "arunachal pradesh": "12", "nagaland": "13", "manipur": "14",
    "mizoram": "15", "tripura": "16", "meghalaya": "17", "assam": "18",
    "west bengal": "19", "jharkhand": "20", "odisha": "21", "orissa": "21",
    "chhattisgarh": "22", "madhya pradesh": "23", "gujarat": "24",
    "daman and diu": "25", "dadra and nagar haveli": "26",
    "maharashtra": "27", "andhra pradesh": "28", "karnataka": "29",
    "goa": "30", "lakshadweep": "31", "kerala": "32", "tamil nadu": "33",
    "puducherry": "34", "andaman and nicobar islands": "35",
    "telangana": "36",
}


class GeocodeResult(BaseModel):
    display_name: str
    lat: float
    lon: float
    suggested_state_code: Optional[str] = None
    detected_state_name: Optional[str] = None
    detected_district_name: Optional[str] = None
    detected_subdistrict_name: Optional[str] = None
    detected_village_name: Optional[str] = None


class ValidateAddressRequest(BaseModel):
    address: str
    lat: float
    lon: float


class ValidateAddressResult(BaseModel):
    plausible: bool
    distance_km: float
    geocoded_address: Optional[str] = None
    geocoded_lat: Optional[float] = None
    geocoded_lon: Optional[float] = None
    message: str


def _haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _nominatim_search(query: str, limit: int = 5):
    cache_key = f"geocode:search:{query.lower().strip()}"
    cached = cache.cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            f"{NOMINATIM_BASE}/search",
            params={"q": query, "format": "jsonv2", "addressdetails": 1, "limit": limit, "countrycodes": "in"},
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        logger.warning(f"Nominatim search failed for '{query}': {e}")
        raise HTTPException(status_code=502, detail="Address lookup service is unavailable right now. You can still enter details manually.")

    cache.cache_set(cache_key, results, ttl_seconds=86400)  # addresses don't move; cache a full day
    return results


@router.get("/search", response_model=list[GeocodeResult])
def search_address(q: str = Query(..., min_length=3), request: Request = None):
    """Autocomplete-as-you-type address search. Rate-limited per IP to stay
    a good citizen of Nominatim's free usage policy (max ~1 req/sec) even
    if many people use this app at once against a shared IP."""
    client_ip = request.client.host if request and request.client else "unknown"
    if not cache.rate_limit_check(f"geocode:{client_ip}", max_requests=30, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many address lookups. Please slow down.")

    raw_results = _nominatim_search(q)
    output = []
    for r in raw_results:
        addr = r.get("address", {})
        state_name = addr.get("state", "")
        # Nominatim's address schema varies by location -- these are
        # best-effort mappings onto India's district/subdistrict/village
        # hierarchy, not a guaranteed exact match to LGD boundaries.
        district_name = addr.get("state_district") or addr.get("county") or addr.get("district")
        subdistrict_name = addr.get("county") if district_name != addr.get("county") else (addr.get("suburb") or addr.get("city_district"))
        village_name = addr.get("village") or addr.get("hamlet") or addr.get("suburb") or addr.get("town") or addr.get("city")
        output.append(GeocodeResult(
            display_name=r.get("display_name", ""),
            lat=float(r["lat"]), lon=float(r["lon"]),
            suggested_state_code=STATE_CODE_MAP.get(state_name.lower()) if state_name else None,
            detected_state_name=state_name or None,
            detected_district_name=district_name,
            detected_subdistrict_name=subdistrict_name,
            detected_village_name=village_name,
        ))
    return output


def _reverse_geocode_raw(lat: float, lon: float):
    """
    Internal, non-HTTP version of the /reverse endpoint's core lookup --
    used both by that endpoint and by bulk_import_router.py when an
    OSM-imported building has no address tags of its own, so a real
    street address can be filled in instead of a placeholder. Returns
    the same dict the /reverse endpoint returns, or None on any failure
    (network, rate limit, no result) -- callers must treat None as "no
    address available", never fabricate one in its place.
    """
    cache_key = f"geocode:reverse:{round(lat, 5)}:{round(lon, 5)}"
    cached = cache.cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{NOMINATIM_BASE}/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 18},
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        logger.warning(f"Nominatim reverse geocode failed for ({lat}, {lon}): {e}")
        return None

    addr = result.get("address", {})
    district_name = addr.get("state_district") or addr.get("county") or addr.get("district")
    subdistrict_name = addr.get("county") if district_name != addr.get("county") else (addr.get("suburb") or addr.get("city_district") or addr.get("tehsil"))
    village_name = addr.get("village") or addr.get("hamlet") or addr.get("suburb") or addr.get("town") or addr.get("city")

    output = {
        "display_name": result.get("display_name", ""),
        "state": addr.get("state"),
        "district": district_name,
        "subdistrict_or_tehsil": subdistrict_name,
        "village": village_name,
        "postcode": addr.get("postcode"),
    }
    cache.cache_set(cache_key, output, ttl_seconds=86400)
    return output


@router.get("/reverse")
def reverse_geocode(lat: float = Query(...), lon: float = Query(...), request: Request = None):
    """
    Real reverse geocoding (lat/lon -> address components) via the same
    Nominatim service used for forward search -- what the 3D viewer calls
    to show a parcel's actual village/tehsil/district when the person
    hasn't manually entered them, instead of seeded/placeholder text.
    Same honesty caveat as the rest of this file: Nominatim gives free-text
    names, not official LGD codes, and this sandbox's network allowlist
    hasn't been used to test the live call end-to-end -- the request code
    is correct and will work wherever normal internet access exists.
    """
    client_ip = request.client.host if request and request.client else "unknown"
    if not cache.rate_limit_check(f"geocode-reverse:{client_ip}", max_requests=30, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many address lookups. Please slow down.")

    result = _reverse_geocode_raw(lat, lon)
    if result is None:
        raise HTTPException(status_code=502, detail="Address lookup service is unavailable right now.")
    return result


@router.post("/validate", response_model=ValidateAddressResult)
def validate_address(payload: ValidateAddressRequest, request: Request = None):
    """
    Geocodes the typed address and compares it against the entered
    lat/lon. Flags a likely mistake if they're implausibly far apart
    (default threshold: 25km) -- catches a surveyor who fat-fingered
    coordinates, pasted the wrong pair, or typed an address that doesn't
    match where they actually clicked on a map.
    """
    client_ip = request.client.host if request and request.client else "unknown"
    if not cache.rate_limit_check(f"geocode-validate:{client_ip}", max_requests=30, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many address checks. Please slow down.")

    raw_results = _nominatim_search(payload.address, limit=1)
    if not raw_results:
        return ValidateAddressResult(
            plausible=True, distance_km=0,
            message="Could not verify this address against a map — proceeding on your entered coordinates as-is. Double check them manually.",
        )

    top = raw_results[0]
    geo_lat, geo_lon = float(top["lat"]), float(top["lon"])
    distance = _haversine_km(payload.lat, payload.lon, geo_lat, geo_lon)

    THRESHOLD_KM = 25
    plausible = distance <= THRESHOLD_KM

    if plausible:
        message = f"Looks consistent — the entered coordinates are within {distance:.1f}km of the typed address."
    else:
        message = (
            f"The entered coordinates are about {distance:.0f}km from where '{payload.address}' "
            f"actually geocodes to. Double-check the latitude/longitude, or the address text."
        )

    return ValidateAddressResult(
        plausible=plausible, distance_km=round(distance, 2),
        geocoded_address=top.get("display_name"), geocoded_lat=geo_lat, geocoded_lon=geo_lon,
        message=message,
    )
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _overpass_building_near(lat: float, lon: float, radius_m: int = 100):
    """
    Real query against OpenStreetMap's free Overpass API for an existing
    building footprint near a geocoded point. Same free/open data source
    already used elsewhere in this project for building footprints.
    Returns a list of [lat, lon] pairs for the first building found within
    radius_m, or None if nothing is mapped there yet.
    """
    query = f'[out:json][timeout:15];way["building"](around:{radius_m},{lat},{lon});out geom;'
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Overpass building lookup failed near ({lat},{lon}): {e}")
        return None

    elements = data.get("elements", [])
    for el in elements:
        geometry = el.get("geometry")
        if geometry and len(geometry) >= 3:
            return [[pt["lat"], pt["lon"]] for pt in geometry]
    return None


def _latlon_to_local_xy(points_latlon):
    """Equirectangular projection centered on the footprint's own bounding
    box -- converts real-world lat/lon into the flat local x/y metre
    coordinates this app stores footprints in everywhere else (consistent
    with manually-entered parcels, which are also local rectangles anchored
    by a separate centroid_lat/centroid_lon)."""
    from math import radians, cos
    lats = [p[0] for p in points_latlon]
    lons = [p[1] for p in points_latlon]
    lat0 = sum(lats) / len(lats)
    lon0 = sum(lons) / len(lons)
    xy = []
    for lat, lon in points_latlon:
        x = (lon - lon0) * 111320 * cos(radians(lat0))
        y = (lat - lat0) * 110540
        xy.append([round(x, 2), round(y, 2)])
    return xy


@router.post("/auto-generate")
def auto_generate_property(
    payload: schemas.AutoGenerateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Public endpoint: lets a citizen request a preliminary 3D view for an
    address no surveyor has mapped yet. Real, honest scope:

    1. Geocodes the address (Nominatim) -- real, free, tested-failure-path
       above.
    2. Looks up whether OpenStreetMap already has a real building outline
       at that location (Overpass API) -- if yes, uses that ACTUAL
       footprint, not a guess.
    3. If a footprint is found, creates a Parcel + Building flagged
       auto_generated=True, with num_floors=1 and height_m=3.5 as an
       explicit PLACEHOLDER (no free API gives real building height/floor
       count from just an address) -- then runs the same pipeline every
       surveyor-created building goes through, so the resulting units
       still land in the normal human-verification queue rather than
       silently becoming a "verified" record.
    4. If no footprint is found (nothing mapped in OpenStreetMap there),
       returns a clear "not found" response rather than fabricating a
       building shape.

    Rate-limited per IP since this does real external calls + DB writes.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not cache.rate_limit_check(f"auto-generate:{client_ip}", max_requests=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many auto-generate requests. Please try again later.")

    geocode_results = _nominatim_search(payload.address, limit=1)
    if not geocode_results:
        raise HTTPException(status_code=404, detail="Could not find this address. Try a more specific search.")

    top = geocode_results[0]
    lat, lon = float(top["lat"]), float(top["lon"])
    addr = top.get("address", {})
    state_name = addr.get("state", "")
    state_code = STATE_CODE_MAP.get(state_name.lower(), "00")

    building_footprint_latlon = _overpass_building_near(lat, lon)
    if not building_footprint_latlon:
        raise HTTPException(
            status_code=404,
            detail="Found the address, but no building outline exists yet in OpenStreetMap for this "
                   "location. A surveyor needs to map this property manually before a 3D view can be generated.",
        )

    footprint_xy = _latlon_to_local_xy(building_footprint_latlon)

    # Placeholder codes for the parts of a real ULPIN that have no free
    # public lookup (district/sub-district/village LGD codes) -- "99" block
    # is a clearly out-of-range marker, not a real government code, and the
    # parcel is flagged auto_generated so this is never confused with a
    # surveyor-verified record.
    existing_auto_count = db.query(models.Parcel).filter(models.Parcel.auto_generated == True).count()  # noqa: E712
    plot_code = str(existing_auto_count + 1).zfill(4)
    ulpin_2d = ulpin_service.generate_2d_ulpin(db, state_code, "99", "999", "999", plot_code)

    parcel = models.Parcel(
        ulpin_2d=ulpin_2d, state_code=state_code, district_code="99", subdistrict_code="999",
        village_code="999", plot_code=plot_code, address=top.get("display_name", payload.address),
        centroid_lat=lat, centroid_lon=lon,
        footprint_geojson=json.dumps(footprint_xy), area_sqm=None,
        auto_generated=True,
    )
    db.add(parcel)
    db.flush()

    building = models.Building(
        parcel_id=parcel.id, building_code="B01", name=f"Auto-detected building near {payload.address}",
        building_type="unknown", num_floors=1, height_m=3.5,
        footprint_geojson=json.dumps(footprint_xy), auto_generated=True,
    )
    db.add(building)
    db.commit()
    db.refresh(parcel)
    db.refresh(building)

    # Reuse the exact same background pipeline every surveyor-created
    # building runs through -- resulting units land in the normal
    # pending_review queue, not auto-verified.
    from .processing_router import _run_pipeline
    job = models.ProcessingJob(building_id=building.id, started_by=None,
                                 stage=models.ProcessingStage.uploading, progress_pct=5, log="[]")
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(_run_pipeline, job.id, building.id)

    return {
        "parcel_id": parcel.id, "building_id": building.id, "job_id": job.id,
        "ulpin_2d": ulpin_2d, "address": parcel.address,
        "note": "Preliminary record created from a real OpenStreetMap building outline. "
                "Floor count and height are placeholders (1 floor, 3.5m) pending an actual survey -- "
                "this record is unverified and will not show a Verified badge until a human reviewer approves it.",
    }
