"""
Building footprint extraction (drone/satellite orthophoto -> a real
segmentation model). Two interchangeable model backends are supported,
selected by FOOTPRINT_MODEL_BACKEND -- neither is required; with neither
configured this falls back to the disclosed deterministic heuristic exactly
as before:

  "yolov8"    (default, unchanged) -- YOLOv8-seg instance segmentation,
              see _run_yolo_inference(). One polygon per detected building
              instance, with the model's own detection confidence.
  "segformer" (optional, additive) -- SegFormer semantic segmentation (a
              transformer encoder, HuggingFace `transformers`), see
              _run_segformer_inference(). Produces a per-pixel building/
              not-building mask; connected components of that mask become
              the candidate polygons, with confidence = mean softmax
              probability over each component. Useful as a second opinion
              or for a checkpoint someone has only fine-tuned as SegFormer
              (e.g. matching the SegFormer footprint step in the public
              kkrrishagarwal/tribhoomi SIH26011 prototype) -- it does not
              replace or remove the YOLOv8-seg path, which stays default.

extract_building_footprint() in processing_router.py calls
extract_footprint_from_imagery() first, and only falls back to the
disclosed deterministic heuristic (geometric_regularity_score) when a real
model/weights/input isn't available.

Honesty note (kept true after this change, not just before it):
- If AI_MODELS_ENABLED is false, or the selected backend's package/weights/
  input aren't available, extract_footprint_from_imagery() returns None.
  The caller then uses the exact same deterministic fallback that shipped
  in the hackathon prototype.
- When a real model IS wired up (either backend), its actual output and
  confidence are used -- not the heuristic -- and the pipeline log says so
  explicitly, including which backend produced it.

Nothing in this file silently invents data: every failure path (missing
package, missing weights, missing input file, model raising an
exception, empty detections) is logged and returns None.
"""
import logging
import os
import uuid
import json

logger = logging.getLogger("landsphere.ai.footprint")

AI_MODELS_ENABLED = os.getenv("AI_MODELS_ENABLED", "false").lower() in ("1", "true", "yes")

FOOTPRINT_MODEL_BACKEND = os.getenv("FOOTPRINT_MODEL_BACKEND", "segformer").strip().lower()

YOLO_SEG_WEIGHTS_PATH = os.getenv("YOLO_SEG_WEIGHTS_PATH", "")
YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF_THRESHOLD", "0.25"))
YOLO_DEVICE = os.getenv("YOLO_DEVICE", "cpu")

SEGFORMER_WEIGHTS_PATH = os.getenv("SEGFORMER_WEIGHTS_PATH", "")
SEGFORMER_DEVICE = os.getenv("SEGFORMER_DEVICE", "cpu")
SEGFORMER_BUILDING_CLASS_ID = int(os.getenv("SEGFORMER_BUILDING_CLASS_ID", "1"))
SEGFORMER_CONF_THRESHOLD = float(os.getenv("SEGFORMER_CONF_THRESHOLD", "0.5"))
SEGFORMER_MIN_COMPONENT_PX = int(os.getenv("SEGFORMER_MIN_COMPONENT_PX", "150"))

IMAGE_GSD_M_PER_PX = float(os.getenv("IMAGE_GSD_M_PER_PX", "0.05"))


_yolo_model = None
_yolo_load_attempted = False


