"""Parking detection: (a) painted stalls on an orthophoto, (b) stall geometry in
floor plans / unit polygons. Classical computer vision + geometry -- no trained
model. Painted-line detection needs a top-down image with visible markings
(GSD <= ~0.10 m/px); it says nothing about a basement unless you have imagery
or a scan OF that basement. Tested on synthetic images only.
"""
import math
import numpy as np

from . import geom2d

STALL_W = (2.2, 3.2)
STALL_L = (4.3, 6.0)


def detect_painted_stalls(image, gsd_m_per_px, origin_xy=(0.0, 0.0), line_thresh=None):
    """image: HxW or HxWx3 uint8 top-down orthophoto. Returns dict with stall
    rows: each row = run of >=3 parallel painted lines ~2.2-3.2 m apart."""
    try:
        import cv2
    except ImportError:
        return {"available": False, "reason": "opencv not installed (requirements-ml.txt)", "rows": []}
    img = np.asarray(image)
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    t = line_thresh if line_thresh is not None else float(np.clip(g.mean() + 2.0 * g.std(), 150, 250))
    mask = (g >= t).astype(np.uint8) * 255
    min_len_px = int(3.0 / gsd_m_per_px)
    segs = cv2.HoughLinesP(mask, 1, np.pi / 180, threshold=max(20, min_len_px // 3),
                           minLineLength=min_len_px, maxLineGap=int(0.6 / gsd_m_per_px))
    if segs is None:
        return {"available": True, "rows": [], "n_segments": 0}
    segs = segs[:, 0, :].astype(float)
    ang = np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0])) % 180
    hist, edges = np.histogram(ang, bins=36, range=(0, 180), weights=np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]))
    dom = edges[int(hist.argmax())] + 2.5
    keep = np.abs(((ang - dom + 90) % 180) - 90) <= 8
    s = segs[keep]
    if len(s) < 3:
        return {"available": True, "rows": [], "n_segments": int(len(segs))}
    th = math.radians(dom)
    normal = np.array([-math.sin(th), math.cos(th)]); along = np.array([math.cos(th), math.sin(th)])
    mid = (s[:, :2] + s[:, 2:]) / 2
    off = mid @ normal * gsd_m_per_px
    order = np.argsort(off)
    lines = []
    for i in order:
        if lines and abs(off[i] - lines[-1]["off"]) < 0.30:
            lines[-1]["idx"].append(i)
        else:
            lines.append({"off": off[i], "idx": [i]})
    for L in lines:
        L["off"] = float(np.mean([off[i] for i in L["idx"]]))
        pts = np.vstack([s[L["idx"], :2], s[L["idx"], 2:]])
        L["a0"], L["a1"] = (pts @ along * gsd_m_per_px).min(), (pts @ along * gsd_m_per_px).max()
    rows, run = [], [lines[0]]
    for L in lines[1:]:
        sp = L["off"] - run[-1]["off"]
        if STALL_W[0] <= sp <= STALL_W[1]:
            run.append(L)
        else:
            if len(run) >= 3:
                rows.append(run)
            run = [L]
    if len(run) >= 3:
        rows.append(run)
    out = []
    ox, oy = origin_xy
    for run in rows:
        stalls = []
        for a, b in zip(run[:-1], run[1:]):
            a0, a1 = max(a["a0"], b["a0"]), min(a["a1"], b["a1"])
            if a1 - a0 < 3.0:
                continue
            depth = min(a1 - a0, STALL_L[1])
            corners = [(a0, a["off"]), (a0 + depth, a["off"]), (a0 + depth, b["off"]), (a0, b["off"])]
            poly = [[ox + p * along[0] * 1 + q * normal[0], oy + p * along[1] + q * normal[1]] for p, q in corners]
            poly.append(poly[0])
            stalls.append({"polygon_local": poly, "width_m": round(b["off"] - a["off"], 2), "depth_m": round(depth, 2)})
        if stalls:
            out.append({"n_stalls": len(stalls), "bearing_deg": round(dom, 1), "stalls": stalls,
                        "confidence": round(min(0.9, 0.5 + 0.05 * len(stalls)), 2)})
    return {"available": True, "rows": out, "n_segments": int(len(segs)),
            "n_stalls": int(sum(r["n_stalls"] for r in out)), "method": "hough_parallel_lines",
            "limits": "needs visible paint, top-down view, GSD<=0.10 m/px; synthetic-tested only"}


def min_area_rect_dims(poly):
    from scipy.spatial import ConvexHull
    p = np.asarray(poly, float)
    if len(p) > 1 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    hull = p[ConvexHull(p).vertices]
    best = (float("inf"), 0, 0)
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        n = np.hypot(*e)
        if n < 1e-9:
            continue
        u = e / n; v = np.array([-u[1], u[0]])
        a, b = hull @ u, hull @ v
        w, h = a.max() - a.min(), b.max() - b.min()
        if w * h < best[0]:
            best = (w * h, w, h)
    return tuple(sorted(best[1:]))


def classify_stall_units(unit_polys):
    """Floor-plan geometry rule: a unit whose minimum-area rectangle matches a car
    bay is a stall. Returns [{index, is_stall, short_m, long_m, score}]."""
    res = []
    for i, poly in enumerate(unit_polys):
        try:
            s, l = min_area_rect_dims(poly)
        except Exception:
            res.append({"index": i, "is_stall": False, "short_m": None, "long_m": None, "score": 0.0}); continue
        ok = STALL_W[0] <= s <= STALL_W[1] and STALL_L[0] <= l <= STALL_L[1]
        fill = geom2d.polygon_area(poly) / max(s * l, 1e-6)
        res.append({"index": i, "is_stall": bool(ok and fill > 0.85), "short_m": round(s, 2), "long_m": round(l, 2),
                    "score": round(float(fill) if ok else 0.0, 2)})
    return res
