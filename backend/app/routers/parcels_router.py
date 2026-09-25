import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List

from .. import models, schemas, auth, lifecycle
from ..database import get_db

router = APIRouter(prefix="/api", tags=["parcels"])


@router.post("/parcels", response_model=schemas.ParcelOut)
def create_parcel(
    payload: schemas.ParcelCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """Real parcel creation from user-entered values — no random or hardcoded
    geometry. The 14-digit ULPIN is composed from the codes the user enters,
    following the real government digit structure."""
    from .. import ulpin as ulpin_service
    try:
        ulpin_2d = ulpin_service.generate_2d_ulpin(
            db, payload.state_code, payload.district_code, payload.subdistrict_code,
            payload.village_code, payload.plot_code,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    if db.query(models.Parcel).filter(models.Parcel.ulpin_2d == ulpin_2d).first():
        raise HTTPException(status_code=400, detail=f"A parcel with ULPIN {ulpin_2d} already exists")

    try:
        pts = json.loads(payload.footprint_geojson)
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="footprint_geojson must be a JSON array of at least 3 [x,y] points")

    area = _polygon_area(pts)

    parcel = models.Parcel(
        ulpin_2d=ulpin_2d, state_code=payload.state_code, district_code=payload.district_code,
        subdistrict_code=payload.subdistrict_code, village_code=payload.village_code,
        plot_code=payload.plot_code, address=payload.address,
        khasra_number=payload.khasra_number, land_use=payload.land_use,
        centroid_lat=payload.centroid_lat, centroid_lon=payload.centroid_lon,
        footprint_geojson=payload.footprint_geojson, area_sqm=round(area, 2),
    )
    db.add(parcel)
    db.commit()
    db.refresh(parcel)
    return parcel


@router.post("/buildings", response_model=schemas.BuildingOut)
def create_building(
    payload: schemas.BuildingCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier")),
):
    """Real building creation — footprint, floors, height, and type all come
    from what the user actually enters. No random dimensions are generated
    here or later in the processing pipeline for this building."""
    parcel = db.query(models.Parcel).filter(models.Parcel.id == payload.parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    try:
        pts = json.loads(payload.footprint_geojson)
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="footprint_geojson must be a JSON array of at least 3 [x,y] points")

    if payload.num_floors < 1 or payload.num_floors > 200:
        raise HTTPException(status_code=400, detail="num_floors must be between 1 and 200")

    existing_count = db.query(models.Building).filter(models.Building.parcel_id == parcel.id).count()
    building_code = f"B{existing_count + 1:02d}"

    building = models.Building(
        parcel_id=parcel.id, building_code=building_code, name=payload.name,
        building_type=payload.building_type, num_floors=payload.num_floors,
        height_m=payload.height_m, num_basement_levels=payload.num_basement_levels,
        footprint_geojson=payload.footprint_geojson,
        ai_confidence=None,
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


def _polygon_area(points):
    """Shoelace formula — real area calculation from actual polygon points."""
    n = len(points)
    area = 0.0
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


@router.get("/location-codes")
def list_location_codes(db: Session = Depends(get_db), field_type: str = None):
    """Transparency endpoint: every real place NAME that has been assigned a
    numeric code so far (see app.ulpin.resolve_numeric_code), so a surveyor
    can see e.g. 'East Singhbhum -> 07' instead of just a bare digit."""
    q = db.query(models.LocationCode)
    if field_type:
        q = q.filter(models.LocationCode.field_type == field_type)
    rows = q.order_by(models.LocationCode.field_type, models.LocationCode.code).all()
    return [
        {"field_type": r.field_type, "display_name": r.display_name, "code": r.code}
        for r in rows
    ]


@router.get("/parcels", response_model=List[schemas.ParcelOut])
def list_parcels(db: Session = Depends(get_db), limit: int = 100, offset: int = 0):
    limit = min(limit, 5000)
    return db.query(models.Parcel).order_by(models.Parcel.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/parcels/{parcel_id}", response_model=schemas.ParcelOut)
def get_parcel(parcel_id: str, db: Session = Depends(get_db)):
    parcel = (
        db.query(models.Parcel)
        .options(joinedload(models.Parcel.buildings).joinedload(models.Building.floors).joinedload(models.Floor.units))
        .filter(models.Parcel.id == parcel_id)
        .first()
    )
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return parcel


@router.get("/buildings/{building_id}", response_model=schemas.BuildingOut)
def get_building(building_id: str, db: Session = Depends(get_db)):
    b = (
        db.query(models.Building)
        .options(joinedload(models.Building.floors).joinedload(models.Floor.units))
        .filter(models.Building.id == building_id)
        .first()
    )
    if not b:
        raise HTTPException(status_code=404, detail="Building not found")
    return b


@router.get("/units/{unit_id}", response_model=schemas.UnitOut)
def get_unit(unit_id: str, db: Session = Depends(get_db)):
    u = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Unit not found")
    return u


@router.get("/search", response_model=List[schemas.SearchResult])
def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    """
    Search across 2D ULPIN, 3D ULPIN, parcel/building/floor/unit codes, and address.
    Supports partial matches for autocomplete-style search-as-you-type.
    """
    like = f"%{q}%"
    results: List[schemas.SearchResult] = []

    parcels = db.query(models.Parcel).filter(
        (models.Parcel.ulpin_2d.like(like)) | (models.Parcel.address.like(like))
    ).limit(10).all()
    for p in parcels:
        results.append(schemas.SearchResult(result_type="parcel", id=p.id, label=p.address or p.ulpin_2d, ulpin=p.ulpin_2d))

    buildings = db.query(models.Building).filter(
        (models.Building.building_code.like(like)) | (models.Building.name.like(like))
    ).limit(10).all()
    for b in buildings:
        results.append(schemas.SearchResult(
            result_type="building", id=b.id, label=f"{b.name or b.building_code}",
            parent_label=b.parcel.ulpin_2d if b.parcel else None,
        ))

    units = db.query(models.Unit).filter(models.Unit.ulpin_3d.like(like)).limit(20).all()
    for u in units:
        results.append(schemas.SearchResult(
            result_type="unit", id=u.id, label=u.ulpin_3d, ulpin=u.ulpin_3d,
            parent_label=u.floor.building.name if u.floor and u.floor.building else None,
        ))

    if q.isdigit() and len(q) >= 6:
        matching_parcels = db.query(models.Parcel).filter(models.Parcel.ulpin_2d.like(f"{q}%")).all()
        for p in matching_parcels:
            for b in p.buildings:
                for f in b.floors:
                    for u in f.units:
                        if not any(r.id == u.id for r in results):
                            results.append(schemas.SearchResult(
                                result_type="unit", id=u.id, label=f"Floor {f.floor_number} — {u.ulpin_3d}",
                                ulpin=u.ulpin_3d, parent_label=p.ulpin_2d,
                            ))

    return results[:30]



_PARCEL_PATCHABLE = {
    "address", "centroid_lat", "centroid_lon", "footprint_geojson",
    "khasra_number", "land_use",
}
_BUILDING_PATCHABLE = {"name", "building_type", "num_floors", "height_m", "num_basement_levels", "footprint_geojson"}
_FLOOR_PATCHABLE = {"z_min", "z_max"}
_UNIT_PATCHABLE = {
    "parcel_type", "footprint_geojson", "area_sqm", "volume_cum",
    "z_min", "z_max", "owner_reference",
}


@router.patch("/parcels/{parcel_id}", response_model=schemas.ParcelOut)
def update_parcel(
    parcel_id: str, payload: dict, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    for key, value in payload.items():
        if key in _PARCEL_PATCHABLE:
            setattr(parcel, key, value)
    if "footprint_geojson" in payload:
        try:
            pts = json.loads(parcel.footprint_geojson)
            parcel.area_sqm = round(_polygon_area(pts), 2)
        except Exception:
            db.rollback()
            raise HTTPException(status_code=400, detail="footprint_geojson must be a JSON array of at least 3 [x,y] points")
    db.commit()
    db.refresh(parcel)
    return parcel


@router.delete("/parcels/{parcel_id}")
def delete_parcel(
    parcel_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    """Cascades to buildings/floors/units (see Parcel.buildings relationship
    cascade="all, delete-orphan") -- admin-only given the blast radius."""
    parcel = db.query(models.Parcel).filter(models.Parcel.id == parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    db.delete(parcel)
    db.commit()
    return {"deleted": parcel_id}


@router.patch("/buildings/{building_id}", response_model=schemas.BuildingOut)
def update_building(
    building_id: str, payload: dict, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    for key, value in payload.items():
        if key in _BUILDING_PATCHABLE:
            setattr(building, key, value)
    if "footprint_geojson" in payload:
        building.footprint_source = "manual"
    if "num_floors" in payload or "height_m" in payload:
        building.floor_source = "manual"
    db.commit()
    db.refresh(building)
    return building


@router.delete("/buildings/{building_id}")
def delete_building(
    building_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    building = db.query(models.Building).filter(models.Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    db.delete(building)
    db.commit()
    return {"deleted": building_id}


@router.patch("/floors/{floor_id}", response_model=schemas.FloorOut)
def update_floor(
    floor_id: str, payload: dict, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    floor = db.query(models.Floor).filter(models.Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    for key, value in payload.items():
        if key in _FLOOR_PATCHABLE:
            setattr(floor, key, value)
    if floor.z_min is not None and floor.z_max is not None and floor.z_min >= floor.z_max:
        db.rollback()
        raise HTTPException(status_code=400, detail="z_min must be less than z_max")
    db.commit()
    db.refresh(floor)
    return floor


@router.delete("/floors/{floor_id}")
def delete_floor(
    floor_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    floor = db.query(models.Floor).filter(models.Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    db.delete(floor)
    db.commit()
    return {"deleted": floor_id}


@router.patch("/units/{unit_id}", response_model=schemas.UnitOut)
def update_unit(
    unit_id: str, payload: dict, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin")),
):
    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    if lifecycle.is_locked(unit) and any(key in _UNIT_PATCHABLE for key in payload):
        raise HTTPException(status_code=409, detail=lifecycle.LOCKED_MESSAGE)
    for key, value in payload.items():
        if key in _UNIT_PATCHABLE:
            setattr(unit, key, value)
    db.commit()
    db.refresh(unit)
    return unit


@router.delete("/units/{unit_id}")
def delete_unit(
    unit_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    db.delete(unit)
    db.commit()
    return {"deleted": unit_id}
