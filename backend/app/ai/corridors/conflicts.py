"""Corridor-vs-building conflict test in 3-D: footprint overlap (or setback
proximity) AND overlapping height ranges. Heights are metres above local ground.
SETBACK_M is a configurable planning default, not a legal figure."""
import os
from . import geom2d

SETBACK_M = float(os.getenv("CORRIDOR_SETBACK_M", "3.0"))


def assess(corridor_poly, hmin, hmax, buildings):
    """buildings: [{'id','footprint':[[x,y]..],'height_m':float|None}] ->
    (status, [reasons]). status in none / potential / confirmed."""
    status, why = "none", []
    for b in buildings:
        h = b.get("height_m")
        if h is None:
            continue
        v_overlap = hmin < h and hmax > 0
        if not v_overlap:
            continue
        a = geom2d.overlap_area(corridor_poly, b["footprint"])
        if a > 0.5:
            status = "confirmed"
            why.append(f"Building {b.get('id')} footprint overlaps corridor by {a:.0f} m2 and rises to {h:.1f} m, above corridor underside {hmin:.1f} m.")
        elif geom2d.min_distance(corridor_poly, b["footprint"]) <= SETBACK_M and status != "confirmed":
            status = "potential"
            why.append(f"Building {b.get('id')} is within {SETBACK_M:.0f} m setback of the corridor envelope.")
    return status, why
