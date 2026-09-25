"""
GPR (Ground Penetrating Radar) B-scan subsurface utility detection -- the
ONLY sensor in this module that can actually see buried pipes/cables.
Drone RGB and standard aerial LiDAR cannot: they only capture the surface.

A GPR "B-scan" is a 2D radargram image: horizontal axis = position along
the survey line, vertical axis = two-way radar travel time (a proxy for
depth). A buried pipe/cable produces a characteristic hyperbola shape in
this image (the radar "sees" the object from a range of positions as the
antenna passes over it, closest at the apex directly above the object).
Detecting the hyperbola's apex position (survey-line position + travel
time) is the standard first step in GPR-based utility mapping.

This module does two real things:
1. Object detection for hyperbola apexes on a B-scan image (needs a
   trained model -- same disclosed pattern as everywhere else in this
   project: returns None without real weights, never fabricates a hit).
2. REAL physics to convert a detected apex (pixel position + travel time)
   into an actual 3D position + depth: the radar signal velocity in the
   ground depends on the material's dielectric constant, and depth follows
   from two-way travel time. This part has no ML in it and needs no
   trained weights -- it's the same formula every commercial GPR software
   uses.
"""
import logging
import os

logger = logging.getLogger("landsphere.ai.underground.gpr")

GPR_MODEL_ENABLED = os.getenv("GPR_MODEL_ENABLED", "false").lower() in ("1", "true", "yes")
GPR_HYPERBOLA_WEIGHTS_PATH = os.getenv("GPR_HYPERBOLA_WEIGHTS_PATH", "")
GPR_CONF_THRESHOLD = float(os.getenv("GPR_CONF_THRESHOLD", "0.3"))
GPR_DEVICE = os.getenv("GPR_DEVICE", "cpu")

SPEED_OF_LIGHT_M_PER_NS = 0.2998

TYPICAL_DIELECTRIC_CONSTANTS = {
    "dry_sand": 4.0,
    "wet_sand": 25.0,
    "dry_clay": 10.0,
    "wet_clay": 20.0,
    "average_soil": 9.0,
    "concrete": 6.0,
    "asphalt": 4.0,
}
DEFAULT_DIELECTRIC_CONSTANT = TYPICAL_DIELECTRIC_CONSTANTS["average_soil"]

_model = None
_load_attempted = False


def _get_model():
    global _model, _load_attempted
    if _model is not None:
        return _model
    if _load_attempted:
        return None
    _load_attempted = True

    if not GPR_HYPERBOLA_WEIGHTS_PATH:
        logger.info("GPR_HYPERBOLA_WEIGHTS_PATH not set -- GPR hyperbola detection unavailable.")
        return None
    if not os.path.isfile(GPR_HYPERBOLA_WEIGHTS_PATH):
        logger.warning(f"GPR_HYPERBOLA_WEIGHTS_PATH '{GPR_HYPERBOLA_WEIGHTS_PATH}' does not exist.")
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.warning("ultralytics not installed (pip install -r requirements-ml.txt) -- GPR detection unavailable.")
        return None
    try:
        _model = YOLO(GPR_HYPERBOLA_WEIGHTS_PATH)
        logger.info(f"Loaded GPR hyperbola-detection model from {GPR_HYPERBOLA_WEIGHTS_PATH}")
        return _model
    except Exception:
        logger.exception(f"Failed to load GPR weights from {GPR_HYPERBOLA_WEIGHTS_PATH}")
        _model = None
        return None


def travel_time_to_depth(two_way_time_ns: float, dielectric_constant: float = DEFAULT_DIELECTRIC_CONSTANT) -> float:
    """
    Standard GPR depth formula: depth = (two-way travel time * velocity) / 2,
    where velocity = speed_of_light / sqrt(dielectric_constant).
    Returns depth in metres. This is real, unmodified radar physics -- the
    same formula used in every commercial GPR post-processing package.
    """
    velocity_m_per_ns = SPEED_OF_LIGHT_M_PER_NS / (dielectric_constant ** 0.5)
    return round((two_way_time_ns * velocity_m_per_ns) / 2.0, 3)


