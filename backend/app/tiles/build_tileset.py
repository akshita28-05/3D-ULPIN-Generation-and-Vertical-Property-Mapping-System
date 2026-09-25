"""
Building/parcel geometry -> Cesium 3D Tiles, for city-scale streaming
instead of shipping full-JSON payloads per request (every unit's
footprint_geojson, on every map pan) the way GisMap.jsx / the /export
endpoints do today.

Pipeline, per parcel:
  1. Each building's footprint_geojson (a local-meters polygon -- see the
     georeferencing note below) is extruded into a simple prism mesh
     (floor + roof + wall quads) up to building.height_m.
  2. The mesh is written as a standalone glTF/GLB using pygltflib.
  3. A 3D Tiles 1.1 tileset.json is emitted with one child tile per
     building, using glTF content directly (1.1 dropped the b3dm wrapper
     requirement for simple non-batched content), positioned via a
     per-tile ENU->ECEF `transform` matrix computed from the parcel's
     centroid_lat/centroid_lon.

Georeferencing assumption (real limitation, not hidden): building
footprints in this schema are stored as local-meter coordinates (see
processing_router.py's _bbox()/extract_building_footprint()), and nothing
in the current schema records the real-world origin those meters are
offset from. This pipeline treats each building's OWN parcel's
(centroid_lat, centroid_lon) as that origin (local ENU (0,0)) -- correct
only if a building's footprint coordinates were captured/entered relative
to its parcel's centroid. If buildings are re-surveyed with real GNSS
control points (see GnssControlPoint / registration.py), swap this for the
actual registered origin per building instead.

Triangulation assumption: uses a simple fan triangulation of each
footprint ring, which is only correct for convex polygons. Every footprint
this app currently generates (bounding-box grids in
processing_router.delineate_units, YOLOv8-seg boxes) is convex/rectangular,
so this holds today -- swap in a proper ear-clipping triangulator (e.g.
mapbox_earcut) before feeding in arbitrary hand-drawn concave footprints.

Dependencies: pip install pygltflib (see requirements.txt).
"""
import json
import math
import os
from dataclasses import dataclass

