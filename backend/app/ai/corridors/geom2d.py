"""Small dependency-free 2-D geometry helpers (numpy only) so the corridor
detectors run and test without shapely/PostGIS. Coordinates: local metres."""
import math
import numpy as np


def polygon_area(pts):
    p = np.asarray(pts, float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0


def points_in_polygon(xs, ys, poly):
    """Vectorised even-odd ray casting."""
    p = np.asarray(poly, float)
    if len(p) > 1 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    inside = np.zeros(np.shape(xs), bool)
    n = len(p)
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = p[i, 0], p[i, 1], p[j, 0], p[j, 1]
        cond = ((yi > ys) != (yj > ys)) & (xs < (xj - xi) * (ys - yi) / ((yj - yi) or 1e-12) + xi)
        inside ^= cond
        j = i
    return inside


def overlap_area(a, b, res=0.25):
    """Intersection area of two polygons via raster sampling (error ~ res*perimeter).
    Fine for corridor-vs-building conflict tests; not a survey-grade boolean op."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    x0 = max(a[:, 0].min(), b[:, 0].min()); x1 = min(a[:, 0].max(), b[:, 0].max())
    y0 = max(a[:, 1].min(), b[:, 1].min()); y1 = min(a[:, 1].max(), b[:, 1].max())
    if x1 <= x0 or y1 <= y0:
        return 0.0
    gx, gy = np.meshgrid(np.arange(x0 + res / 2, x1, res), np.arange(y0 + res / 2, y1, res))
    m = points_in_polygon(gx, gy, a) & points_in_polygon(gx, gy, b)
    return float(m.sum()) * res * res


def min_distance(a, b, res=0.5):
    """Approx. min distance between two polygon outlines (dense-sampled)."""
    def dense(p):
        p = np.asarray(p, float); out = []
        for i in range(len(p) - 1):
            n = max(2, int(np.hypot(*(p[i + 1] - p[i])) / res))
            out.append(np.linspace(p[i], p[i + 1], n))
        return np.vstack(out) if out else p
    A, B = dense(a), dense(b)
    d = np.sqrt(((A[:, None, :] - B[None, :, :]) ** 2).sum(-1))
    return float(d.min())


def buffer_polyline(line, width_m):
    """Polygon of a polyline widened to width_m (mitre joins, mitre length capped)."""
    p = np.asarray(line, float)
    if len(p) < 2:
        return []
    h = width_m / 2.0
    seg = np.diff(p, axis=0)
    ln = np.hypot(seg[:, 0], seg[:, 1]); keep = ln > 1e-9
    p = np.vstack([p[0], p[1:][keep]]) if len(p) > 1 else p
    seg = np.diff(p, axis=0)
    if len(seg) == 0:
        return []
    d = seg / np.hypot(seg[:, 0], seg[:, 1])[:, None]
    nrm = np.stack([-d[:, 1], d[:, 0]], 1)
    left, right = [p[0] + nrm[0] * h], [p[0] - nrm[0] * h]
    for i in range(1, len(p) - 1):
        m = nrm[i - 1] + nrm[i]
        mm = np.dot(m, m)
        if mm < 1e-9:
            off = nrm[i] * h
        else:
            off = m / mm * 2.0 * h
            if np.hypot(*off) > 2.5 * h:
                off = nrm[i] * h
        left.append(p[i] + off); right.append(p[i] - off)
    left.append(p[-1] + nrm[-1] * h); right.append(p[-1] - nrm[-1] * h)
    poly = left + right[::-1]
    poly.append(poly[0])
    return [[float(x), float(y)] for x, y in poly]


def clip_line_to_box(line, xmin, ymin, xmax, ymax):
    """Liang-Barsky clip of each segment; returns list of polylines inside the box."""
    out, cur = [], []
    for (x0, y0), (x1, y1) in zip(line[:-1], line[1:]):
        dx, dy = x1 - x0, y1 - y0
        t0, t1 = 0.0, 1.0
        ok = True
        for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
            if abs(p) < 1e-12:
                if q < 0:
                    ok = False; break
            else:
                t = q / p
                if p < 0:
                    t0 = max(t0, t)
                else:
                    t1 = min(t1, t)
        if not ok or t0 > t1:
            if len(cur) > 1:
                out.append(cur)
            cur = []
            continue
        a = [x0 + t0 * dx, y0 + t0 * dy]; b = [x0 + t1 * dx, y0 + t1 * dy]
        if cur and np.allclose(cur[-1], a):
            cur.append(b)
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = [a, b]
    if len(cur) > 1:
        out.append(cur)
    return out


def is_convex(poly):
    p = np.asarray(poly, float)
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    s = 0
    n = len(p)
    for i in range(n):
        a, b, c = p[i], p[(i + 1) % n], p[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) < 1e-9:
            continue
        sg = 1 if cr > 0 else -1
        if s == 0:
            s = sg
        elif sg != s:
            return False
    return True


def clip_polygon_convex(subject, clip):
    """Sutherland-Hodgman: clip `subject` (any simple polygon) by CONVEX `clip`."""
    c = np.asarray(clip, float)
    if np.allclose(c[0], c[-1]):
        c = c[:-1]
    area2 = np.dot(c[:, 0], np.roll(c[:, 1], -1)) - np.dot(c[:, 1], np.roll(c[:, 0], -1))
    if area2 < 0:
        c = c[::-1]
    out = [tuple(p) for p in np.asarray(subject, float)]
    if out and out[0] == out[-1]:
        out = out[:-1]
    for i in range(len(c)):
        a, b = c[i], c[(i + 1) % len(c)]
        inp, out = out, []
        if not inp:
            break
        def side(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        def inter(p, q):
            sp, sq = side(p), side(q)
            t = sp / (sp - sq)
            return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
        for j in range(len(inp)):
            cur, prev = inp[j], inp[j - 1]
            if side(cur) >= 0:
                if side(prev) < 0:
                    out.append(inter(prev, cur))
                out.append(cur)
            elif side(prev) >= 0:
                out.append(inter(prev, cur))
    if len(out) < 3:
        return []
    out.append(out[0])
    return [[float(x), float(y)] for x, y in out]


def oriented_rect(points):
    """PCA-oriented bounding rectangle -> (polygon, length, width, angle_rad)."""
    p = np.asarray(points, float)
    c = p.mean(0)
    u, s, vt = np.linalg.svd(p - c, full_matrices=False)
    ax = vt[0]; ay = vt[1]
    a = (p - c) @ ax; b = (p - c) @ ay
    a0, a1, b0, b1 = a.min(), a.max(), b.min(), b.max()
    corners = [c + ax * a0 + ay * b0, c + ax * a1 + ay * b0, c + ax * a1 + ay * b1, c + ax * a0 + ay * b1]
    corners.append(corners[0])
    return [[float(x), float(y)] for x, y in corners], float(a1 - a0), float(b1 - b0), math.atan2(ax[1], ax[0])
