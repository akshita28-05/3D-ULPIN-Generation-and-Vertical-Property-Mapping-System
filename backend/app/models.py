"""
SQLAlchemy models — the full data schema for the 3D ULPIN system.

Geometry is stored as JSON text (a list of [x,y] / [x,y,z] coordinates)
for SQLite portability. In production on PostgreSQL+PostGIS, swap these
`geometry_json` columns for `geoalchemy2.Geometry("POLYGONZ", srid=4326)`
columns — the rest of the schema (relationships, constraints, indexes)
carries over unchanged.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, ForeignKey, Text, Boolean,
    Enum as SAEnum, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from .database import Base, IS_POSTGIS

if IS_POSTGIS:
    from geoalchemy2 import Geometry


def gen_id():
    return str(uuid.uuid4())


class RightTypeEnum(str, enum.Enum):
    """LADM (ISO 19152) Right types attachable to any spatial unit."""
    ownership = "ownership"
    lease = "lease"
    mortgage = "mortgage"
    easement = "easement"
    right_of_way = "right_of_way"
    usufruct = "usufruct"


class RestrictionTypeEnum(str, enum.Enum):
    height_restriction = "height_restriction"
    usage_restriction = "usage_restriction"
    conservation = "conservation"
    setback = "setback"
    encumbrance = "encumbrance"


class SpatialUnitTypeEnum(str, enum.Enum):
    """Which table a Party/RRR row is attached to -- lets one RRR model
    cover surface parcels, flats/units, underground assets, and air-right
    corridors uniformly, per LADM's Spatial Unit concept."""
    parcel = "parcel"
    unit = "unit"
    underground_asset = "underground_asset"
    air_right_corridor = "air_right_corridor"


class RoleEnum(str, enum.Enum):
    surveyor = "surveyor"
    verifier = "verifier"
    admin = "admin"


class VerificationStatus(str, enum.Enum):
    ai_generated = "ai_generated"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    reprocessing = "reprocessing"


class GrievanceStatus(str, enum.Enum):
    submitted = "submitted"
    under_review = "under_review"
    assigned = "assigned"
    resolved = "resolved"
    closed = "closed"
    rejected = "rejected"


class ProcessingStage(str, enum.Enum):
    uploading = "uploading"
    preprocessing = "preprocessing"
    building_extraction = "building_extraction"
    floor_segmentation = "floor_segmentation"
    vertical_delineation = "vertical_delineation"
    reconstruction_3d = "reconstruction_3d"
    ulpin_generation = "ulpin_generation"
    topology_validation = "topology_validation"
    ready_for_review = "ready_for_review"
    failed = "failed"


class ValidationSeverity(str, enum.Enum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"



class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(RoleEnum), nullable=False, default=RoleEnum.surveyor)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LocationCode(Base):
    """Registry mapping a real place NAME (typed by a surveyor into a field
    that expects a government numeric LGD code) to a consistent numeric code.
    Same name always resolves to the same code, so the composed 2D ULPIN is
    always pure digits even when no numeric code was known at entry time."""
    __tablename__ = "location_codes"
    id = Column(String, primary_key=True, default=gen_id)
    field_type = Column(String, nullable=False)
    name_normalized = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("field_type", "name_normalized", name="uq_location_code_name"),
        UniqueConstraint("field_type", "code", name="uq_location_code_value"),
    )


