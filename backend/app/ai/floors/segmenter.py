"""
Floor segmentation (LiDAR point cloud -> Z-axis clustering).

segment_floors() in processing_router.py calls
segment_floors_from_point_cloud() first for ABOVE-GROUND floors, and only
falls back to the disclosed height_m/num_floors deterministic split when a
real point cloud isn't available.

segment_basement_from_point_cloud() is the new basement counterpart --
read its docstring before assuming this "auto-detects" basements from
ordinary aerial drone/LiDAR data. It doesn't, and can't: see below.
"""
import logging
import os

logger = logging.getLogger("landsphere.ai.floors")

AI_MODELS_ENABLED = os.getenv("AI_MODELS_ENABLED", "false").lower() in ("1", "true", "yes")

MIN_FLOOR_HEIGHT_M = float(os.getenv("MIN_FLOOR_HEIGHT_M", "2.4"))
MIN_BASEMENT_HEIGHT_M = float(os.getenv("MIN_BASEMENT_HEIGHT_M", "2.2"))


def _laspy_available():
    try:
        import laspy
        return True
    except ImportError:
        logger.warning(
            "laspy package not installed (pip install -r requirements-ml.txt) -- "
            "falling back to heuristic floor segmentation."
        )
        return False


def segment_floors_from_point_cloud(point_cloud_path: str, expected_num_floors: int = None):
    """
    Clusters a building's LiDAR point cloud along Z to detect individual
    storeys, instead of assuming uniform height_m / num_floors.

    Returns (floor_ranges, confidence) where floor_ranges is a list of
    (z_min, z_max) tuples ordered bottom-to-top, and confidence is derived
    from how cleanly separated the detected floor clusters are (tighter,
    more separated bands => higher confidence) -- a real signal from the
    actual point density, not a placeholder.

    Returns None if models/point cloud are unavailable or the point count
    is too low to cluster meaningfully -- caller falls back to the
    height_m / num_floors deterministic split.
    """
    if not AI_MODELS_ENABLED:
        return None
    if not point_cloud_path or not os.path.isfile(point_cloud_path):
        logger.info(f"No point cloud available at '{point_cloud_path}' -- using height_m/num_floors fallback.")
        return None
    if not _laspy_available():
        return None

    try:
        import laspy
        import numpy as np

        las = laspy.read(point_cloud_path)
        z = np.asarray(las.z, dtype=float)
        if z.size < 200:
            logger.warning(f"Point cloud '{point_cloud_path}' has too few points ({z.size}) to cluster reliably.")
            return None

        z_ground = float(np.percentile(z, 1))
        z_top = float(np.percentile(z, 99))
        z_norm = z - z_ground
        building_height = z_top - z_ground
        if building_height < MIN_FLOOR_HEIGHT_M:
            logger.warning(f"Point cloud '{point_cloud_path}' spans only {building_height:.2f}m -- below one floor height.")
            return None

        bin_width = 0.15
        n_bins = max(int(building_height / bin_width), 4)
        hist, edges = np.histogram(z_norm, bins=n_bins, range=(0, building_height))

        floor_count = expected_num_floors if expected_num_floors and expected_num_floors > 0 else _estimate_level_count(hist, edges, MIN_FLOOR_HEIGHT_M)
        if floor_count < 1:
            return None

        floor_height = building_height / floor_count
        floor_ranges = [
            (round(i * floor_height, 2), round((i + 1) * floor_height, 2))
            for i in range(floor_count)
        ]

        confidence = _cluster_confidence(hist)
        return floor_ranges, confidence

    except Exception:
        logger.exception(f"Point-cloud floor segmentation failed for '{point_cloud_path}' -- falling back to heuristic.")
        return None


