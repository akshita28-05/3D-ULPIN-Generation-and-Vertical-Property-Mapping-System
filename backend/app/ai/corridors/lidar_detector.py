"""Aerial-LiDAR detection of elevated linear structures (viaduct / flyover decks)
and fusion with OSM candidates.

Method (no trained model, all numpy/scipy):
 1. Grid the cloud (default 1 m). Per cell: z_top, point count, z spread.
 2. Local ground = moving-window minimum of cell z_min (or a supplied DEM value).
 3. Keep cells that are >= MIN_ELEV_M above ground, flat (low z spread) and NOT
    inside a known building footprint.
 4. Connected components -> keep the elongated, narrow ones (length/width and
    absolute size gates). Trees fail flatness, buildings fail the footprint
    mask + aspect gate, blocks of roofs fail the width gate.
 5. Deck top = median z_top of the component. Underside is MEASURED only if the
    cloud has returns beneath the deck (multi-return / oblique / mobile scan:
    a >= MIN_GAP_M vertical gap in >= 30 % of cells); otherwise it is deck top
    minus a disclosed structural depth.
Limits (read before demoing): the outline is an oriented rectangle, so a sharply
curved viaduct is over-approximated; tested on synthetic clouds only.
"""
import numpy as np
from scipy import ndimage

from . import geom2d

DEFAULT_DEPTH = {"metro": 2.5, "elevated_rail": 2.5, "flyover": 1.8, "elevated_road": 1.8, "unclassified_elevated": 2.0}
ENVELOPE = {"metro": 6.0, "elevated_rail": 6.0, "flyover": 5.5, "elevated_road": 5.5, "unclassified_elevated": 3.0}


