"""
Scaffold for converting building-footprint annotations (GeoJSON/COCO/
shapefile, whatever your source dataset ships) into YOLO segmentation
format (one .txt per image, normalized polygon points per line):

    <class_id> x1 y1 x2 y2 x3 y3 ... xn yn   (all coords 0-1, normalized)

This file intentionally does NOT ship a specific converter for one named
dataset, because the right converter depends on which dataset/annotation
format you actually pull (SpaceNet ships GeoJSON polygons in image CRS;
Open Cities AI ships COCO-style; your own CVAT export ships COCO or
YOLO directly). Fill in `convert_one_image()` for your source format --
the loop/IO scaffolding around it is done for you.
"""
import json
import os
from pathlib import Path


def normalize_polygon(polygon_px, img_w, img_h):
    """[(x_px, y_px), ...] -> flat normalized list [x1,y1,x2,y2,...]"""
    flat = []
    for x, y in polygon_px:
        flat.append(round(x / img_w, 6))
        flat.append(round(y / img_h, 6))
    return flat


def convert_one_image(annotation, img_w, img_h, class_id=0):
    """
    Fill this in for your source annotation format. `annotation` is
    whatever one record of your source dataset looks like (a GeoJSON
    feature, a COCO annotation dict, etc.) -- it must yield one or more
    pixel-space polygons for buildings in this image.

    Returns a list of label lines, e.g.:
        ["0 0.12 0.34 0.15 0.36 0.20 0.30", ...]
    """
    raise NotImplementedError(
        "Implement this for your source dataset's annotation format. "
        "See the SpaceNet / Open Cities AI / your CVAT export docs for the exact schema."
    )


def write_yolo_dataset(images_dir, annotations_by_image, output_dir, class_id=0):
    """
    images_dir: directory of source images
    annotations_by_image: {image_filename: [annotation, ...]}
    output_dir: where images/ and labels/ subfolders get written
    """
    out_images = Path(output_dir) / "images"
    out_labels = Path(output_dir) / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    for filename, annotations in annotations_by_image.items():
        src_path = Path(images_dir) / filename
        if not src_path.exists():
            continue
        with Image.open(src_path) as img:
            w, h = img.size

        lines = []
        for ann in annotations:
            lines.extend(convert_one_image(ann, w, h, class_id=class_id))

        label_path = out_labels / (Path(filename).stem + ".txt")
        label_path.write_text("\n".join(lines))

        dest_img = out_images / filename
        if not dest_img.exists():
            os.symlink(src_path.resolve(), dest_img)

    print(f"Wrote YOLO-seg dataset to {output_dir} ({len(annotations_by_image)} images)")


if __name__ == "__main__":
    print(__doc__)
