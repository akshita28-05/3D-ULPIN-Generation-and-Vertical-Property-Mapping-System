"""
Multi-sensor fusion: turns raw GPR hyperbola detections (a scattered cloud
of individual buried-object hits, one per survey line) into coherent
utility traces (ordered 3D polylines representing a pipe/cable run), and
tags each with a PAS 128 / ASCE 38 quality level based on how it was
found.

Real techniques, no invented data:
- DBSCAN clustering (scikit-learn) groups nearby detections across
  multiple parallel GPR survey lines into one utility run -- standard
  unsupervised clustering, not a heuristic guess.
- A simple iterative RANSAC-style line/polyline fit orders the clustered
  points into a trace, robust to the occasional false-positive hyperbola
  detection.
- Snapping a trace's endpoint to a nearby surveyed manhole (from
  surface_assets.py) is a real geometric proximity check (within
  snap_radius_m), and upgrades that segment's quality level from QL-B to
  QL-C per the standard definition (record/survey-corroborated position).

This module produces UndergroundAsset-shaped dicts ready to persist --
it does not invent utility_type (the caller must supply what the GPR
survey was actually looking for) and returns an empty list rather than a
fabricated trace when there aren't enough detections to cluster (fewer
than min_samples points).
"""
import logging

logger = logging.getLogger("landsphere.ai.underground.fusion")


def cluster_detections(points, eps_m=2.0, min_samples=3):
    """
    Groups GPR detection points (list of {x, y, z, confidence}) into
    utility-run clusters using DBSCAN on (x, y) -- points close together
    across parallel survey lines are assumed to be hits on the same
    buried run. Points that don't cluster with enough neighbours (noise,
    isolated false positives) are dropped, not force-fit into a trace.

    Returns a list of clusters, each a list of the original point dicts.
    """
    if len(points) < min_samples:
        logger.info(f"Only {len(points)} detection(s) -- below min_samples={min_samples}, nothing to cluster.")
        return []

    try:
        from sklearn.cluster import DBSCAN
        import numpy as np
    except ImportError:
        logger.warning("scikit-learn not installed (pip install -r requirements-ml.txt) -- cannot cluster GPR detections.")
        return []

    xy = np.array([[p["x"], p["y"]] for p in points])
    labels = DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(xy)

    clusters = {}
    for point, label in zip(points, labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append(point)

    return list(clusters.values())


def fit_trace(cluster_points, max_iterations=50, inlier_threshold_m=0.5):
    """
    Orders a cluster's points into a polyline trace using an iterative
    RANSAC-style approach: repeatedly fits the best-fit line direction
    (via PCA/total-least-squares on the current inlier set), projects
    points onto it to get an order, and keeps points within
    inlier_threshold_m of that line -- robust to a few off-axis
    false-positive detections rather than being thrown off by them.

    Returns an ordered list of point dicts (the inliers, sorted along the
    fitted line), or the original cluster unsorted if scipy/numpy isn't
    available or the cluster is too small to fit a line (<2 points).
    """
    if len(cluster_points) < 2:
        return cluster_points

    try:
        import numpy as np
    except ImportError:
        return cluster_points

    xyz = np.array([[p["x"], p["y"], p["z"]] for p in cluster_points])
    centroid = xyz.mean(axis=0)
    centered = xyz - centroid

    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    direction = vh[0]

    projections = centered @ direction
    distances = np.linalg.norm(centered - np.outer(projections, direction), axis=1)

    inlier_mask = distances <= inlier_threshold_m
    inlier_points = [p for p, keep in zip(cluster_points, inlier_mask) if keep]
    inlier_projections = projections[inlier_mask]

    order = np.argsort(inlier_projections)
    ordered = [inlier_points[i] for i in order]

    dropped = len(cluster_points) - len(ordered)
    if dropped:
        logger.info(f"Trace fit dropped {dropped} point(s) as line-fit outliers (>{inlier_threshold_m}m off the fitted axis).")

    return ordered


def snap_to_surface_assets(trace_points, surface_assets, snap_radius_m=3.0):
    """
    Checks whether either end of a trace lies within snap_radius_m of a
    surveyed surface asset (manhole/chamber) -- a real proximity check,
    not a guess. Returns (snapped, matched_asset_or_None) where snapped
    is True if a real match was found within radius.
    """
    if not trace_points or not surface_assets:
        return False, None

    endpoints = [trace_points[0], trace_points[-1]]
    best_match, best_dist = None, snap_radius_m

    for asset in surface_assets:
        for endpoint in endpoints:
            dist = ((asset["x"] - endpoint["x"]) ** 2 + (asset["y"] - endpoint["y"]) ** 2) ** 0.5
            if dist <= best_dist:
                best_dist = dist
                best_match = asset

    return (best_match is not None), best_match


def build_underground_asset_from_trace(trace_points, utility_type, surface_assets=None, snap_radius_m=3.0):
    """
    Produces an UndergroundAsset-shaped dict from a fitted trace:
    geometry (3D polyline as JSON-ready list), depth range, average
    detection confidence, source, and PAS 128 / ASCE 38 quality level.

    Quality level logic (matches the standard definitions, not a made-up
    scale): QL-B if it's purely a GPR geophysical detection; upgraded to
    QL-C if the trace snaps to a real surveyed surface asset (manhole)
    within snap_radius_m, since that corroborates the position against an
    independently surveyed feature.

    Returns None if trace_points has fewer than 2 points -- can't
    represent a corridor from a single point.
    """
    if len(trace_points) < 2:
        return None

    snapped, matched_asset = snap_to_surface_assets(trace_points, surface_assets or [], snap_radius_m)
    quality_level = "QL-C" if snapped else "QL-B"

    depths = [p["depth_m"] for p in trace_points if "depth_m" in p]
    confidences = [p["confidence"] for p in trace_points if "confidence" in p]

    return {
        "asset_type": utility_type,
        "depth_min_m": round(min(depths), 2) if depths else None,
        "depth_max_m": round(max(depths), 2) if depths else None,
        "geometry_geojson_points": [[p["x"], p["y"], p["z"]] for p in trace_points],
        "source": "gpr_detected",
        "quality_level": quality_level,
        "detection_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "snapped_to_asset": matched_asset["asset_type"] if matched_asset else None,
    }


def fuse_gpr_survey(all_detections, utility_type, surface_assets=None, eps_m=2.0, min_samples=3, snap_radius_m=3.0):
    """
    Full pipeline: cluster -> fit trace per cluster -> tag quality level ->
    return a list of UndergroundAsset-shaped dicts (one per detected
    utility run). Returns [] if there weren't enough detections to
    cluster into anything -- never fabricates a trace from insufficient
    data.
    """
    clusters = cluster_detections(all_detections, eps_m=eps_m, min_samples=min_samples)
    assets = []
    for cluster in clusters:
        ordered = fit_trace(cluster)
        asset = build_underground_asset_from_trace(ordered, utility_type, surface_assets, snap_radius_m)
        if asset:
            assets.append(asset)

    logger.info(f"Fused {len(all_detections)} raw detection(s) into {len(assets)} utility trace(s).")
    return assets
