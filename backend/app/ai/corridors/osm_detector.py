"""OSM-tag based detection of elevated corridors and parking areas.

WHAT IS REAL: which ways are bridges/viaducts/elevated (bridge=*, layer>=1,
railway=subway|light_rail|monorail ...) and where they are, comes straight
from OpenStreetMap. Corridor TYPE is a deterministic tag rule.
WHAT IS ASSUMED: unless OSM carries a height tag (rare), deck underside /
thickness / above-deck envelope are documented planning defaults (DEFAULTS
below, overridable), reported with height_source="assumed_default" and a
confidence capped at 0.45. lidar_detector.fuse() replaces them with measured
values when a point cloud is available.
"""
import math
import os

import numpy as np

from . import geom2d

M_PER_DEG_LAT = 111320.0

DEFAULTS = {
    "metro":         {"under": 7.0, "depth": 2.5, "envelope": 6.0, "per_track_w": 4.5},
    "elevated_rail": {"under": 6.0, "depth": 2.5, "envelope": 6.0, "per_track_w": 4.5},
    "flyover":       {"under": 5.5, "depth": 1.8, "envelope": 5.5, "lane_w": 3.5},
    "elevated_road": {"under": 5.5, "depth": 1.8, "envelope": 5.5, "lane_w": 3.5},
}
ASSUMED_CONF_CAP = 0.45
RAIL_METRO = {"subway", "light_rail", "monorail"}
RAIL_OTHER = {"rail", "tram", "narrow_gauge"}
ROAD_MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link",
              "trunk_link", "primary_link", "secondary_link", "tertiary_link", "unclassified", "residential"}
NOT_VEHICULAR = {"footway", "path", "cycleway", "steps", "pedestrian", "bridleway", "corridor"}


def build_query(south, west, north, east, timeout=30):
    bb = f"({south},{west},{north},{east})"
    rail = "subway|light_rail|monorail|rail|tram|narrow_gauge"
    return f"""
[out:json][timeout:{timeout}];
(
  way["railway"~"^({rail})$"]["bridge"]{bb};
  way["railway"~"^({rail})$"]["layer"~"^[1-9]"]{bb};
  way["highway"]["bridge"]{bb};
  way["highway"]["layer"~"^[1-9]"]{bb};
  way["man_made"="bridge"]{bb};
  way["amenity"="parking"]{bb};
  way["amenity"="parking_space"]{bb};
  way["building"~"^(parking|garage|garages)$"]{bb};
  node["amenity"="parking_space"]{bb};
);
out body geom;
""".strip()


def latlon_to_local(points_latlon, origin_lat, origin_lon):
    m_lon = M_PER_DEG_LAT * max(math.cos(math.radians(origin_lat)), 1e-6)
    return [[(lon - origin_lon) * m_lon, (lat - origin_lat) * M_PER_DEG_LAT] for lat, lon in points_latlon]


def _geom_latlon(el):
    return [(g["lat"], g["lon"]) for g in el.get("geometry", [])]


def _num(v):
    try:
        return float(str(v).split()[0].replace(",", "."))
    except (TypeError, ValueError, IndexError):
        return None


def _is_elevated(tags):
    bridge = tags.get("bridge")
    layer = _num(tags.get("layer"))
    if tags.get("tunnel") in ("yes", "building_passage", "culvert") or (layer is not None and layer < 0):
        return False
    return (bridge not in (None, "no")) or (layer is not None and layer >= 1)


def classify_corridor_type(tags):
    """Deterministic tag rule -> corridor_type or None (not a vehicle/rail corridor)."""
    if not _is_elevated(tags):
        return None
    rw, hw = tags.get("railway"), tags.get("highway")
    if rw in RAIL_METRO:
        return "metro"
    if rw in RAIL_OTHER:
        return "elevated_rail"
    if hw and hw not in NOT_VEHICULAR:
        return "flyover" if (hw in ROAD_MAJOR and tags.get("bridge") not in (None, "no")) else "elevated_road"
    return None


def _corridor_from_way(el, origin):
    tags = el.get("tags", {})
    ctype = classify_corridor_type(tags)
    if not ctype:
        return None
    ll = _geom_latlon(el)
    if len(ll) < 2:
        return None
    line = latlon_to_local(ll, *origin)
    d = DEFAULTS[ctype]
    layer = _num(tags.get("layer")) or 1.0

    w = _num(tags.get("width"))
    wsrc = "osm_tag"
    if w is None:
        if "per_track_w" in d:
            w = (_num(tags.get("tracks")) or 1.0) * d["per_track_w"]
        else:
            lanes = _num(tags.get("lanes")) or 2.0
            w = lanes * d["lane_w"] + 1.0
        wsrc = "assumed_default"

    tag_h, tag_min = _num(tags.get("height")), _num(tags.get("min_height"))
    if tag_h is not None:
        top = tag_h
        under = tag_min if tag_min is not None else max(top - d["depth"], 0.0)
        hsrc = "osm_tag"
    else:
        under = d["under"] + max(layer - 1.0, 0.0) * 6.0
        top = under + d["depth"]
        hsrc = "assumed_default"
    hmax = top + d["envelope"]
    conf = 0.70 if hsrc == "osm_tag" else 0.40
    if hsrc != "osm_tag":
        conf = min(conf, ASSUMED_CONF_CAP)
    notes = []
    if hsrc == "assumed_default":
        notes.append("Heights are planning defaults; no OSM height tag and no LiDAR measurement.")
    if tags.get("waterway") or tags.get("bridge:structure") == "simple_supported" and tags.get("waterway"):
        notes.append("May span water; clearance above ground is not meaningful there.")
    return {
        "corridor_type": ctype, "source": "osm", "osm_id": el.get("id"),
        "name": tags.get("name") or tags.get("ref"),
        "centerline_local": line, "width_m": round(w, 2), "width_source": wsrc,
        "deck_underside_m": round(under, 2), "deck_top_m": round(top, 2),
        "height_min_m": round(under, 2), "height_max_m": round(hmax, 2),
        "height_source": hsrc, "confidence": round(conf, 2),
        "polygon_local": geom2d.buffer_polyline(line, w), "notes": notes,
        "tags_used": {k: tags[k] for k in ("railway", "highway", "bridge", "layer", "height", "min_height", "lanes", "tracks", "width") if k in tags},
    }