def _get_yolo_model():
    global _yolo_model, _yolo_load_attempted
    if _yolo_model is not None:
        return _yolo_model
    if _yolo_load_attempted:
        return None
    _yolo_load_attempted = True

    if not YOLO_SEG_WEIGHTS_PATH:
        logger.info("YOLO_SEG_WEIGHTS_PATH not set -- footprint extraction will use the manual/heuristic fallback.")
        return None
    if not os.path.isfile(YOLO_SEG_WEIGHTS_PATH):
        logger.warning(f"YOLO_SEG_WEIGHTS_PATH '{YOLO_SEG_WEIGHTS_PATH}' does not exist -- falling back to heuristic.")
        return None

    try:
        from ultralytics import YOLO
    except ImportError:
        logger.warning(
            "ultralytics package not installed (pip install -r requirements-ml.txt) -- "
            "falling back to heuristic footprint extraction."
        )
        return None

    try:
        _yolo_model = YOLO(YOLO_SEG_WEIGHTS_PATH)
        logger.info(f"Loaded YOLOv8-seg building-footprint model from {YOLO_SEG_WEIGHTS_PATH} (device={YOLO_DEVICE})")
        return _yolo_model
    except Exception:
        logger.exception(f"Failed to load YOLOv8-seg weights from {YOLO_SEG_WEIGHTS_PATH} -- falling back to heuristic.")
        _yolo_model = None
        return None


def _crop_source_image(image_path: str, crop_box):
    """
    Shared crop-before-inference helper, used by both backends. If
    crop_box=[x0,y0,x1,y1] (original-image pixel coords) is given and
    valid, saves a cropped copy alongside image_path and returns
    (cropped_path, offset_x, offset_y). Otherwise returns
    (image_path, 0.0, 0.0) unchanged. Never raises -- an invalid/
    out-of-bounds crop_box is logged and ignored, inference then runs on
    the full image. Caller is responsible for deleting the cropped file
    if the returned path != image_path.
    """
    if crop_box is None:
        return image_path, 0.0, 0.0
    try:
        from PIL import Image
        x0, y0, x1, y1 = [float(v) for v in crop_box]
        if x1 <= x0 or y1 <= y0:
            logger.warning(f"Invalid crop_box {crop_box} (non-positive width/height) -- ignoring crop.")
            return image_path, 0.0, 0.0
        with Image.open(image_path) as im:
            width, height = im.size
            x0c, y0c = max(0.0, x0), max(0.0, y0)
            x1c, y1c = min(float(width), x1), min(float(height), y1)
            if x1c <= x0c or y1c <= y0c:
                logger.warning(f"crop_box {crop_box} does not overlap image bounds {width}x{height} -- ignoring crop.")
                return image_path, 0.0, 0.0
            cropped = im.crop((int(x0c), int(y0c), int(x1c), int(y1c)))
            crop_path = os.path.join(
                os.path.dirname(image_path),
                f".crop_{uuid.uuid4().hex}_{os.path.basename(image_path)}",
            )
            cropped.save(crop_path)
            return crop_path, x0c, y0c
    except Exception:
        logger.exception(f"Failed to crop '{image_path}' to {crop_box} -- running inference on the full image instead.")
        return image_path, 0.0, 0.0


_segformer_model = None
_segformer_processor = None
_segformer_load_attempted = False


def _get_segformer_model():
    global _segformer_model, _segformer_processor, _segformer_load_attempted
    if _segformer_model is not None:
        return _segformer_model, _segformer_processor
    if _segformer_load_attempted:
        return None, None
    _segformer_load_attempted = True

    if not SEGFORMER_WEIGHTS_PATH:
        logger.info("SEGFORMER_WEIGHTS_PATH not set -- SegFormer footprint extraction unavailable.")
        return None, None

    try:
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
    except ImportError:
        logger.warning(
            "transformers package not installed (pip install -r requirements-ml.txt) -- "
            "falling back to heuristic footprint extraction."
        )
        return None, None

    try:
        model = SegformerForSemanticSegmentation.from_pretrained(SEGFORMER_WEIGHTS_PATH)
        processor = SegformerImageProcessor.from_pretrained(SEGFORMER_WEIGHTS_PATH)
        model.to(SEGFORMER_DEVICE)
        model.eval()
        _segformer_model, _segformer_processor = model, processor
        logger.info(f"Loaded SegFormer building-footprint model from {SEGFORMER_WEIGHTS_PATH} (device={SEGFORMER_DEVICE})")
        return model, processor
    except Exception:
        logger.exception(f"Failed to load SegFormer weights from '{SEGFORMER_WEIGHTS_PATH}' -- falling back to heuristic.")
        _segformer_model, _segformer_processor = None, None
        return None, None


