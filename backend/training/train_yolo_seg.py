"""
Trains the YOLOv8-seg building-footprint model that ai_pipeline.py loads
via YOLO_SEG_WEIGHTS_PATH.

You run this yourself, on your own GPU (local/Colab/Kaggle) -- it is NOT
run automatically by the backend, and needs no API key. It needs:
  1. A dataset in YOLO segmentation format (images/ + labels/ with polygon
     masks) -- see prepare_dataset.py in this folder for how to convert
     open building-footprint datasets into that format.
  2. `pip install -r requirements-ml.txt` (ultralytics + deps).

Recommended starting datasets (all public, no key required, but check
each one's license before commercial/production use):
  - SpaceNet Buildings (AWS Open Data, CC-BY-SA)   https://spacenet.ai/spacenet-buildings-dataset/
  - Open Cities AI Challenge (Drivendata, CC-BY)   https://mlhub.earth/data/open_cities_ai_challenge
  - Microsoft Building Footprints (ODbL)           https://github.com/microsoft/GlobalMLBuildingFootprints
None of these are India-specific or drone-native -- treat this as a
pretraining/starting checkpoint, then fine-tune on your own labeled
drone imagery for production accuracy (that's the part that genuinely
needs your own data collection + annotation, e.g. via CVAT/Labelbox on
your DoLR/state drone survey imagery).

Usage:
    python train_yolo_seg.py --data data.yaml --epochs 100 --imgsz 640
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8-seg for building footprint extraction")
    parser.add_argument("--data", required=True, help="Path to a YOLO-seg data.yaml (see dataset_yaml_example below)")
    parser.add_argument("--model", default="yolov8n-seg.pt", help="Base checkpoint to fine-tune from (n/s/m/l/x-seg)")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0", help="'0' for first GPU, 'cpu' for CPU (slow)")
    parser.add_argument("--project", default="runs/building_footprint")
    parser.add_argument("--name", default="yolov8seg_buildings")
    args = parser.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("ultralytics not installed. Run: pip install -r requirements-ml.txt --break-system-packages")

    model = YOLO(args.model)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        task="segment",
    )

    best_weights = f"{args.project}/{args.name}/weights/best.pt"
    print(f"\nTraining complete. Point YOLO_SEG_WEIGHTS_PATH in your .env at:\n  {best_weights}\n")
    return results


DATASET_YAML_EXAMPLE = """
path: /path/to/dataset
train: images/train
val: images/val
names:
  0: building
"""

if __name__ == "__main__":
    main()
