"""OpenStreetMap tags -> typed underground structures and air-right corridors.

WHAT IS REAL: that a tunnel / basement / viaduct / cable / power line exists, where
it runs, and its type. All of it is read from OpenStreetMap, never invented.

WHAT IS ASSUMED: OSM rarely stores depth or clearance. When a tag (`depth`,
`building:levels:underground`, `height`, `min_height`, `voltage` ...) is present it
is used and the feature is stamped z_source="osm_tag". Otherwise a documented
planning default for that structure type is used, stamped z_source="assumed_default",
with confidence capped at 0.45 -- the same convention as ai/corridors/osm_detector.py.
The defaults below are typical values, NOT survey or legal figures.

Nothing here is an official record: features are PROPOSALS for verifier review.
"""
import math

from shapely.geometry import Polygon
from shapely.validation import make_valid

from ..ai.corridors import osm_detector

M_PER_DEG_LAT = 111320.0
ASSUMED_CONF_CAP = 0.45
STOREY_M = 3.2

UNDERGROUND_DEFAULTS = {
    "metro_tunnel":      {"top": 12.0, "bottom": 22.0, "width": 6.5, "label": "Metro tunnel"},
    "rail_tunnel":       {"top": 8.0,  "bottom": 16.0, "width": 7.0, "label": "Rail tunnel"},
    "road_tunnel":       {"top": 6.0,  "bottom": 14.0, "width": None, "label": "Road tunnel"},
    "road_underpass":    {"top": 0.5,  "bottom": 6.5,  "width": None, "label": "Road underpass"},
    "pedestrian_subway": {"top": 1.0,  "bottom": 4.5,  "width": 3.0, "label": "Pedestrian subway"},
    "culvert":           {"top": 0.5,  "bottom": 3.0,  "width": 1.6, "label": "Culvert"},
    "storm_drain":       {"top": 1.0,  "bottom": 4.0,  "width": 1.6, "label": "Storm drain"},
    "power_cable":       {"top": 0.6,  "bottom": 1.5,  "width": 0.8, "label": "Underground power cable"},
    "pipeline":          {"top": 1.0,  "bottom": 2.5,  "width": 0.9, "label": "Buried pipeline"},
    "underground_parking": {"top": 0.5, "bottom": None, "width": None, "label": "Underground parking"},
    "basement":          {"top": 0.0,  "bottom": None, "width": None, "label": "Basement levels"},
}
DISPLAY_MIN_WIDTH_M = 3.0

POWER_CLASSES = [
    (700, 64.0, 15.0, 60.0), (380, 52.0, 12.0, 50.0), (200, 35.0, 9.0, 45.0),
    (110, 27.0, 8.0, 35.0), (60, 18.0, 7.0, 30.0), (30, 15.0, 6.0, 25.0),
]
POWER_UNKNOWN = (15.0, 6.0, 25.0)

AIR_LABELS = {
    "metro": "Elevated metro", "elevated_rail": "Elevated rail", "flyover": "Flyover",
    "elevated_road": "Elevated road", "power_line": "Overhead power line (right-of-way)",
}

RAIL_ALL = {"subway", "light_rail", "monorail", "rail", "tram", "narrow_gauge"}
RAIL_METRO = {"subway", "light_rail", "monorail"}
MIN_ROAD_BRIDGE_M = 60.0


def build_query(south, west, north, east, timeout=25):
    bb = f"({south},{west},{north},{east})"
    rail = "subway|light_rail|monorail|rail|tram|narrow_gauge"
    return f"""
[out:json][timeout:{timeout}];
(
  way["railway"~"^({rail})$"]["bridge"]{bb};
  way["railway"~"^({rail})$"]["layer"~"^[1-9]"]{bb};
  way["highway"]["bridge"]{bb};
  way["highway"]["layer"~"^[1-9]"]{bb};
  way["power"="line"]{bb};
  way["tunnel"~"^(yes|culvert|flooded)$"]{bb};
  way["location"="underground"]{bb};
  way["power"="cable"]{bb};
  way["man_made"="pipeline"]["location"~"^(underground|underwater)$"]{bb};
  way["amenity"="parking"]["parking"="underground"]{bb};
  way["amenity"="parking"]["layer"~"^-"]{bb};
  way["building"]["building:levels:underground"]{bb};
  way["building:part"]["building:levels:underground"]{bb};
  way["highway"]["layer"~"^-[1-9]"]{bb};
);
out body geom;
""".strip()



def _num(v):
    return osm_detector._num(v)


def _line_len(line):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(line[:-1], line[1:]))


def _is_closed(ll):
    return len(ll) >= 4 and ll[0] == ll[-1]


