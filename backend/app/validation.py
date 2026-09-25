"""
Topology validation service.

Real spatial checks using Shapely (the same geometry engine PostGIS uses
under the hood). Each check returns a list of ValidationResult-shaped
dicts, which the caller persists to the database.
"""
import json
from typing import List, Dict, Optional
from shapely.geometry import shape, Polygon


def _safe_polygon(geojson_str: Optional[str]) -> Optional[Polygon]:
    if not geojson_str:
        return None
    try:
        geom = json.loads(geojson_str)
        if isinstance(geom, dict) and "coordinates" in geom:
            return shape(geom)
        if isinstance(geom, list):
            return Polygon(geom)
    except Exception:
        return None
    return None


def check_containment(child_geojson: str, parent_geojson: str, child_label: str, parent_label: str) -> List[Dict]:
    """Flags if a child geometry (e.g. building) is not within its parent (e.g. parcel)."""
    child = _safe_polygon(child_geojson)
    parent = _safe_polygon(parent_geojson)
    results = []
    if child is not None and parent is not None:
        if not parent.buffer(1e-9).contains(child):
            results.append({
                "check_type": "building_outside_parcel" if "parcel" in parent_label.lower() else "unit_outside_building",
                "severity": "HIGH",
                "message": f"{child_label} is not fully contained within {parent_label}",
            })
    return results


def check_overlap(geometries: List[Dict]) -> List[Dict]:
    """
    geometries: list of {"id": str, "label": str, "geojson": str}
    Flags any pair whose polygons overlap (excluding touching edges).
    """
    results = []
    parsed = [(g["id"], g["label"], _safe_polygon(g["geojson"])) for g in geometries]
    parsed = [p for p in parsed if p[2] is not None]
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            id_a, label_a, poly_a = parsed[i]
            id_b, label_b, poly_b = parsed[j]
            if poly_a.intersects(poly_b) and not poly_a.touches(poly_b):
                intersection_area = poly_a.intersection(poly_b).area
                if intersection_area > 1e-9:
                    results.append({
                        "check_type": "unit_overlap",
                        "severity": "HIGH",
                        "message": f"{label_a} overlaps {label_b} (intersection area {intersection_area:.4f})",
                    })
    return results


def check_z_range(z_min: float, z_max: float, label: str) -> List[Dict]:
    results = []
    if z_max <= z_min:
        results.append({
            "check_type": "invalid_z_range",
            "severity": "HIGH",
            "message": f"{label}: invalid elevation range (Zmax {z_max} <= Zmin {z_min})",
        })
    return results


def check_floor_overlap(floors: List[Dict]) -> List[Dict]:
    """floors: list of {"id", "label", "z_min", "z_max"} for one building."""
    results = []
    sorted_floors = sorted(floors, key=lambda f: f["z_min"])
    for i in range(len(sorted_floors) - 1):
        a, b = sorted_floors[i], sorted_floors[i + 1]
        if a["z_max"] > b["z_min"] + 1e-6:
            results.append({
                "check_type": "floor_overlap",
                "severity": "MEDIUM",
                "message": f"{a['label']} (up to {a['z_max']}m) vertically overlaps {b['label']} (from {b['z_min']}m)",
            })
    return results


def check_underground_conflict(building_geojson: str, building_label: str,
                                 asset_geojson: str, asset_label: str, asset_type: str) -> List[Dict]:
    building = _safe_polygon(building_geojson)
    asset = _safe_polygon(asset_geojson)
    results = []
    if building is not None and asset is not None and building.intersects(asset):
        results.append({
            "check_type": "underground_conflict",
            "severity": "HIGH",
            "message": f"HIGH — {asset_type.replace('_', ' ').title()} ({asset_label}) intersects {building_label} basement volume",
        })
    return results