def detect_elevated_structures(points, building_footprints=(), ground_z=None, cell=1.0,
                               min_elev_m=4.5, max_elev_m=45.0, max_flat_std=0.25,
                               min_len_m=20.0, min_w_m=3.0, max_w_m=30.0, min_aspect=4.0,
                               min_gap_m=3.0):
    pts = np.asarray(points, float)
    if pts.ndim != 2 or pts.shape[0] < 500:
        return []
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    ix = ((pts[:, 0] - x0) / cell).astype(int); iy = ((pts[:, 1] - y0) / cell).astype(int)
    W, H = ix.max() + 1, iy.max() + 1
    key = ix * H + iy
    order = np.argsort(key, kind="stable")
    ks, zs = key[order], pts[order, 2]
    uniq, start = np.unique(ks, return_index=True)
    end = np.append(start[1:], len(ks))
    span = {int(k): (int(s), int(e)) for k, s, e in zip(uniq, start, end)}

    ztop = np.full((W, H), np.nan); zmin = np.full((W, H), np.nan)
    zstd = np.full((W, H), np.nan); cnt = np.zeros((W, H), int)
    for k, s, e in zip(uniq, start, end):
        a, b = divmod(int(k), H)
        seg = zs[s:e]
        t = seg.max(); up = seg[seg >= t - 1.0]
        ztop[a, b] = np.median(up); zstd[a, b] = up.std(); zmin[a, b] = seg.min(); cnt[a, b] = e - s

    filled = np.where(np.isnan(zmin), np.inf, zmin)
    win = max(3, int(60 / cell) | 1)
    ground = ndimage.minimum_filter(filled, size=win, mode="nearest")
    if ground_z is not None:
        ground = np.full_like(ground, float(ground_z)) if np.isscalar(ground_z) else np.asarray(ground_z, float)
    ground = np.where(np.isfinite(ground), ground, np.nanmin(zmin))

    elev = ztop - ground
    cand = (~np.isnan(ztop)) & (elev >= min_elev_m) & (elev <= max_elev_m) & (zstd <= max_flat_std) & (cnt >= 2)

    if len(building_footprints):
        gx, gy = np.meshgrid(x0 + (np.arange(W) + 0.5) * cell, y0 + (np.arange(H) + 0.5) * cell, indexing="ij")
        for fp in building_footprints:
            pad = np.asarray(fp, float)
            cand &= ~_inside_expanded(gx, gy, pad, 1.5)

    cand = ndimage.binary_closing(cand, structure=np.ones((3, 3)), iterations=1) & (~np.isnan(ztop))
    lab, n = ndimage.label(cand, structure=np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        cells = np.argwhere(lab == i)
        if len(cells) < (min_len_m * min_w_m) / (cell * cell) * 0.6:
            continue
        cxy = np.stack([x0 + (cells[:, 0] + 0.5) * cell, y0 + (cells[:, 1] + 0.5) * cell], 1)
        rect, length, width, ang = geom2d.oriented_rect(cxy)
        length += cell; width += cell
        if length < min_len_m or not (min_w_m <= width <= max_w_m) or length / max(width, 1e-6) < min_aspect:
            continue
        tops = ztop[cells[:, 0], cells[:, 1]]; grd = ground[cells[:, 0], cells[:, 1]]
        deck_top = float(np.median(tops)); ground_m = float(np.median(grd))
        sample = cells[:: max(1, len(cells) // 200)]
        open_n, unders = 0, []
        for a, b in sample:
            s0, e0 = span[int(a * H + b)]
            zz = np.sort(zs[s0:e0])
            if len(zz) < 2:
                continue
            d = np.diff(zz); j = int(np.argmax(d))
            if d[j] >= min_gap_m and zz[j + 1] >= ztop[a, b] - 3.5:
                open_n += 1
                up = zz[j + 1:]
                if up.max() - up.min() >= 1.0:
                    unders.append(up.min())
        open_frac = open_n / max(1, len(sample))
        if len(unders) >= 0.3 * max(1, len(sample)):
            under = float(np.median(unders)); usrc = "lidar_measured_underside"
        else:
            under = None; usrc = "assumed_structural_depth"
        flat = 1.0 - min(1.0, float(np.nanmedian(zstd[cells[:, 0], cells[:, 1]])) / max_flat_std)
        smooth = 1.0 - min(1.0, float(np.std(tops)) / 3.0)
        aspect_s = min(1.0, (length / width) / 12.0)
        conf = round(float(np.clip(0.35 + 0.25 * flat + 0.2 * smooth + 0.2 * aspect_s, 0, 0.9)), 2)
        out.append({
            "source": "lidar", "polygon_local": rect, "length_m": round(length, 1), "width_m": round(width, 1),
            "bearing_deg": round(float(np.degrees(ang)) % 180, 1),
            "deck_top_m": round(deck_top - ground_m, 2),
            "deck_underside_m": None if under is None else round(under - ground_m, 2),
            "underside_source": usrc, "open_underneath": round(open_frac, 2), "cells": int(len(cells)), "confidence": conf,
        })
    return out


def _inside_expanded(gx, gy, poly, pad):
    """Inside polygon OR within `pad` metres of its outline (cheap dilation)."""
    p = np.asarray(poly, float)
    inside = geom2d.points_in_polygon(gx, gy, p)
    cx, cy = p[:, 0].mean(), p[:, 1].mean()
    grown = p + (p - [cx, cy]) / np.maximum(np.hypot(*(p - [cx, cy]).T), 1e-6)[:, None] * pad
    return inside | geom2d.points_in_polygon(gx, gy, grown)


def fuse(osm_corridors, lidar_structures, min_overlap=0.30):
    """OSM says WHAT it is; LiDAR says HOW HIGH it really is. Returns final proposals."""
    used, fused = set(), []
    for c in osm_corridors:
        best, bi = 0.0, None
        for i, l in enumerate(lidar_structures):
            a = geom2d.overlap_area(c["polygon_local"], l["polygon_local"])
            r = a / max(1e-6, min(geom2d.polygon_area(c["polygon_local"]), geom2d.polygon_area(l["polygon_local"])))
            if r > best:
                best, bi = r, i
        c = dict(c)
        if bi is not None and best >= min_overlap:
            l = lidar_structures[bi]; used.add(bi)
            depth = DEFAULT_DEPTH[c["corridor_type"]]
            under = l["deck_underside_m"] if l["deck_underside_m"] is not None else max(l["deck_top_m"] - depth, 0.0)
            c.update(
                deck_top_m=l["deck_top_m"], deck_underside_m=round(under, 2),
                height_min_m=round(under, 2),
                height_max_m=round(l["deck_top_m"] + ENVELOPE[c["corridor_type"]], 2),
                height_source="lidar_measured_top" + ("+underside" if l["underside_source"] == "lidar_measured_underside" else "+assumed_depth"),
                confidence=round(min(0.90 if l["underside_source"] == "lidar_measured_underside" else 0.80, max(c["confidence"], l["confidence"]) + 0.15), 2),
                source="osm+lidar", lidar_overlap=round(best, 2),
            )
            c["notes"] = [n for n in c["notes"] if "planning defaults" not in n] + ["Deck height measured from LiDAR."]
        fused.append(c)
    for i, l in enumerate(lidar_structures):
        if i in used:
            continue
        t = "unclassified_elevated"
        under = l["deck_underside_m"] if l["deck_underside_m"] is not None else max(l["deck_top_m"] - DEFAULT_DEPTH[t], 0.0)
        fused.append({
            "corridor_type": t, "source": "lidar", "osm_id": None, "name": None,
            "polygon_local": l["polygon_local"], "width_m": l["width_m"], "width_source": "lidar_measured",
            "deck_top_m": l["deck_top_m"], "deck_underside_m": round(under, 2),
            "height_min_m": round(under, 2), "height_max_m": round(l["deck_top_m"] + ENVELOPE[t], 2),
            "height_source": "lidar_measured_top" + ("+underside" if l["underside_source"] == "lidar_measured_underside" else "+assumed_depth"),
            "confidence": round(min(l["confidence"], 0.6), 2),
            "notes": ["Elevated linear structure seen in LiDAR with no matching OSM way -- type unknown, reviewer must classify."],
        })
    return fused