def _local_to_lonlat(points, origin):
    olat, olon = origin
    m_lon = M_PER_DEG_LAT * max(math.cos(math.radians(olat)), 1e-6)
    return [[olon + x / m_lon, olat + y / M_PER_DEG_LAT] for x, y in points]


def _valid_polygon(points_local):
    try:
        poly = Polygon(points_local)
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        if poly.geom_type != "Polygon" or poly.is_empty or poly.area < 0.5:
            return None
        return [[float(x), float(y)] for x, y in poly.exterior.coords]
    except Exception:
        return None


def _conf(z_source):
    return 0.7 if z_source == "osm_tag" else min(0.4, ASSUMED_CONF_CAP)


def _voltage_kv(tags):
    best = None
    for part in str(tags.get("voltage", "")).replace(",", ";").split(";"):
        v = _num(part)
        if v:
            best = max(best or 0.0, v / 1000.0 if v > 1000 else v)
    return best



def classify_underground(tags, length_m, closed):
    """Deterministic tag rule -> subtype or None (not something we can say is underground)."""
    if tags.get("bridge") not in (None, "no"):
        return None
    tunnel, loc, layer = tags.get("tunnel"), tags.get("location"), _num(tags.get("layer"))
    is_tunnel = tunnel in ("yes", "culvert", "flooded")
    below = layer is not None and layer < 0
    rw, hw, ww = tags.get("railway"), tags.get("highway"), tags.get("waterway")

    if tags.get("amenity") == "parking":
        if closed and (tags.get("parking") == "underground" or loc == "underground" or below):
            return "underground_parking"
        return None
    if (tags.get("building") or tags.get("building:part")) and _num(tags.get("building:levels:underground")):
        return "basement" if closed else None
    if tags.get("power") == "cable" or (tags.get("power") in ("line", "minor_line") and loc == "underground"):
        return None if loc in ("overhead", "overground") else "power_cable"
    if tags.get("man_made") == "pipeline":
        return "pipeline" if loc in ("underground", "underwater") else None
    if rw and (is_tunnel or loc == "underground" or below):
        if rw in RAIL_METRO:
            return "metro_tunnel"
        return "rail_tunnel" if rw in RAIL_ALL else None
    if hw and (is_tunnel or below):
        if tunnel == "culvert":
            return "culvert"
        if hw in osm_detector.NOT_VEHICULAR:
            return "pedestrian_subway"
        return "road_tunnel" if length_m >= 250 else "road_underpass"
    if ww and is_tunnel:
        return "storm_drain" if ww in ("drain", "ditch") else "culvert"
    return None


def _underground_feature(el, origin):
    tags = el.get("tags", {})
    ll = osm_detector._geom_latlon(el)
    if len(ll) < 2:
        return None
    local = osm_detector.latlon_to_local(ll, *origin)
    closed = _is_closed(ll)
    length = _line_len(local)
    subtype = classify_underground(tags, length, closed)
    if not subtype:
        return None
    d = UNDERGROUND_DEFAULTS[subtype]
    notes = []
    z_source = "assumed_default"

    if subtype in ("basement", "underground_parking"):
        levels = (_num(tags.get("building:levels:underground")) or _num(tags.get("parking:levels"))
                  or _num(tags.get("levels")))
        if levels:
            z_source = "osm_tag"
            notes.append(f"OSM gives {levels:g} underground level(s); {STOREY_M} m per level is an assumed storey height.")
        else:
            levels = 1.0
            notes.append("Level count not in OSM -- one level assumed.")
        z_min = d["top"]
        z_max = round(z_min + levels * STOREY_M, 1)
        ring = _valid_polygon(local if closed else local + [local[0]])
        if not ring:
            return None
        return _pack("underground", subtype, tags, el, origin, geometry_local=("Polygon", ring),
                     width=None, z_min=z_min, z_max=z_max, deck_top=None, z_source=z_source, notes=notes)

    depth = _num(tags.get("depth"))
    if depth and depth > 0:
        z_source = "osm_tag"
        z_max = float(depth)
        z_min = max(0.0, z_max - (d["bottom"] - d["top"]))
    else:
        z_min, z_max = d["top"], d["bottom"]
        notes.append(f"Depth is a typical value for a {d['label'].lower()} ({z_min:g}-{z_max:g} m), not measured.")
    width = _num(tags.get("width")) or d["width"]
    if width is None:
        width = (_num(tags.get("lanes")) or 2.0) * 3.5 + 1.0
    return _pack("underground", subtype, tags, el, origin, geometry_local=("LineString", local),
                 width=float(width), z_min=z_min, z_max=z_max, deck_top=None, z_source=z_source, notes=notes)