def check_height_floor_consistency(height_m: Optional[float], num_floors: Optional[int], building_label: str,
                                    min_floor_height_m: float = 2.4, max_floor_height_m: float = 4.5) -> List[Dict]:
    """
    Automated check comparing a building's declared/OSM height against its
    declared/OSM floor count, flagging the discrepancy for review instead
    of silently trusting mismatched source data (OSM height and
    building:levels tags are independently entered and frequently
    disagree). A real plausibility check, not a guess: given a real-world
    range of per-storey heights (min_floor_height_m to max_floor_height_m,
    same bounds used elsewhere in this project for point-cloud floor
    clustering), the plausible floor-count range for a given height is
    [height / max_floor_height_m, height / min_floor_height_m]. If the
    declared num_floors falls outside that range, it's flagged.

    Returns [] if height_m or num_floors is missing (nothing to check
    against) or if the values are consistent -- a ValidationResult-shaped
    list otherwise.
    """
    if not height_m or not num_floors or height_m <= 0 or num_floors <= 0:
        return []

    plausible_min_floors = height_m / max_floor_height_m
    plausible_max_floors = height_m / min_floor_height_m

    if plausible_min_floors <= num_floors <= plausible_max_floors:
        return []

    implied_floor_height = round(height_m / num_floors, 2)
    return [{
        "check_type": "height_floor_inconsistency",
        "severity": "medium",
        "message": (
            f"{building_label}: declared height {height_m}m with {num_floors} floors implies "
            f"{implied_floor_height}m per floor, outside the plausible {min_floor_height_m}-{max_floor_height_m}m "
            f"range (expected {plausible_min_floors:.1f}-{plausible_max_floors:.1f} floors for this height)."
        ),
    }]



def check_slenderness(height_m: Optional[float], footprint_w: float, footprint_d: float,
                      building_label: str, max_ratio: float = 8.0) -> List[Dict]:
    """A building far taller than its footprint is wide is almost always a
    wrong floor count (or a wrong footprint), not a real needle tower."""
    short_side = min(footprint_w, footprint_d)
    if not height_m or short_side <= 0:
        return []
    ratio = height_m / short_side
    if ratio <= max_ratio:
        return []
    return [{
        "check_type": "anomaly_slenderness",
        "severity": "MEDIUM",
        "message": (
            f"{building_label}: height {height_m:.0f}m on a {short_side:.1f}m-wide footprint "
            f"(ratio {ratio:.1f}:1) is implausibly slender -- check the floor count or footprint."
        ),
    }]


def check_vegetation_ndvi(ndvi_result: Optional[Dict], building_label: str) -> List[Dict]:
    """
    Flags a footprint whose real Sentinel-2 NDVI (ai/vegetation/ndvi_check.py
    -- actual satellite reflectance, not a guess) reads as vegetation
    rather than a built surface. ndvi_result is whatever
    ndvi_check.check_vegetation_ndvi() returned (or None, if the check
    couldn't run -- in which case this raises nothing, same "no evidence,
    no flag" rule every other check in this file follows).

    This never deletes or blocks the building -- same as every other
    anomaly check here, it only queues a HIGH-severity item for a human
    reviewer, since a false positive here (a genuine building surrounded
    by/partly covered in trees) is a real possibility a satellite index
    alone can't rule out.
    """
    if not ndvi_result or not ndvi_result.get("likely_vegetation"):
        return []
    return [{
        "check_type": "anomaly_possible_vegetation",
        "severity": "HIGH",
        "message": (
            f"{building_label}: mean NDVI {ndvi_result['ndvi_mean']:.2f} over this footprint "
            f"({ndvi_result['source']}, {ndvi_result['scene_date'][:10] if ndvi_result.get('scene_date') else 'recent scene'}) "
            f"reads as vegetation, not a built surface -- likely tree canopy misread as a building. Verify on site/imagery before confirming."
        ),
    }]


def check_area_outlier(area_sqm: float, batch_median_sqm: Optional[float], building_label: str,
                       factor: float = 30.0) -> List[Dict]:
    """Footprint wildly larger than the rest of the same import batch --
    usually a merged/mis-traced polygon rather than one real building."""
    if not batch_median_sqm or batch_median_sqm <= 0 or area_sqm <= 0:
        return []
    if area_sqm <= batch_median_sqm * factor:
        return []
    return [{
        "check_type": "anomaly_area_outlier",
        "severity": "LOW",
        "message": (
            f"{building_label}: footprint {area_sqm:.0f} sqm is {area_sqm / batch_median_sqm:.0f}x the "
            f"median of this import ({batch_median_sqm:.0f} sqm) -- possibly several buildings merged."
        ),
    }]
