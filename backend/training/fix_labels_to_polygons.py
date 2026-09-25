"""
Fixes a common Roboflow export quirk: a dataset exported for "YOLOv8"
sometimes mixes real polygon annotations with plain bounding boxes (5
fields: class xc yc w h) in the same label set. ultralytics' segmentation
trainer needs every line to be a polygon, so this converts every
bbox-only line into its 4-corner rectangle as a degenerate polygon.

Honesty note: a box-derived label only gives you a RECTANGULAR mask for
that building, not its real footprint shape (an L-shaped or irregular
building will be masked as its bounding rectangle). Only the labels that
were already real polygons give true footprint shapes. This script lets
you train immediately on 100% of the images, but for production accuracy
you should prioritize adding/fixing real polygon labels over time
(re-annotate the box-only images in Roboflow/CVAT with the polygon tool)
rather than treating this conversion as a permanent fix.

Usage:
    python fix_labels_to_polygons.py --dataset /path/to/dataset --out /path/to/dataset_fixed
"""
import argparse
import shutil
from pathlib import Path


def bbox_to_polygon(class_id, xc, yc, w, h):
    x0, y0 = xc - w / 2, yc - h / 2
    x1, y1 = xc + w / 2, yc + h / 2
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(1.0, x1), min(1.0, y1)
    return f"{class_id} {x0:.6f} {y0:.6f} {x1:.6f} {y0:.6f} {x1:.6f} {y1:.6f} {x0:.6f} {y1:.6f}"


def convert_label_file(src_path: Path, dst_path: Path):
    lines_out = []
    box_count, poly_count = 0, 0
    for line in src_path.read_text().splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        nfields = len(parts)
        class_id = int(parts[0])
        if nfields == 5:
            xc, yc, w, h = map(float, parts[1:])
            lines_out.append(bbox_to_polygon(class_id, xc, yc, w, h))
            box_count += 1
        elif nfields >= 7 and nfields % 2 == 1:
            lines_out.append(line.strip())
            poly_count += 1
        else:
            print(f"  WARNING: skipping malformed line in {src_path.name}: '{line.strip()}'")
    dst_path.write_text("\n".join(lines_out) + ("\n" if lines_out else ""))
    return box_count, poly_count


def convert_split(dataset_dir: Path, out_dir: Path, split: str):
    src_labels = dataset_dir / split / "labels"
    src_images = dataset_dir / split / "images"
    if not src_labels.exists():
        return 0, 0, 0
    dst_labels = out_dir / split / "labels"
    dst_images = out_dir / split / "images"
    dst_labels.mkdir(parents=True, exist_ok=True)
    dst_images.mkdir(parents=True, exist_ok=True)

    total_box, total_poly, n_images = 0, 0, 0
    for label_file in src_labels.glob("*.txt"):
        b, p = convert_label_file(label_file, dst_labels / label_file.name)
        total_box += b
        total_poly += p
        n_images += 1

    for img_file in src_images.iterdir():
        shutil.copy2(img_file, dst_images / img_file.name)

    return n_images, total_box, total_poly


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="Path to the original Roboflow export (has train/valid/test)")
    parser.add_argument("--out", required=True, help="Output path for the fixed dataset")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    out_dir = Path(args.out)

    for split in ("train", "valid", "test"):
        n_images, n_box, n_poly = convert_split(dataset_dir, out_dir, split)
        if n_images:
            print(f"{split}: {n_images} images | {n_poly} real-polygon labels kept | {n_box} bbox labels converted to rectangles")

    data_yaml = f"""path: {out_dir.resolve()}
train: train/images
val: valid/images
test: test/images

nc: 1
names: ['building']
"""
    (out_dir / "data.yaml").write_text(data_yaml)
    print(f"\nWrote fixed dataset + data.yaml to {out_dir.resolve()}")


if __name__ == "__main__":
    main()