class Parcel(Base):
    """The base 2D ULPIN parcel (14-digit representative ID)."""
    __tablename__ = "parcels"
    id = Column(String, primary_key=True, default=gen_id)
    ulpin_2d = Column(String(120), unique=True, nullable=False, index=True)
    state_code = Column(String(2))
    district_code = Column(String(2))
    subdistrict_code = Column(String(3))
    village_code = Column(String(3))
    plot_code = Column(String(4))
    address = Column(String)
    khasra_number = Column(String, nullable=True)
    land_use = Column(String, nullable=True)
    centroid_lat = Column(Float)
    centroid_lon = Column(Float)
    footprint_geojson = Column(Text)
    area_sqm = Column(Float)
    auto_generated = Column(Boolean, default=False)
    osm_id = Column(String, nullable=True, index=True)
    bulk_import_job_id = Column(String, ForeignKey("bulk_import_jobs.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    if IS_POSTGIS:
        geom = Column(Geometry("POLYGON", srid=4326), nullable=True)

    buildings = relationship("Building", back_populates="parcel", cascade="all, delete-orphan")

    if IS_POSTGIS:
        __table_args__ = (Index("ix_parcels_geom", "geom", postgresql_using="gist"),)


class Building(Base):
    __tablename__ = "buildings"
    id = Column(String, primary_key=True, default=gen_id)
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    building_code = Column(String(4), nullable=False)
    name = Column(String)
    building_type = Column(String)
    building_type_source = Column(String, default="manual")
    num_floors = Column(Integer, default=0)
    height_m = Column(Float)
    num_basement_levels = Column(Integer, default=0)
    footprint_geojson = Column(Text)
    ai_confidence = Column(Float)
    auto_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    drone_image_path = Column(String, nullable=True)
    point_cloud_path = Column(String, nullable=True)
    basement_point_cloud_path = Column(String, nullable=True)
    footprint_source = Column(String, default="manual")
    floor_source = Column(String, default="manual")
    osm_id = Column(String, nullable=True, index=True)
    ms_footprint_id = Column(String, nullable=True, index=True)
    ms_confidence = Column(Float, nullable=True)
    consistency_flag = Column(Boolean, default=False)
    consistency_note = Column(String, nullable=True)
    if IS_POSTGIS:
        geom = Column(Geometry("POLYGON", srid=4326), nullable=True)
    manual_footprint_geojson = Column(Text, nullable=True)
    manual_num_floors = Column(Integer, nullable=True)
    manual_height_m = Column(Float, nullable=True)
    ai_processed_at = Column(DateTime, nullable=True)

    last_change_check_footprint_geojson = Column(Text, nullable=True)
    last_change_check_num_floors = Column(Integer, nullable=True)
    last_change_check_at = Column(DateTime, nullable=True)

    parcel = relationship("Parcel", back_populates="buildings")
    floors = relationship("Floor", back_populates="building", cascade="all, delete-orphan")

    __table_args__ = (
        (UniqueConstraint("parcel_id", "building_code", name="uq_building_per_parcel"),)
        + ((Index("ix_buildings_geom", "geom", postgresql_using="gist"),) if IS_POSTGIS else ())
    )


class Floor(Base):
    __tablename__ = "floors"
    id = Column(String, primary_key=True, default=gen_id)
    building_id = Column(String, ForeignKey("buildings.id"), nullable=False)
    floor_code = Column(String(4), nullable=False)
    floor_number = Column(Integer, nullable=False)
    z_min = Column(Float, nullable=False)
    z_max = Column(Float, nullable=False)
    ai_confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    building = relationship("Building", back_populates="floors")
    units = relationship("Unit", back_populates="floor", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("building_id", "floor_code", name="uq_floor_per_building"),)


class Unit(Base):
    __tablename__ = "units"
    id = Column(String, primary_key=True, default=gen_id)
    floor_id = Column(String, ForeignKey("floors.id"), nullable=False)
    unit_code = Column(String(4), nullable=False)
    ulpin_3d = Column(String(160), unique=True, nullable=False, index=True)
    parcel_type = Column(String)
    footprint_geojson = Column(Text)
    area_sqm = Column(Float)
    volume_cum = Column(Float)
    z_min = Column(Float)
    z_max = Column(Float)
    owner_reference = Column(String)
    ai_confidence = Column(Float)
    verification_status = Column(SAEnum(VerificationStatus), default=VerificationStatus.ai_generated)
    verified_by = Column(String, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    floor = relationship("Floor", back_populates="units")

    __table_args__ = (
        UniqueConstraint("floor_id", "unit_code", name="uq_unit_per_floor"),
    )


class UtilityQualityLevel(str, enum.Enum):
    """PAS 128 / ASCE 38 subsurface utility quality levels -- what
    confidence class a detected/recorded utility segment is tagged with.
    QL-D: existing records only. QL-C: records + surveyed surface features
    (manholes/valve boxes). QL-B: geophysical detection (GPR/EML) gave a
    horizontal position. QL-A: physically exposed/measured (trial pit)."""
    QL_D = "QL-D"
    QL_C = "QL-C"
    QL_B = "QL-B"
    QL_A = "QL-A"


class UndergroundAsset(Base):
    __tablename__ = "underground_assets"
    id = Column(String, primary_key=True, default=gen_id)
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    asset_type = Column(String)
    depth_min_m = Column(Float)
    depth_max_m = Column(Float)
    geometry_geojson = Column(Text)
    source = Column(String, default="manual")
    quality_level = Column(SAEnum(UtilityQualityLevel), default=UtilityQualityLevel.QL_D)
    detection_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    if IS_POSTGIS:
        geom = Column(Geometry("LINESTRING", srid=4326), nullable=True)

        __table_args__ = (Index("ix_underground_assets_geom", "geom", postgresql_using="gist"),)


class AirRightCorridor(Base):
    __tablename__ = "air_right_corridors"
    id = Column(String, primary_key=True, default=gen_id)
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    corridor_type = Column(String)
    height_min_m = Column(Float)
    height_max_m = Column(Float)
    geometry_geojson = Column(Text)
    conflict_status = Column(String, default="none")
    source = Column(String, default="manual")
    detection_confidence = Column(Float, nullable=True)
    height_source = Column(String, nullable=True)
    detection_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    if IS_POSTGIS:
        geom = Column(Geometry("POLYGONZ", srid=4326), nullable=True)

        __table_args__ = (Index("ix_air_right_corridors_geom", "geom", postgresql_using="gist"),)


class InfraFeature(Base):
    """Underground structure or elevated / air-right corridor found AUTOMATICALLY
    in open data (OpenStreetMap) -- no sensor, no manual entry.

    This is the map layer's own store. Where a feature crosses a registered
    parcel, app/infra/service.py::link_to_parcels() also writes the regular
    UndergroundAsset / AirRightCorridor rows (source="osm_auto") so the per-parcel
    3D viewer and the rights registry see it too.

    Vertical extent is always disclosed: `z_source` is "osm_tag" when OSM itself
    carried a depth/height/levels value and "assumed_default" when the number is a
    documented planning default for that structure type (see app/infra/osm_infra.py).
    Position and existence come from OSM either way.
    """
    __tablename__ = "infra_features"
    id = Column(String, primary_key=True, default=gen_id)
    kind = Column(String, nullable=False, index=True)
    subtype = Column(String, nullable=False)
    name = Column(String, nullable=True)
    osm_id = Column(String, nullable=True, index=True)
    geometry_geojson = Column(Text, nullable=False)
    width_m = Column(Float, nullable=True)
    z_min_m = Column(Float, nullable=True)
    z_max_m = Column(Float, nullable=True)
    deck_top_m = Column(Float, nullable=True)
    z_source = Column(String, default="assumed_default")
    confidence = Column(Float, nullable=True)
    source = Column(String, default="osm")
    notes = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)
    cell_key = Column(String, nullable=True, index=True)
    bbox_south = Column(Float, index=True)
    bbox_west = Column(Float, index=True)
    bbox_north = Column(Float, index=True)
    bbox_east = Column(Float, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class InfraScanCell(Base):
    """One grid cell of the open-data scan, so the same area is never fetched twice."""
    __tablename__ = "infra_scan_cells"
    cell_key = Column(String, primary_key=True)
    status = Column(String, default="ok")
    n_features = Column(Integer, default=0)
    message = Column(String, nullable=True)
    scanned_at = Column(DateTime, default=datetime.utcnow)


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(String, primary_key=True, default=gen_id)
    uploaded_by = Column(String, ForeignKey("users.id"))
    dataset_type = Column(String)
    filename = Column(String)
    file_format = Column(String)
    size_bytes = Column(Integer)
    status = Column(String, default="uploaded")
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    crs = Column(String, nullable=True)
    gsd_m_per_px = Column(Float, nullable=True)
    capture_date = Column(DateTime, nullable=True)
    accuracy_m = Column(Float, nullable=True)
    storage_path = Column(String, nullable=True)
    transform_matrix_json = Column(Text, nullable=True)
    registration_rmse_m = Column(Float, nullable=True)
    registered_at = Column(DateTime, nullable=True)


class GnssControlPoint(Base):
    """A CORS/GCP ground-control point used to georeference a dataset --
    Layer 1 (Data Sources & Acquisition) input, referenced by ETL jobs
    during orthorectification / point-cloud registration."""
    __tablename__ = "gnss_control_points"
    id = Column(String, primary_key=True, default=gen_id)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=True)
    label = Column(String)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    ellipsoidal_height_m = Column(Float, nullable=True)
    horizontal_accuracy_m = Column(Float, nullable=True)
    source = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Party(Base):
    """LADM Party: a person or organization holding a right. Deliberately
    minimal and PII-free, same pattern as Unit.owner_reference elsewhere --
    real name/ID data belongs in the existing land-records system this
    would integrate with, not duplicated here."""
    __tablename__ = "parties"
    id = Column(String, primary_key=True, default=gen_id)
    party_type = Column(String, default="individual")
    reference_code = Column(String, unique=True, nullable=False)
    display_label = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RightRestrictionResponsibility(Base):
    """LADM RRR, generalized to attach to ANY spatial unit type (surface
    parcel, flat/unit, underground asset, or air-right corridor) via
    spatial_unit_type + spatial_unit_id -- this is what Layer 4 of the
    architecture calls the Basic Administrative Unit linking spatial units
    to rights. One spatial unit can have several RRR rows (e.g. an
    ownership right plus a height restriction plus a mortgage)."""
    __tablename__ = "rrrs"
    id = Column(String, primary_key=True, default=gen_id)
    spatial_unit_type = Column(SAEnum(SpatialUnitTypeEnum), nullable=False)
    spatial_unit_id = Column(String, nullable=False, index=True)
    party_id = Column(String, ForeignKey("parties.id"), nullable=True)
    right_type = Column(SAEnum(RightTypeEnum), nullable=True)
    restriction_type = Column(SAEnum(RestrictionTypeEnum), nullable=True)
    responsibility_note = Column(String, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    party = relationship("Party")

    __table_args__ = (
        Index("ix_rrr_spatial_unit", "spatial_unit_type", "spatial_unit_id"),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id = Column(String, primary_key=True, default=gen_id)
    building_id = Column(String, ForeignKey("buildings.id"), nullable=True)
    started_by = Column(String, ForeignKey("users.id"))
    stage = Column(SAEnum(ProcessingStage), default=ProcessingStage.uploading)
    progress_pct = Column(Integer, default=0)
    log = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id = Column(String, primary_key=True, default=gen_id)
    unit_id = Column(String, ForeignKey("units.id"), nullable=True)
    building_id = Column(String, ForeignKey("buildings.id"), nullable=True)
    check_type = Column(String)
    severity = Column(SAEnum(ValidationSeverity), default=ValidationSeverity.low)
    message = Column(String)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Grievance(Base):
    __tablename__ = "grievances"
    id = Column(String, primary_key=True, default=gen_id)
    grievance_number = Column(String, unique=True, nullable=False, index=True)
    unit_id = Column(String, ForeignKey("units.id"), nullable=True)
    building_id = Column(String, ForeignKey("buildings.id"), nullable=True)
    category = Column(String)
    description = Column(Text)
    reporter_contact = Column(String, nullable=True)
    status = Column(SAEnum(GrievanceStatus), default=GrievanceStatus.submitted)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(String)
    entity_type = Column(String)
    entity_id = Column(String)
    previous_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    record_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChangeDetection(Base):
    __tablename__ = "change_detections"
    id = Column(String, primary_key=True, default=gen_id)
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=True)
    date_before = Column(String)
    date_after = Column(String)
    description = Column(String)
    confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationStatus(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    failed = "failed"
    dev_logged = "dev_logged"


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    recipient_email = Column(String, nullable=False)
    event_type = Column(String)
    subject = Column(String)
    body = Column(Text)
    status = Column(SAEnum(NotificationStatus), default=NotificationStatus.queued)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)


class BulkImportJob(Base):
    """
    Tracks the bounding-box OSM bulk-import pipeline: Select (draw a bbox
    on the map) -> Process (fetch + persist all buildings in that box) ->
    View (open the result in the 3D viewer). Separate from ProcessingJob,
    which tracks one building's AI extraction pipeline -- this tracks one
    bulk-import run covering potentially thousands of buildings at once.
    """
    __tablename__ = "bulk_import_jobs"
    id = Column(String, primary_key=True, default=gen_id)
    started_by = Column(String, ForeignKey("users.id"))
    status = Column(String, default="pending")
    south = Column(Float)
    west = Column(Float)
    north = Column(Float)
    east = Column(Float)
    search_query = Column(String, nullable=True)
    source = Column(String, default="osm")
    total_buildings = Column(Integer, default=0)
    processed_buildings = Column(Integer, default=0)
    flagged_buildings = Column(Integer, default=0)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ExternalBuildingFootprint(Base):
    """
    Staging table for offline-loaded satellite-ML building footprint
    datasets (Microsoft Global ML Building Footprints, and any similar
    dataset later) -- see scripts/load_ms_footprints.py and
    app/ingestion/ms_footprints.py. Populated ONCE per downloaded
    quadkey file, then queried by bbox from bulk_import_router.py the
    same way OSM is queried live -- except this is a local table lookup,
    since these datasets are only available as bulk downloads, not a
    live API like Overpass.

    Deliberately separate from Parcel/Building: importing a row from here
    into a real Parcel/Building (via POST /api/bulk-import/commit with
    source="ms_footprints") is a distinct, explicit step -- loading this
    table does not, by itself, create any ULPIN records.
    """
    __tablename__ = "external_building_footprints"
    id = Column(String, primary_key=True, default=gen_id)
    source = Column(String, default="ms_building_footprints")
    quadkey = Column(String, nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    height_m = Column(Float, nullable=True)
    centroid_lat = Column(Float, nullable=False, index=True)
    centroid_lon = Column(Float, nullable=False, index=True)
    footprint_latlon_geojson = Column(Text, nullable=False)
    imported_at = Column(DateTime, default=datetime.utcnow)


class ChangeRequestStatus(str, enum.Enum):
    pending_owner = "pending_owner"
    owner_approved = "owner_approved"
    owner_declined = "owner_declined"
    applied = "applied"
    rejected = "rejected"


class ChangeRequest(Base):
    """
    Ownership lifecycle: once a unit is verified its geometry is a LOCKED
    BASELINE. It can't be edited in place any more -- a change has to be
    proposed here, approved by the rights-holder (via a one-time link, no
    citizen account needed), and only then applied by an officer, which
    locks a new baseline and writes the audit trail. Directly answers the
    SIH26011 goal "reduce ownership conflicts and ambiguities".
    """
    __tablename__ = "change_requests"
    id = Column(String, primary_key=True, default=gen_id)
    unit_id = Column(String, ForeignKey("units.id"), nullable=False, index=True)
    requested_by = Column(String, ForeignKey("users.id"), nullable=True)
    change_type = Column(String, default="geometry")
    proposed_json = Column(Text, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(SAEnum(ChangeRequestStatus), default=ChangeRequestStatus.pending_owner)
    owner_token_hash = Column(String, nullable=True, index=True)
    owner_decided_at = Column(DateTime, nullable=True)
    applied_by = Column(String, ForeignKey("users.id"), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    officer_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    unit = relationship("Unit")