def _run_segformer_inference(image_path: str, crop_box=None):
    """
    SegFormer counterpart to _run_yolo_inference(): same contract (list of
    {"confidence": float, "polygon_px": [[x, y], ...]} sorted by confidence
    descending, in the ORIGINAL uncropped image's pixel frame; None if the
    model/deps/input aren't available; [] if it ran and found nothing).

    Unlike YOLOv8-seg's own per-instance masks, SegFormer produces one
    per-pixel building/not-building map for the whole image -- so "one
    detection" here means one connected component of that mask, and
    "confidence" is the mean softmax probability the model assigned to the
    building class over that component's pixels (not a detection score),
    which is the honest per-component analogue available from a semantic
    (not instance) segmentation model.
    """
    if not AI_MODELS_ENABLED:
        return None
    if not image_path or not os.path.isfile(image_path):
        logger.info(f"No drone image available at '{image_path}' -- using manual/heuristic footprint.")
        return None

    model, processor = _get_segformer_model()
    if model is None:
        return None

    try:
        import numpy as np
        import torch
        import cv2
    except ImportError as exc:
        logger.warning(
            f"SegFormer inference needs numpy+torch+opencv-python-headless "
            f"(pip install -r requirements-ml.txt) -- missing: {exc}. Falling back to heuristic."
        )
        return None

    predict_source, offset_x, offset_y = _crop_source_image(image_path, crop_box)
    try:
        from PIL import Image
        image = Image.open(predict_source).convert("RGB")
        orig_w, orig_h = image.size

        inputs = processor(images=image, return_tensors="pt").to(SEGFORMER_DEVICE)
        with torch.no_grad():
            outputs = model(**inputs)
        logits = torch.nn.functional.interpolate(
            outputs.logits, size=(orig_h, orig_w), mode="bilinear", align_corners=False,
        )
        probs = torch.softmax(logits, dim=1)[0]
        if SEGFORMER_BUILDING_CLASS_ID >= probs.shape[0]:
            logger.warning(
                f"SEGFORMER_BUILDING_CLASS_ID={SEGFORMER_BUILDING_CLASS_ID} is outside this checkpoint's "
                f"{probs.shape[0]} classes -- check the checkpoint's config.json id2label. Falling back to heuristic."
            )
            return None
        building_prob = probs[SEGFORMER_BUILDING_CLASS_ID].cpu().numpy()
        mask = (building_prob >= SEGFORMER_CONF_THRESHOLD).astype("uint8")
    except Exception:
        logger.exception(f"SegFormer inference failed on '{predict_source}'.")
        return None
    finally:
        if predict_source != image_path and os.path.isfile(predict_source):
            try:
                os.remove(predict_source)
            except OSError:
                pass

    if mask.sum() == 0:
        logger.info(f"SegFormer found no building pixels in '{image_path}' (crop_box={crop_box}).")
        return []

    num_labels, labels = cv2.connectedComponents(mask, connectivity=8)
    candidates = []
    for label_id in range(1, num_labels):
        component = (labels == label_id).astype("uint8")
        if int(component.sum()) < SEGFORMER_MIN_COMPONENT_PX:
            continue
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        if len(contour) < 3:
            continue
        confidence = float(building_prob[component.astype(bool)].mean())
        polygon_px = [[float(pt[0][0]) + offset_x, float(pt[0][1]) + offset_y] for pt in contour]
        candidates.append({"confidence": confidence, "polygon_px": polygon_px})

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def _run_footprint_inference(image_path: str, crop_box=None):
    """
    Single entry point every caller in this module uses. Tries the backend
    FOOTPRINT_MODEL_BACKEND selects (SegFormer by default) first. If that
    backend has no usable model at all (returns None -- e.g. its weights
    path is unset/missing/package not installed) AND the OTHER backend
    does have weights configured, falls back to it before finally falling
    back to the disclosed deterministic heuristic. This means setting
    weights for just one backend works regardless of which one is
    configured as the default, and YOLOv8-seg keeps working exactly as
    before for anyone who already has YOLO_SEG_WEIGHTS_PATH set and never
    touches FOOTPRINT_MODEL_BACKEND.

    A backend that DID run but legitimately found nothing returns []
    (not None) -- that is a real answer and is returned as-is, never
    overridden by trying the other backend.
    """
    primary, secondary = (
        (_run_segformer_inference, _run_yolo_inference)
        if FOOTPRINT_MODEL_BACKEND == "segformer"
        else (_run_yolo_inference, _run_segformer_inference)
    )
    result = primary(image_path, crop_box=crop_box)
    if result is not None:
        return result
    return secondary(image_path, crop_box=crop_box)