def detect_hyperbolas(bscan_image_path: str):
    """
    Runs object detection for hyperbola apexes on a single GPR B-scan
    image. Returns a list of {pixel_x, pixel_y, confidence} -- pixel
    positions within the B-scan image, NOT yet real-world coordinates
    (see convert_detection_to_position for that step, which needs the
    scan's survey-line metadata). Returns None if the model/weights/image
    aren't available.
    """
    if not GPR_MODEL_ENABLED:
        return None
    if not bscan_image_path or not os.path.isfile(bscan_image_path):
        logger.info(f"No B-scan image available at '{bscan_image_path}'.")
        return None

    model = _get_model()
    if model is None:
        return None

    try:
        results = model.predict(source=bscan_image_path, conf=GPR_CONF_THRESHOLD, device=GPR_DEVICE, verbose=False)
    except Exception:
        logger.exception(f"GPR hyperbola inference failed on '{bscan_image_path}'.")
        return None

    if not results or results[0].boxes is None:
        return []

    result = results[0]
    detections = []
    for box, conf in zip(result.boxes.xywh.tolist(), result.boxes.conf.tolist()):
        cx_px, cy_px, _, _ = box
        detections.append({"pixel_x": round(cx_px, 1), "pixel_y": round(cy_px, 1), "confidence": round(float(conf), 3)})
    return detections


def convert_detection_to_position(detection, scan_line, image_width_px, image_height_px):
    """
    Converts one hyperbola-apex detection (pixel coords in the B-scan
    image) into a real 3D position, using the survey line's real GNSS
    trajectory + GPR scan parameters.

    scan_line: {
      "start_lat", "start_lon", "end_lat", "end_lon",  -- real GNSS trajectory endpoints of this GPR pass
      "time_window_ns",                                 -- the B-scan's total vertical time window (a real GPR acquisition setting)
      "dielectric_constant" (optional, defaults to average soil),
      "origin_lat", "origin_lon"                         -- local-metre projection origin, shared with the rest of the site (pass the same origin used elsewhere so coordinates line up)
    }

    Returns {x, y, z, depth_m} in local metres (z is negative = below
    ground), or None if scan_line is missing required fields.
    """
    required = {"start_lat", "start_lon", "end_lat", "end_lon", "time_window_ns", "origin_lat", "origin_lon"}
    if not required.issubset(scan_line.keys()):
        logger.warning(f"scan_line missing required fields {required - scan_line.keys()} -- cannot convert detection to position.")
        return None

    from ..registration.alignment import latlon_alt_to_local_meters

    fraction_along_line = detection["pixel_x"] / max(image_width_px, 1)
    lat = scan_line["start_lat"] + (scan_line["end_lat"] - scan_line["start_lat"]) * fraction_along_line
    lon = scan_line["start_lon"] + (scan_line["end_lon"] - scan_line["start_lon"]) * fraction_along_line

    two_way_time_ns = (detection["pixel_y"] / max(image_height_px, 1)) * scan_line["time_window_ns"]
    dielectric = scan_line.get("dielectric_constant", DEFAULT_DIELECTRIC_CONSTANT)
    depth_m = travel_time_to_depth(two_way_time_ns, dielectric)

    x, y, _ = latlon_alt_to_local_meters(lat, lon, 0.0, scan_line["origin_lat"], scan_line["origin_lon"])

    return {"x": round(x, 3), "y": round(y, 3), "z": -depth_m, "depth_m": depth_m}


def process_gpr_survey_line(bscan_image_path: str, scan_line: dict, image_width_px: int, image_height_px: int):
    """
    End-to-end: detect hyperbolas on one B-scan, convert each to a real 3D
    position. Returns a list of {x, y, z, depth_m, confidence}, or None if
    detection was unavailable (model/weights/image missing).
    """
    detections = detect_hyperbolas(bscan_image_path)
    if detections is None:
        return None

    positioned = []
    for d in detections:
        pos = convert_detection_to_position(d, scan_line, image_width_px, image_height_px)
        if pos:
            pos["confidence"] = d["confidence"]
            positioned.append(pos)
    return positioned
