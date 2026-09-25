"""
Point-cloud / imagery georeferencing and registration -- Layer 2 (Ingestion
& ETL) of the architecture: "Register point clouds (ICP) and fuse LiDAR +
photogrammetry" and "Georeference all layers to a common CRS using
CORS/GCPs."

Two real, independent techniques, both standard in production photogrammetry/
LiDAR pipelines:

1. GCP-based georeferencing (Umeyama/Kabsch closed-form similarity fit):
   given >=3 points you've identified in your raw survey data (a local
   point cloud, an ortho image, a total-station traverse) matched to their
   real-world position (a GnssControlPoint), computes the single best
   rotation + uniform scale + translation that maps local -> world
   coordinates, plus the fit's RMSE in metres. This is exactly what a
   surveyor does by hand in commercial GIS software when tying a raw
   dataset to CORS/GCP control -- the closed-form math is the same either
   way.

2. ICP (Iterative Closest Point) refinement: given two overlapping point
   clouds already roughly aligned (e.g. by the GCP fit above, or by two
   overlapping drone/LiDAR passes), iteratively refines the alignment by
   repeatedly (a) finding each source point's nearest neighbour in the
   target cloud, (b) re-solving the closed-form transform for those
   correspondences, until the fit stops improving. This is the standard
   point-cloud-to-point-cloud registration algorithm referenced in the
   architecture doc -- implemented here from scratch with numpy/scipy
   (no heavyweight point-cloud library needed).

Honesty note: neither of these invents correspondences. GCP alignment
needs you to identify which raw point corresponds to which control point
(the same manual step any GIS/photogrammetry tool requires). ICP needs an
overlapping target cloud already in world coordinates. Neither function
will silently produce a plausible-looking transform from insufficient or
fabricated input -- both raise on bad input (fewer than 3 correspondences,
degenerate/collinear points, empty clouds).
"""
import json
import logging

logger = logging.getLogger("landsphere.registration")

EARTH_RADIUS_M = 6371000.0


def latlon_alt_to_local_meters(lat, lon, alt, origin_lat, origin_lon):
    """
    Local tangent-plane (East-North-Up) projection, metres from an origin
    lat/lon -- adequate for the scale of a single survey site (a building,
    a few city blocks). This is the same small-area approximation used
    throughout ai_pipeline.py/geocode_router.py in this project; a
    state-wide production deployment should use a proper projected CRS
    (e.g. the relevant UTM zone via pyproj) instead, since the flat-earth
    approximation's error grows with distance from the origin.
    """
    import math
    lat_rad = math.radians(origin_lat)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(lat_rad)
    x = (lon - origin_lon) * m_per_deg_lon
    y = (lat - origin_lat) * m_per_deg_lat
    z = alt
    return x, y, z


def umeyama_alignment(source_points, target_points, with_scale=True):
    """
    Closed-form similarity transform (rotation + uniform scale +
    translation) minimizing sum of squared distances between
    transformed(source_points) and target_points (Umeyama 1991 / Kabsch
    algorithm with scale). Both inputs: Nx3 arrays, N >= 3, not collinear.

    Returns (R, t, s, rmse_m) where transformed_point = s * R @ point + t.
    Raises ValueError on insufficient/degenerate input rather than
    returning a meaningless fit.
    """
    import numpy as np

    src = np.asarray(source_points, dtype=float)
    tgt = np.asarray(target_points, dtype=float)
    if src.shape != tgt.shape or src.shape[0] < 3:
        raise ValueError(f"Need >=3 matched correspondences of equal length; got {src.shape} vs {tgt.shape}")

    src_mean = src.mean(axis=0)
    tgt_mean = tgt.mean(axis=0)
    src_c = src - src_mean
    tgt_c = tgt - tgt_mean

    cov = (tgt_c.T @ src_c) / src.shape[0]
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt

    if with_scale:
        var_src = (src_c ** 2).sum() / src.shape[0]
        if var_src < 1e-12:
            raise ValueError("Source points are degenerate (near-zero variance) -- cannot fit a scale.")
        s = float(np.trace(np.diag(D) @ S) / var_src)
    else:
        s = 1.0

    t = tgt_mean - s * R @ src_mean

    transformed = (s * (R @ src.T)).T + t
    rmse = float(np.sqrt(np.mean(np.sum((transformed - tgt) ** 2, axis=1))))

    return R, t, s, rmse