def _corridor_feature(el, origin):
    c = osm_detector._corridor_from_way(el, origin)
    if not c:
        return None
    tags = el.get("tags", {})
    length = _line_len(c["centerline_local"])
    layer = _num(tags.get("layer"))
    minor = (
        c["corridor_type"] in ("flyover", "elevated_road", "elevated_rail")
        and not (layer is not None and layer >= 1)
        and tags.get("bridge") not in ("viaduct",)
        and length < MIN_ROAD_BRIDGE_M
    )
    if minor:
        return None
    ring = _valid_polygon(c["polygon_local"])
    if not ring:
        return None
    z_source = "osm_tag" if c["height_source"] == "osm_tag" else "assumed_default"
    notes = list(c["notes"])
    return _pack("air", c["corridor_type"], tags, el, origin, geometry_local=("Polygon", ring),
                 width=c["width_m"], z_min=c["deck_underside_m"], z_max=c["height_max_m"],
                 deck_top=c["deck_top_m"], z_source=z_source, notes=notes)


def _power_line_feature(el, origin):
    tags = el.get("tags", {})
    if tags.get("power") != "line" or tags.get("location") in ("underground", "underwater"):
        return None
    ll = osm_detector._geom_latlon(el)
    if len(ll) < 2:
        return None
    local = osm_detector.latlon_to_local(ll, *origin)
    kv = _voltage_kv(tags)
    notes = []
    if kv is None:
        row, clearance, top = POWER_UNKNOWN
        z_source = "assumed_default"
        notes.append("Voltage not tagged in OSM -- smallest right-of-way class assumed.")
    else:
        row, clearance, top = next(((r, c, t) for v, r, c, t in POWER_CLASSES if kv >= v), POWER_UNKNOWN)
        z_source = "osm_tag"
        notes.append(f"Right-of-way width and clearance are planning defaults for a ~{kv:g} kV line (not legal figures).")
    width = _num(tags.get("width")) or row
    from ..ai.corridors import geom2d
    ring = _valid_polygon(geom2d.buffer_polyline(local, width))
    if not ring:
        return None
    return _pack("air", "power_line", tags, el, origin, geometry_local=("Polygon", ring),
                 width=float(width), z_min=clearance, z_max=top, deck_top=None,
                 z_source=z_source, notes=notes, conf=0.6 if kv is not None else 0.35)



def _pack(kind, subtype, tags, el, origin, geometry_local, width, z_min, z_max, deck_top, z_source, notes, conf=None):
    gtype, coords = geometry_local
    lonlat = _local_to_lonlat(coords, origin)
    xs, ys = [p[0] for p in lonlat], [p[1] for p in lonlat]
    if gtype == "Polygon":
        geometry = {"type": "Polygon", "coordinates": [lonlat if lonlat[0] == lonlat[-1] else lonlat + [lonlat[0]]]}
    else:
        geometry = {"type": "LineString", "coordinates": lonlat}
    keep = ("railway", "highway", "bridge", "tunnel", "layer", "location", "power", "voltage", "man_made", "substance",
            "amenity", "parking", "building", "building:levels:underground", "depth", "height", "min_height", "waterway")
    return {
        "kind": kind, "subtype": subtype, "name": tags.get("name") or tags.get("ref"),
        "osm_id": f"{el.get('type', 'way')}/{el.get('id')}",
        "geometry": geometry, "width_m": None if width is None else round(float(width), 2),
        "z_min_m": round(float(z_min), 2), "z_max_m": round(float(z_max), 2),
        "deck_top_m": None if deck_top is None else round(float(deck_top), 2),
        "z_source": z_source, "confidence": round(conf if conf is not None else _conf(z_source), 2),
        "notes": notes, "tags": {k: tags[k] for k in keep if k in tags},
        "bbox": (min(ys), min(xs), max(ys), max(xs)),
    }


def classify_elements(elements, origin, max_features=1500):
    """Overpass `elements` -> list of feature dicts (see _pack). `origin` = (lat, lon) used
    only for the intermediate local-metre maths; output geometry is lon/lat."""
    out = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        feature = None
        try:
            if tags.get("power") == "line":
                feature = _power_line_feature(el, origin)
            if feature is None:
                feature = _corridor_feature(el, origin) or _underground_feature(el, origin)
        except Exception:
            feature = None
        if feature:
            out.append(feature)
        if len(out) >= max_features:
            break
    return out


def label_for(kind, subtype):
    if kind == "air":
        return AIR_LABELS.get(subtype, subtype.replace("_", " ").title())
    return UNDERGROUND_DEFAULTS.get(subtype, {}).get("label", subtype.replace("_", " ").title())