def merge_parallel_rail(corridors, gap_m=3.0):
    """Double-track viaducts are two OSM ways a few metres apart -> one corridor
    (convex hull; exact for near-straight viaducts, generous for tight curves)."""
    from scipy.spatial import ConvexHull
    rail = [c for c in corridors if c["corridor_type"] in ("metro", "elevated_rail")]
    other = [c for c in corridors if c not in rail]
    groups = []
    for c in rail:
        for g in groups:
            if g[0]["corridor_type"] == c["corridor_type"] and any(
                geom2d.min_distance(m["polygon_local"], c["polygon_local"]) <= gap_m for m in g
            ):
                g.append(c); break
        else:
            groups.append([c])
    merged = []
    for g in groups:
        if len(g) == 1:
            merged.append(g[0]); continue
        pts = np.vstack([np.asarray(m["polygon_local"], float) for m in g])
        h = ConvexHull(pts)
        poly = pts[h.vertices].tolist(); poly.append(poly[0])
        base = dict(g[0])
        base.update(polygon_local=poly, merged_osm_ids=[m["osm_id"] for m in g],
                    height_min_m=min(m["height_min_m"] for m in g),
                    height_max_m=max(m["height_max_m"] for m in g),
                    confidence=min(m["confidence"] for m in g))
        base["notes"] = list(base["notes"]) + [f"Merged {len(g)} parallel OSM ways (double track)."]
        merged.append(base)
    return other + merged


def classify_parking(elements, origin):
    """Parking areas + mapped stall counts -> proposals. Levels/capacity are only
    reported when OSM says so (None otherwise -- never invented)."""
    areas, stalls = [], []
    for el in elements:
        tags = el.get("tags", {})
        if tags.get("amenity") == "parking_space":
            if el["type"] == "node":
                stalls.append([(el["lon"] - origin[1]) * M_PER_DEG_LAT * math.cos(math.radians(origin[0])),
                               (el["lat"] - origin[0]) * M_PER_DEG_LAT])
            else:
                ll = _geom_latlon(el)
                if ll:
                    loc = np.mean(latlon_to_local(ll, *origin), axis=0)
                    stalls.append(loc.tolist())
            continue
        is_area = tags.get("amenity") == "parking" or tags.get("building") in ("parking", "garage", "garages")
        if not is_area or el["type"] != "way":
            continue
        ll = _geom_latlon(el)
        if len(ll) < 4:
            continue
        poly = latlon_to_local(ll, *origin)
        ptype = tags.get("parking")
        layer = _num(tags.get("layer"))
        if ptype in ("underground",) or tags.get("location") == "underground" or (layer is not None and layer < 0):
            kind = "underground"
        elif ptype in ("multi-storey", "multi_storey") or tags.get("building") == "parking":
            kind = "multi_storey"
        elif ptype == "rooftop":
            kind = "rooftop"
        elif tags.get("building") in ("garage", "garages"):
            kind = "garage"
        else:
            kind = "surface"
        levels = _num(tags.get("building:levels")) or _num(tags.get("parking:levels")) or _num(tags.get("levels"))
        areas.append({
            "parking_kind": kind, "source": "osm", "osm_id": el["id"], "name": tags.get("name"),
            "polygon_local": poly, "area_sqm": round(geom2d.polygon_area(poly), 1),
            "levels": levels, "capacity": _num(tags.get("capacity")),
            "confidence": 0.65, "mapped_stalls": 0,
            "notes": [] if levels is not None or kind in ("surface", "garage") else ["Level count not in OSM -- reviewer must supply."],
        })
    for s in stalls:
        for a in areas:
            if geom2d.points_in_polygon(np.array([s[0]]), np.array([s[1]]), a["polygon_local"])[0]:
                a["mapped_stalls"] += 1; break
    return areas


def classify_elements(elements, origin):
    corridors = [c for c in (_corridor_from_way(e, origin) for e in elements if e.get("type") == "way") if c]
    return {"corridors": merge_parallel_rail(corridors), "parking": classify_parking(elements, origin)}