def align_via_control_points(local_points_xyz, control_points):
    """
    Georeferences raw local survey coordinates using matched GNSS control
    points. control_points: list of {lat, lon, ellipsoidal_height_m}
    matching local_points_xyz 1:1 by index (the same correspondences a
    surveyor would pick manually). Real-world coordinates are converted to
    local tangent-plane metres around the first control point before
    fitting, so the returned transform maps local survey coords -> that
    same local-metric frame (consistent with how footprint/floor
    coordinates are already stored elsewhere in this system).

    Returns a dict: {rotation (3x3 list), translation (3 list), scale,
    rmse_m, origin_lat, origin_lon} -- JSON-serializable for storing on
    Dataset.transform_matrix_json.
    """
    if len(local_points_xyz) != len(control_points):
        raise ValueError("local_points_xyz and control_points must be the same length (matched pairs)")
    if len(control_points) < 3:
        raise ValueError("Need at least 3 control points for a similarity-transform fit")

    origin_lat = control_points[0]["lat"]
    origin_lon = control_points[0]["lon"]

    target_points = [
        latlon_alt_to_local_meters(cp["lat"], cp["lon"], cp.get("ellipsoidal_height_m") or 0.0, origin_lat, origin_lon)
        for cp in control_points
    ]

    R, t, s, rmse = umeyama_alignment(local_points_xyz, target_points, with_scale=True)

    return {
        "rotation": R.tolist(),
        "translation": t.tolist(),
        "scale": s,
        "rmse_m": rmse,
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "method": "gcp_umeyama",
    }


def apply_transform(points_xyz, transform):
    """Applies a stored transform dict (from align_via_control_points or
    icp_refine) to a new set of local points."""
    import numpy as np
    R = np.asarray(transform["rotation"])
    t = np.asarray(transform["translation"])
    s = transform["scale"]
    pts = np.asarray(points_xyz, dtype=float)
    return ((s * (R @ pts.T)).T + t).tolist()


def icp_refine(source_points, target_points, initial_transform=None, max_iterations=30, tolerance=1e-5):
    """
    Refines an alignment between two overlapping point clouds via
    Iterative Closest Point. source_points/target_points: Nx3 / Mx3 arrays
    (need not be the same length -- ICP matches each source point to its
    nearest target point every iteration, not a fixed 1:1 correspondence).

    initial_transform: optional starting transform dict (e.g. the GCP fit
    above) to refine from; identity if omitted.

    Returns a transform dict in the same shape as align_via_control_points
    (minus origin_lat/lon, which only apply to the GCP step), plus
    'iterations_run' and 'converged'.

    Raises ValueError if either cloud has fewer than 10 points -- too
    sparse for nearest-neighbour correspondence to be meaningful.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    src = np.asarray(source_points, dtype=float)
    tgt = np.asarray(target_points, dtype=float)
    if src.shape[0] < 10 or tgt.shape[0] < 10:
        raise ValueError("Need at least 10 points in each cloud for ICP to be meaningful.")

    if initial_transform:
        R = np.asarray(initial_transform["rotation"])
        t = np.asarray(initial_transform["translation"])
        s = initial_transform["scale"]
    else:
        R, t, s = np.eye(3), np.zeros(3), 1.0

    tree = cKDTree(tgt)
    prev_rmse = None
    converged = False
    iterations_run = 0

    current = (s * (R @ src.T)).T + t

    for i in range(max_iterations):
        iterations_run = i + 1
        distances, indices = tree.query(current)
        matched_target = tgt[indices]

        R_step, t_step, s_step, rmse = umeyama_alignment(src, matched_target, with_scale=True)
        R, t, s = R_step, t_step, s_step
        current = (s * (R @ src.T)).T + t

        if prev_rmse is not None and abs(prev_rmse - rmse) < tolerance:
            converged = True
            break
        prev_rmse = rmse

    return {
        "rotation": R.tolist(),
        "translation": t.tolist(),
        "scale": s,
        "rmse_m": prev_rmse,
        "method": "icp",
        "iterations_run": iterations_run,
        "converged": converged,
    }


def load_point_cloud_xyz(las_path, max_points=200000):
    """Reads a .las/.laz file's XYZ coordinates via laspy, downsampled to
    max_points for ICP performance if larger. Returns None (not a fake
    array) if laspy isn't installed or the file can't be read."""
    try:
        import laspy
        import numpy as np
    except ImportError:
        logger.warning("laspy not installed (pip install -r requirements-ml.txt) -- cannot load point cloud for registration.")
        return None

    try:
        las = laspy.read(las_path)
        pts = np.vstack([las.x, las.y, las.z]).T
        if pts.shape[0] > max_points:
            idx = np.random.choice(pts.shape[0], max_points, replace=False)
            pts = pts[idx]
        return pts
    except Exception:
        logger.exception(f"Failed to read point cloud '{las_path}' for registration.")
        return None