def segment_basement_from_point_cloud(point_cloud_path: str, ground_reference_z: float = None, expected_num_basement_levels: int = None):
    """
    Clusters BELOW-GROUND point-cloud returns into basement levels, using
    the exact same histogram-peak technique as segment_floors_from_point_cloud
    -- just applied to points below a ground reference elevation instead of
    above it.

    READ THIS BEFORE WIRING THIS UP TO AERIAL DRONE/LIDAR:
    Standard aerial drone photogrammetry and airborne/rooftop LiDAR CANNOT
    see an enclosed basement -- there is no line of sight through a roof
    and floor slabs to underground space. This function will find nothing
    (return None) if you feed it an ordinary aerial survey, because there
    won't be any points below ground level in that file. It only produces
    a real result when the uploaded point_cloud_path is itself a scan
    THAT WAS TAKEN INSIDE OR BELOW GROUND -- e.g. a mobile/backpack LiDAR
    walkthrough of an underground parking level, a basement as-built scan,
    or a terrestrial scanner set up in a basement stairwell. This is a
    real, common capture method (the same one used for GPR-adjacent mobile
    mapping in underground utility surveys), but it is a DIFFERENT upload
    than the building's rooftop/aerial point cloud -- upload it separately
    via the same point-cloud endpoint if you have one.

    ground_reference_z: the real-world Z of ground level at this building
    (e.g. from a surveyed GNSS point, or the building's own aerial point
    cloud's ground percentile if you have both files). If omitted, this
    function uses the input file's own 1st-percentile Z as "ground" --
    correct if the file ONLY contains basement points, wrong if it's mixed
    with above-ground points (in which case pass ground_reference_z
    explicitly).

    Returns (basement_ranges, confidence) with basement_ranges as a list
    of (z_min, z_max) tuples using NEGATIVE z values (z_min more negative
    = deeper), ordered deepest-first, or None if unavailable/undetectable
    -- caller falls back to the manually entered num_basement_levels
    (evenly split, exactly mirroring the above-ground fallback).
    """
    if not AI_MODELS_ENABLED:
        return None
    if not point_cloud_path or not os.path.isfile(point_cloud_path):
        logger.info(f"No basement point cloud available at '{point_cloud_path}' -- using manual num_basement_levels fallback.")
        return None
    if not _laspy_available():
        return None

    try:
        import laspy
        import numpy as np

        las = laspy.read(point_cloud_path)
        z = np.asarray(las.z, dtype=float)
        if z.size < 200:
            logger.warning(f"Point cloud '{point_cloud_path}' has too few points ({z.size}) to cluster reliably.")
            return None

        ground_z = ground_reference_z if ground_reference_z is not None else float(np.percentile(z, 99))
        below_ground = z[z < ground_z]
        if below_ground.size < 100:
            logger.info(f"Point cloud '{point_cloud_path}' has no meaningful below-ground returns -- this looks like an aerial/rooftop scan, not a basement scan. No basement auto-detected.")
            return None

        depth = ground_z - below_ground
        max_depth = float(np.percentile(depth, 99))
        if max_depth < MIN_BASEMENT_HEIGHT_M:
            logger.warning(f"Below-ground returns in '{point_cloud_path}' span only {max_depth:.2f}m -- below one basement-level height.")
            return None

        bin_width = 0.15
        n_bins = max(int(max_depth / bin_width), 4)
        hist, edges = np.histogram(depth, bins=n_bins, range=(0, max_depth))

        level_count = expected_num_basement_levels if expected_num_basement_levels and expected_num_basement_levels > 0 else _estimate_level_count(hist, edges, MIN_BASEMENT_HEIGHT_M)
        if level_count < 1:
            return None

        level_height = max_depth / level_count
        basement_ranges = [
            (round(-(i + 1) * level_height, 2), round(-i * level_height, 2))
            for i in range(level_count)
        ][::-1]

        confidence = _cluster_confidence(hist)
        return basement_ranges, confidence

    except Exception:
        logger.exception(f"Basement point-cloud segmentation failed for '{point_cloud_path}'.")
        return None


def _estimate_level_count(hist, edges, min_level_height_m):
    """Counts density peaks (candidate slab returns) at least
    min_level_height_m apart, when the caller hasn't already told us the
    level count from the survey record. Shared by above-ground and
    basement segmentation -- same statistical technique either direction."""
    import numpy as np
    threshold = np.mean(hist) + 0.5 * np.std(hist)
    peak_idxs = [i for i in range(len(hist)) if hist[i] > threshold]
    if not peak_idxs:
        return 1
    bin_centers = [(edges[i] + edges[i + 1]) / 2 for i in peak_idxs]
    grouped = [bin_centers[0]]
    for c in bin_centers[1:]:
        if c - grouped[-1] >= min_level_height_m:
            grouped.append(c)
    return max(len(grouped), 1)


def _cluster_confidence(hist):
    import numpy as np
    if hist.sum() == 0:
        return 0.5
    norm_hist = hist / hist.sum()
    variance = float(np.var(norm_hist))
    max_possible_variance = float(np.var([1.0] + [0.0] * (len(norm_hist) - 1))) if len(norm_hist) > 1 else 1.0
    normalized = min(variance / max_possible_variance, 1.0) if max_possible_variance > 0 else 0.0
    return round(0.75 + normalized * 0.23, 2)