import numpy as np
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Buffer, BufferView,
    Accessor, Asset, ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, UNSIGNED_INT,
    FLOAT, SCALAR, VEC3,
)

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def geodetic_to_ecef(lat_deg: float, lon_deg: float, height_m: float = 0.0):
    """WGS84 lat/lon/height -> Earth-Centered Earth-Fixed X,Y,Z (meters)."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + height_m) * cos_lat * math.cos(lon)
    y = (n + height_m) * cos_lat * math.sin(lon)
    z = (n * (1 - WGS84_E2) + height_m) * sin_lat
    return x, y, z


def enu_to_ecef_transform(lat_deg: float, lon_deg: float, height_m: float = 0.0):
    """
    4x4 column-major transform matrix (as 3D Tiles' `transform` expects)
    mapping a tile's local East-North-Up meters to ECEF -- i.e. "place
    this tile's local origin at (lat, lon, height), oriented so +X is
    East, +Y is North, +Z is Up". Cesium composes this with the
    glTF-internal geometry automatically; we don't need to touch the mesh
    vertices' frame beyond building them in local ENU meters.
    """
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    x0, y0, z0 = geodetic_to_ecef(lat_deg, lon_deg, height_m)

    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)

    east = (-sin_lon, cos_lon, 0.0)
    north = (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)

    return [
        east[0], east[1], east[2], 0.0,
        north[0], north[1], north[2], 0.0,
        up[0], up[1], up[2], 0.0,
        x0, y0, z0, 1.0,
    ]


def _fan_triangulate(n: int):
    """Indices for a fan triangulation of an n-vertex convex ring (0-indexed)."""
    return [(0, i, i + 1) for i in range(1, n - 1)]


@dataclass
class ExtrudedMesh:
    positions: np.ndarray
    indices: np.ndarray


def extrude_footprint(ring_xy, height_m: float) -> ExtrudedMesh:
    """
    ring_xy: list of [x, y] in local meters (footprint_geojson's own
    format -- the same list processing_router.py already produces/consumes).
    Builds floor (z=0) + roof (z=height_m) + vertical wall quads.
    """
    ring = list(ring_xy)
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    n = len(ring)
    if n < 3:
        raise ValueError("Footprint needs at least 3 distinct vertices to extrude")

    floor_pts = [(x, y, 0.0) for x, y in ring]
    roof_pts = [(x, y, height_m) for x, y in ring]
    positions = np.array(floor_pts + roof_pts, dtype=np.float32)

    tris = []
    for a, b, c in _fan_triangulate(n):
        tris.append((a, c, b))
    for a, b, c in _fan_triangulate(n):
        tris.append((n + a, n + b, n + c))
    for i in range(n):
        j = (i + 1) % n
        f0, f1 = i, j
        r0, r1 = n + i, n + j
        tris.append((f0, f1, r1))
        tris.append((f0, r1, r0))

    indices = np.array(tris, dtype=np.uint32).reshape(-1)
    return ExtrudedMesh(positions=positions, indices=indices)


def mesh_to_glb_bytes(mesh: ExtrudedMesh) -> bytes:
    """Wraps a single extruded mesh into a minimal, valid GLB buffer."""
    positions = mesh.positions.astype(np.float32)
    indices = mesh.indices.astype(np.uint32)

    positions_blob = positions.tobytes()
    indices_blob = indices.tobytes()
    pad = (-len(positions_blob)) % 4
    binary_blob = positions_blob + (b"\x00" * pad) + indices_blob

    gltf = GLTF2(
        asset=Asset(version="2.0", generator="sih_app.tiles.build_tileset"),
        scene=0,
        scenes=[Scene(nodes=[0])],
        nodes=[Node(mesh=0)],
        meshes=[Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0),
            indices=1,
        )])],
        buffers=[Buffer(byteLength=len(binary_blob))],
        bufferViews=[
            BufferView(buffer=0, byteOffset=0, byteLength=len(positions_blob), target=ARRAY_BUFFER),
            BufferView(buffer=0, byteOffset=len(positions_blob) + pad, byteLength=len(indices_blob), target=ELEMENT_ARRAY_BUFFER),
        ],
        accessors=[
            Accessor(
                bufferView=0, componentType=FLOAT, count=len(positions), type=VEC3,
                min=positions.min(axis=0).tolist(), max=positions.max(axis=0).tolist(),
            ),
            Accessor(bufferView=1, componentType=UNSIGNED_INT, count=len(indices), type=SCALAR),
        ],
    )
    gltf.set_binary_blob(binary_blob)
    return b"".join(gltf.save_to_bytes())


def bounding_box_volume(ring_xy, height_m: float):
    """3D Tiles `box` boundingVolume: [centerX, centerY, centerZ, halfX-axis..., halfY-axis..., halfZ-axis...]
    in the tile's own local ENU frame (meters), axis-aligned to East/North/Up."""
    xs = [p[0] for p in ring_xy]
    ys = [p[1] for p in ring_xy]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    hx, hy = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
    return [
        cx, cy, height_m / 2,
        hx, 0, 0,
        0, hy, 0,
        0, 0, height_m / 2,
    ]


def build_tileset_for_parcel(parcel, buildings, output_dir: str) -> dict:
    """
    Writes one .glb per building plus a tileset.json for the parcel into
    output_dir. Returns the tileset.json dict (also written to disk).
    Buildings with no footprint/height (e.g. never processed) are skipped,
    not padded with placeholder geometry.
    """
    os.makedirs(output_dir, exist_ok=True)
    children = []

    for b in buildings:
        if not b.footprint_geojson or not b.height_m:
            continue
        ring = json.loads(b.footprint_geojson)
        mesh = extrude_footprint(ring, b.height_m)
        glb_bytes = mesh_to_glb_bytes(mesh)

        glb_name = f"{b.id}.glb"
        with open(os.path.join(output_dir, glb_name), "wb") as f:
            f.write(glb_bytes)

        children.append({
            "boundingVolume": {"box": bounding_box_volume(ring, b.height_m)},
            "geometricError": 0,
            "transform": enu_to_ecef_transform(parcel.centroid_lat, parcel.centroid_lon),
            "content": {"uri": glb_name},
        })

    tileset = {
        "asset": {"version": "1.1"},
        "geometricError": 200,
        "root": {
            "boundingVolume": {"box": bounding_box_volume(
                [pt for b in buildings if b.footprint_geojson for pt in json.loads(b.footprint_geojson)] or [[0, 0]],
                max((b.height_m or 0) for b in buildings) if buildings else 1,
            )},
            "geometricError": 100,
            "refine": "ADD",
            "children": children,
        },
    }

    with open(os.path.join(output_dir, "tileset.json"), "w") as f:
        json.dump(tileset, f, indent=2)

    return tileset