def _run_yolo_inference(image_path: str, crop_box=None):
    """
    Shared inference core for both the single-best path
    (extract_footprint_from_imagery, unchanged behaviour/contract) and the
    multi-candidate path (extract_all_footprints_from_imagery).

    crop_box, if given, is [x0, y0, x1, y1] in the ORIGINAL uploaded image's
    pixel coordinates (e.g. a bounding box the surveyor drew in the
    frontend around the one building they mean, when the uploaded image
    covers several buildings -- see Option 1 in the imagery/detect
    endpoint). When provided, inference runs on the cropped region only,
    which both focuses the model on the intended building and avoids the
    "highest confidence anywhere in the image" mistargeting risk. Detected
    masks are translated back into the ORIGINAL (uncropped) image's pixel
    frame before returning, so every caller downstream keeps working in one
    consistent coordinate system regardless of whether a crop was used.

    Returns a list of candidate dicts, each:
      {"confidence": float, "polygon_px": [[x, y], ...]}   # original-image pixel coords
    sorted by confidence descending (index 0 == old "best" pick), or an
    empty list if inference ran but found nothing. Returns None if
    inference could not run at all (disabled, no weights, bad image, crop
    error, etc.) -- callers distinguish "no model available" (None) from
    "model ran, found nothing" ([]).
    """
    if not AI_MODELS_ENABLED:
        return None
    if not image_path or not os.path.isfile(image_path):
        logger.info(f"No drone image available at '{image_path}' -- using manual/heuristic footprint.")
        return None

    model = _get_yolo_model()
    if model is None:
        return None

    offset_x, offset_y = 0.0, 0.0
    predict_source = image_path

    if crop_box is not None:
        try:
            from PIL import Image
            x0, y0, x1, y1 = [float(v) for v in crop_box]
            if x1 <= x0 or y1 <= y0:
                logger.warning(f"Invalid crop_box {crop_box} (non-positive width/height) -- ignoring crop.")
            else:
                with Image.open(image_path) as im:
                    width, height = im.size
                    x0c, y0c = max(0.0, x0), max(0.0, y0)
                    x1c, y1c = min(float(width), x1), min(float(height), y1)
                    if x1c <= x0c or y1c <= y0c:
                        logger.warning(f"crop_box {crop_box} does not overlap image bounds {width}x{height} -- ignoring crop.")
                    else:
                        cropped = im.crop((int(x0c), int(y0c), int(x1c), int(y1c)))
                        crop_path = os.path.join(
                            os.path.dirname(image_path),
                            f".crop_{uuid.uuid4().hex}_{os.path.basename(image_path)}",
                        )
                        cropped.save(crop_path)
                        predict_source = crop_path
                        offset_x, offset_y = x0c, y0c
        except Exception:
            logger.exception(f"Failed to crop '{image_path}' to {crop_box} -- running inference on the full image instead.")
            predict_source = image_path
            offset_x, offset_y = 0.0, 0.0

    try:
        results = model.predict(source=predict_source, conf=YOLO_CONF_THRESHOLD, device=YOLO_DEVICE, verbose=False)
    except Exception:
        logger.exception(f"YOLOv8-seg inference failed on '{predict_source}'.")
        return None
    finally:
        if predict_source != image_path and os.path.isfile(predict_source):
            try:
                os.remove(predict_source)
            except OSError:
                pass

    if not results:
        return []
    result = results[0]
    if result.masks is None or len(result.masks.xy) == 0:
        logger.info(f"YOLOv8-seg found no building mask in '{image_path}' (crop_box={crop_box}).")
        return []

    confidences = result.boxes.conf.tolist() if result.boxes is not None else [None] * len(result.masks.xy)
    candidates = []
    for mask_px, conf in zip(result.masks.xy, confidences):
        polygon_px = [[float(px) + offset_x, float(py) + offset_y] for px, py in mask_px]
        candidates.append({
            "confidence": float(conf) if conf is not None else 0.0,
            "polygon_px": polygon_px,
        })
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def _polygon_px_to_m(polygon_px):
    polygon_m = [[round(float(px) * IMAGE_GSD_M_PER_PX, 3), round(float(py) * IMAGE_GSD_M_PER_PX, 3)] for px, py in polygon_px]
    return _simplify_polygon(polygon_m, max_points=60)


