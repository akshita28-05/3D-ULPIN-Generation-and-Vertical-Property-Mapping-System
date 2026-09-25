"""
Surface utility asset detection: manholes, valve boxes, utility chambers
detected from a drone orthophoto -- the QL-C "surveyed surface feature"
half of underground utility mapping.

This finds things ON the surface that are visible to an ordinary drone
camera. It does not see anything underground -- for buried pipe/cable
detection, see gpr_detection.py, which needs actual subsurface (GPR)
data. The two are combined in fusion.py.

Same disclosed pattern as ai/footprint/extractor.py: returns None (not a
fabricated detection list) whenever the model/weights/image aren't
available, so the pipeline can fall back to "no surface assets detected
yet -- add them manually" rather than pretending to have found something.
"""
import logging
import os

logger = logging.getLogger("landsphere.ai.underground.surface_assets")

SURFACE_ASSET_MODEL_ENABLED = os.getenv("SURFACE_ASSET_MODEL_ENABLED", "false").lower() in ("1", "true", "yes")
SURFACE_ASSET_WEIGHTS_PATH = os.getenv("SURFACE_ASSET_WEIGHTS_PATH", "")
SURFACE_ASSET_CONF_THRESHOLD = float(os.getenv("SURFACE_ASSET_CONF_THRESHOLD", "0.3"))
SURFACE_ASSET_DEVICE = os.getenv("SURFACE_ASSET_DEVICE", "cpu")
IMAGE_GSD_M_PER_PX = float(os.getenv("IMAGE_GSD_M_PER_PX", "0.05"))

CLASS_NAME_TO_ASSET_TYPE = {
    "manhole": "manhole",
    "manhole_cover": "manhole",
    "valve": "valve_box",
    "valve_box": "valve_box",
    "utility_box": "utility_chamber",
    "chamber": "utility_chamber",
    "hydrant": "fire_hydrant",
    "transformer": "transformer",
}

_model = None
_load_attempted = False


def _get_model():
    global _model, _load_attempted
    if _model is not None:
        return _model
    if _load_attempted:
        return None
    _load_attempted = True

    if not SURFACE_ASSET_WEIGHTS_PATH:
        logger.info("SURFACE_ASSET_WEIGHTS_PATH not set -- surface utility-asset detection is unavailable.")
        return None
    if not os.path.isfile(SURFACE_ASSET_WEIGHTS_PATH):
        logger.warning(f"SURFACE_ASSET_WEIGHTS_PATH '{SURFACE_ASSET_WEIGHTS_PATH}' does not exist.")
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.warning("ultralytics not installed (pip install -r requirements-ml.txt) -- surface asset detection unavailable.")
        return None
    try:
        _model = YOLO(SURFACE_ASSET_WEIGHTS_PATH)
        logger.info(f"Loaded surface utility-asset model from {SURFACE_ASSET_WEIGHTS_PATH}")
        return _model
    except Exception:
        logger.exception(f"Failed to load surface asset weights from {SURFACE_ASSET_WEIGHTS_PATH}")
        _model = None
        return None


def detect_surface_assets(image_path: str, origin_xy=(0.0, 0.0)):
    """
    Runs object detection for manholes/valve boxes/chambers on a drone
    orthophoto. origin_xy: the same local-metre origin used elsewhere in
    the pipeline (e.g. the building's footprint bbox origin), so returned
    positions are in the same coordinate frame as footprints/units.

    Returns a list of {asset_type, x, y, confidence} in local metres, or
    None if the model/weights/image aren't available -- never a
    fabricated list.
    """
    if not SURFACE_ASSET_MODEL_ENABLED:
        return None
    if not image_path or not os.path.isfile(image_path):
        logger.info(f"No orthophoto available at '{image_path}' for surface asset detection.")
        return None

    model = _get_model()
    if model is None:
        return None

    try:
        results = model.predict(source=image_path, conf=SURFACE_ASSET_CONF_THRESHOLD, device=SURFACE_ASSET_DEVICE, verbose=False)
    except Exception:
        logger.exception(f"Surface asset inference failed on '{image_path}'.")
        return None

    if not results or results[0].boxes is None:
        return []

    result = results[0]
    detections = []
    ox, oy = origin_xy
    for box, conf, cls_idx in zip(result.boxes.xywh.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist()):
        cx_px, cy_px, _, _ = box
        class_name = result.names.get(int(cls_idx), "unknown")
        asset_type = CLASS_NAME_TO_ASSET_TYPE.get(class_name, class_name)
        detections.append({
            "asset_type": asset_type,
            "x": round(ox + cx_px * IMAGE_GSD_M_PER_PX, 3),
            "y": round(oy + cy_px * IMAGE_GSD_M_PER_PX, 3),
            "confidence": round(float(conf), 3),
        })

    logger.info(f"Detected {len(detections)} surface utility asset(s) in '{image_path}'.")
    return detections
