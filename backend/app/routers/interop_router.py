"""
Interoperability export: CityJSON 1.1 (OGC community standard for 3D city
models), so the 3D ULPIN model can be opened in standard 3D-cadastre / GIS
tooling and not only in this app.

  Building      -> type "Building"      (LoD1 solid extruded from its footprint)
  Unit          -> type "BuildingUnit"  (solid between its z_min..z_max) with the
                                         3D ULPIN as an attribute, child of its Building

Heights are metres ABOVE LOCAL GROUND (no terrain model is applied), stated in
the metadata. The data model follows the LADM (ISO 19152) idea already used in
this project: Spatial Unit + Rights/Restrictions/Responsibilities.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import models, georef
from ..auto_pipeline import floor_evidence_state, FLOOR_HEIGHT_M
from ..database import get_db

router = APIRouter(prefix="/api/interop", tags=["interop"])


def _signed_area(ring):
    return sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring))) / 2.0


class _Vertices:
    def __init__(self):
        self.items = []

    def add(self, lon, lat, z):
        self.items.append([round(lon, 8), round(lat, 8), round(z, 3)])
        return len(self.items) - 1


def _prism_solid(vertices: _Vertices, ring_latlon, z0, z1):
    """Closed [[lat, lon], ...] ring -> CityJSON Solid boundaries for an extruded prism."""
    pts = [(lon, lat) for lat, lon in ring_latlon[:-1]] if ring_latlon[0] == ring_latlon[-1] else [(lon, lat) for lat, lon in ring_latlon]
    if len(pts) < 3:
        return None
    if _signed_area(pts) < 0:
        pts.reverse()  # counter-clockwise from above -> outward-facing top face
    bottom = [vertices.add(x, y, z0) for x, y in pts]
    top = [vertices.add(x, y, z1) for x, y in pts]
    n = len(pts)
    faces = [[list(reversed(bottom))], [top]]
    for i in range(n):
        j = (i + 1) % n
        faces.append([[bottom[i], bottom[j], top[j], top[i]]])
    return [faces]


def _cityjson(db: Session, pairs, title: str):
    resolver = georef.OriginResolver(db)
    vertices = _Vertices()
    objects = {}
    for building, parcel in pairs:
        points = georef.parse_points(building.footprint_geojson)
        ring = resolver.ring_latlon(parcel, points)
        if not ring:
            continue
        height = building.height_m or ((building.num_floors or 0) * FLOOR_HEIGHT_M) or FLOOR_HEIGHT_M
        solid = _prism_solid(vertices, ring, 0.0, height)
        if solid is None:
            continue
        bid = f"building-{building.id}"
        children = []
        for floor in sorted(building.floors, key=lambda f: f.floor_number):
            for unit in floor.units:
                uring = resolver.ring_latlon(parcel, georef.parse_points(unit.footprint_geojson))
                usolid = _prism_solid(vertices, uring, unit.z_min or 0.0, unit.z_max or height) if uring else None
                if usolid is None:
                    continue
                uid = f"unit-{unit.id}"
                children.append(uid)
                objects[uid] = {
                    "type": "BuildingUnit", "parents": [bid],
                    "attributes": {
                        "ulpin_3d": unit.ulpin_3d, "property_type": unit.parcel_type,
                        "floor": floor.floor_code, "area_sqm": unit.area_sqm, "volume_cum": unit.volume_cum,
                        "z_min_m": unit.z_min, "z_max_m": unit.z_max,
                        "verification_status": unit.verification_status.value if hasattr(unit.verification_status, "value") else unit.verification_status,
                    },
                    "geometry": [{"type": "Solid", "lod": "1", "boundaries": usolid}],
                }
        objects[bid] = {
            "type": "Building",
            "attributes": {
                "ulpin_2d": parcel.ulpin_2d, "name": building.name, "building_type": building.building_type,
                "storeys_above_ground": building.num_floors, "measured_height_m": building.height_m,
                "floor_count_evidence": floor_evidence_state(building),
            },
            "geometry": [{"type": "Solid", "lod": "1", "boundaries": solid}],
            **({"children": children} if children else {}),
        }
    return {
        "type": "CityJSON", "version": "1.1",
        "metadata": {
            "title": title,
            "referenceSystem": "https://www.opengis.net/def/crs/OGC/0/CRS84h",
            "description": (
                "Vasudha 3D prototype export. Heights are metres above local ground (no terrain applied). "
                "3D ULPINs are PROPOSED identifiers for the SIH26011 prototype, not official DoLR issuance."
            ),
        },
        "CityObjects": objects,
        "vertices": vertices.items,
    }


def _download(doc, filename):
    return JSONResponse(doc, media_type="application/city+json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/cityjson/parcels/{parcel_id}")
def cityjson_for_parcel(parcel_id: str, db: Session = Depends(get_db)):
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    pairs = [(b, parcel) for b in parcel.buildings]
    return _download(_cityjson(db, pairs, f"Parcel {parcel.ulpin_2d}"), f"{parcel.ulpin_2d}.city.json")


@router.get("/cityjson")
def cityjson_for_area(
    south: float, west: float, north: float, east: float, limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.Building, models.Parcel)
        .join(models.Parcel, models.Parcel.id == models.Building.parcel_id)
        .filter(models.Parcel.centroid_lat.between(south, north), models.Parcel.centroid_lon.between(west, east))
        .limit(limit).all()
    )
    return _download(_cityjson(db, rows, "Vasudha 3D area export"), "vasudha-area.city.json")