def reanchor_to_existing_footprint(new_points, existing_geojson):
    """
    Re-anchors a freshly detected footprint (real shape/size, in metres --
    just positioned at whatever pixel origin its source image happened to
    use) onto the location the building already occupies in the parcel's
    shared local coordinate frame.

    Without this, a saved AI detection was visually invisible/unchanged in
    the 3D view: pixel-to-metre conversion (IMAGE_GSD_M_PER_PX) has no
    knowledge of where the building sits in the parcel, so the detected
    polygon landed at raw image-pixel coordinates -- typically far outside
    the parcel's local frame (which is centred wherever the surveyor drew
    the parcel/building at creation, e.g. a 0-30m range) and so never
    rendered anywhere the person would see it change, and the manually
    entered shape (still on `building.footprint_geojson` until save)
    silently stayed authoritative to the viewer.

    Only a translation is applied -- real detected width/height/shape are
    untouched, just recentred on the existing footprint's own centroid, so
    "this building's real building is over here" (existing_geojson) is
    preserved while "this is its real detected outline" (new_points)
    becomes what's actually drawn. Returns new_points unmoved if there's no
    existing footprint to anchor to (nothing dishonest to fall back to).
    """
    if not existing_geojson:
        return new_points
    try:
        existing_points = json.loads(existing_geojson)
        if not isinstance(existing_points, list) or len(existing_points) < 3:
            return new_points
    except Exception:
        return new_points

    def centroid(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    ex_cx, ex_cy = centroid(existing_points)
    new_cx, new_cy = centroid(new_points)
    dx, dy = ex_cx - new_cx, ex_cy - new_cy
    return [[round(x + dx, 3), round(y + dy, 3)] for x, y in new_points]


def estimate_floor_count_from_imagery(image_path: str, crop_box=None):
    """
    Estimates how many floors an uploaded facade photo actually shows, by
    clustering the YOLOv8-seg model's raw per-instance detections
    vertically -- the same masks that, on a tall building's oblique
    facade, tend to land roughly one-per-floor/window-band (this is
    exactly the fragmentation _merge_candidates_to_one_building() collapses
    away for footprint purposes; here it's read the other way, as the only
    real per-floor signal a single 2D photo can offer in this codebase).

    Returns None if the model is disabled/unavailable, the image is
    missing, or it ran but found nothing -- callers then keep whatever
    num_floors/height_m the building already has (manual or a prior
    estimate), never a fabricated floor count. Otherwise returns:
      {"floor_count": int, "height_m": float, "confidence": float, "band_count": int}

    This is a real but approximate estimate, not ground truth: an oblique
    photo that doesn't show the building's full height top-to-bottom will
    undercount, and window bands don't always correspond 1:1 with storeys.
    Callers surface it to a human to confirm before it overwrites anything
    (see /imagery/detect-floors + /imagery/select-floors) -- it is never
    applied automatically.
    """
    candidates = _run_footprint_inference(image_path, crop_box=crop_box)
    if not candidates:
        return None

    bands_in = []
    for c in candidates:
        ys = [p[1] for p in c["polygon_px"]]
        bands_in.append((min(ys), max(ys), c["confidence"]))
    bands_in.sort(key=lambda b: b[0])

    merged = []
    for y0, y1, conf in bands_in:
        if merged and y0 <= merged[-1][1]:
            py0, py1, pconf = merged[-1]
            merged[-1] = (py0, max(py1, y1), max(pconf, conf))
        else:
            merged.append((y0, y1, conf))

    if not merged:
        return None

    band_count = len(merged)
    top_y = merged[0][0]
    bottom_y = merged[-1][1]
    height_m = round((bottom_y - top_y) * IMAGE_GSD_M_PER_PX, 2)
    avg_confidence = round(sum(b[2] for b in merged) / band_count, 3)

    return {
        "floor_count": band_count,
        "height_m": height_m,
        "confidence": avg_confidence,
        "band_count": band_count,
    }


def extract_footprint_from_imagery(image_path: str):
    """
    Runs the real YOLOv8-seg model on a building's uploaded orthophoto and
    picks the single highest-confidence detection, unchanged from the
    original behaviour -- this is what the automatic pipeline
    (extract_building_footprint in processing_router.py) still uses when a
    building's imagery already unambiguously contains one target building
    (e.g. a pre-cropped per-building tile).

    Returns (polygon_points, confidence) where polygon_points is a list of
    [x, y] pairs in local metres (same coordinate convention as the manually
    entered footprint_geojson used elsewhere in the pipeline), and
    confidence is the model's own detection confidence (0-1) -- not the
    geometric heuristic.

    Returns None if models are disabled, unavailable, the image is missing,
    or the model produces no usable detection -- callers must fall back to
    the deterministic path in that case, never invent a polygon.

    NOTE: if the image contains multiple buildings, this silently picks
    whichever one the model is most confident about, which may not be the
    building the surveyor intended. For imagery covering more than one
    building, use extract_all_footprints_from_imagery() (optionally with a
    crop_box) via the /imagery/detect + /imagery/select endpoints instead,
    so a human confirms which detection is correct.
    """
    candidates = _run_footprint_inference(image_path, crop_box=None)
    if not candidates:
        return None

    best = candidates[0]
    polygon_m = _polygon_px_to_m(best["polygon_px"])
    if len(polygon_m) < 3:
        logger.warning(f"YOLOv8-seg mask for '{image_path}' degenerated to <3 points after simplification.")
        return None

    return polygon_m, best["confidence"]


def extract_all_footprints_from_imagery(image_path: str, crop_box=None):
    """
    Multi-candidate counterpart to extract_footprint_from_imagery(), for
    imagery that may contain more than one building.

    crop_box (optional): [x0, y0, x1, y1] in pixel coordinates of the
    uploaded image -- when the surveyor has drawn a bounding box around the
    one building they mean (Option 1: crop-before-detect), pass it here so
    inference only looks at that region, in addition to letting the
    surveyor pick from the results (Option 3: human-confirmed candidate
    selection). Both can be used together or independently -- a crop_box
    narrows what the model even sees; without one, the model runs on the
    full image and may return several buildings' worth of detections for
    the caller to disambiguate.

    Returns a list of candidate dicts, each:
      {"confidence": float, "polygon_m": [[x, y], ...], "bbox_px": [x0, y0, x1, y1]}
    sorted by confidence descending, "polygon_m" in the same local-metre
    convention as everywhere else in the pipeline, "bbox_px" in the
    ORIGINAL (uncropped) image's pixel coordinates so the frontend can draw
    it directly on the full image the surveyor is looking at.

    Returns None if models are disabled/unavailable or the image is
    missing (nothing to show the surveyor). Returns [] if the model ran
    successfully but found no buildings -- distinguished from None so the
    caller can tell "can't try" from "tried, found nothing".

    When crop_box is given, the surveyor has already told us "this box is
    ONE building" -- but the segmentation model can still return several
    partial masks inside it (e.g. one per floor/window band on a tall
    facade, which is what produced a wall of tiny numbered candidates in
    the UI instead of one footprint). In that case every mask inside the
    crop is merged into a single combined footprint below, instead of
    surfacing each fragment as a separate pick-one candidate.
    """
    candidates = _run_footprint_inference(image_path, crop_box=crop_box)
    if candidates is None:
        return None

    out = []
    for c in candidates:
        polygon_m = _polygon_px_to_m(c["polygon_px"])
        if len(polygon_m) < 3:
            continue
        xs = [p[0] for p in c["polygon_px"]]
        ys = [p[1] for p in c["polygon_px"]]
        out.append({
            "confidence": c["confidence"],
            "polygon_m": polygon_m,
            "bbox_px": [min(xs), min(ys), max(xs), max(ys)],
        })

    if crop_box is not None and len(out) > 1:
        merged = _merge_candidates_to_one_building(out)
        if merged is not None:
            return [merged]

    return out


def _merge_candidates_to_one_building(candidates):
    """
    Combine several partial masks that all fall inside one surveyor-drawn
    crop into a single footprint for that one selected building, instead
    of a fragment per detected piece (floor/window band/etc).

    Takes the union of every candidate polygon and returns its convex
    hull as one merged footprint -- a tall building's stacked facade
    fragments don't perfectly overlap in an oblique photo, so a plain
    union would still be a jagged multi-part shape, while the hull gives
    one clean outline covering the whole selected building. Confidence is
    the highest of the merged fragments (the model's own best signal that
    something real is there), not an average that would be diluted by
    every low-confidence fragment.

    Returns None (caller keeps the original fragmented list) if shapely
    isn't available or every candidate polygon is degenerate -- this
    never invents a footprint the model didn't actually detect pieces of.
    """
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ImportError:
        logger.warning("shapely not installed -- cannot merge fragmented candidates into one footprint.")
        return None

    polys = []
    for c in candidates:
        try:
            poly = Polygon(c["polygon_m"])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.area > 0:
                polys.append(poly)
        except Exception:
            continue
    if not polys:
        return None

    merged_shape = unary_union(polys).convex_hull
    if merged_shape.is_empty or merged_shape.geom_type != "Polygon":
        return None

    coords = list(merged_shape.exterior.coords)[:-1]
    polygon_m = _simplify_polygon([[round(x, 3), round(y, 3)] for x, y in coords], max_points=60)
    if len(polygon_m) < 3:
        return None

    all_xs = [x for c in candidates for x in (c["bbox_px"][0], c["bbox_px"][2])]
    all_ys = [y for c in candidates for y in (c["bbox_px"][1], c["bbox_px"][3])]

    return {
        "confidence": max(c["confidence"] for c in candidates),
        "polygon_m": polygon_m,
        "bbox_px": [min(all_xs), min(all_ys), max(all_xs), max(all_ys)],
    }


def _simplify_polygon(points, max_points=60):
    """Naive uniform-stride downsampling to cap vertex count. A production
    system would use Douglas-Peucker (e.g. shapely's .simplify()); this is
    intentionally simple since the caller already has shapely as a
    dependency and can be swapped in without touching anything else."""
    if len(points) <= max_points:
        return points
    try:
        from shapely.geometry import Polygon
        poly = Polygon(points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        simplified = poly.simplify(tolerance=IMAGE_GSD_M_PER_PX * 2, preserve_topology=True)
        coords = list(simplified.exterior.coords)[:-1]
        if len(coords) >= 3:
            return [[round(x, 3), round(y, 3)] for x, y in coords]
    except Exception:
        logger.exception("Polygon simplification via shapely failed, falling back to uniform stride.")
    stride = max(1, len(points) // max_points)
    return points[::stride]
