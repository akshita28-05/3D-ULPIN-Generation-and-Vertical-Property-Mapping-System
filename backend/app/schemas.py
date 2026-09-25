from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, ConfigDict


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    name: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str
    role: str
    is_active: bool


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    unit_code: str
    ulpin_3d: str
    parcel_type: Optional[str]
    footprint_geojson: Optional[str]
    area_sqm: Optional[float]
    volume_cum: Optional[float]
    z_min: Optional[float]
    z_max: Optional[float]
    owner_reference: Optional[str]
    ai_confidence: Optional[float]
    verification_status: str


class FloorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    floor_code: str
    floor_number: int
    z_min: float
    z_max: float
    ai_confidence: Optional[float]
    units: List[UnitOut] = []


class BuildingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    building_code: str
    name: Optional[str]
    building_type: Optional[str]
    building_type_source: str = "manual"
    num_floors: Optional[int] = None
    height_m: Optional[float]
    num_basement_levels: int = 0
    footprint_geojson: Optional[str]
    ai_confidence: Optional[float]
    auto_generated: bool = False
    footprint_source: str = "manual"
    floor_source: str = "manual"
    osm_id: Optional[str] = None
    ms_footprint_id: Optional[str] = None
    ms_confidence: Optional[float] = None
    consistency_flag: bool = False
    consistency_note: Optional[str] = None
    drone_image_path: Optional[str] = None
    point_cloud_path: Optional[str] = None
    basement_point_cloud_path: Optional[str] = None
    manual_footprint_geojson: Optional[str] = None
    manual_num_floors: Optional[int] = None
    manual_height_m: Optional[float] = None
    ai_processed_at: Optional[datetime] = None
    floors: List[FloorOut] = []


class ParcelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ulpin_2d: str
    address: Optional[str]
    khasra_number: Optional[str] = None
    land_use: Optional[str] = None
    centroid_lat: Optional[float]
    centroid_lon: Optional[float]
    footprint_geojson: Optional[str]
    area_sqm: Optional[float]
    auto_generated: bool = False
    osm_id: Optional[str] = None
    buildings: List[BuildingOut] = []


class SearchResult(BaseModel):
    result_type: str
    id: str
    label: str
    ulpin: Optional[str] = None
    parent_label: Optional[str] = None


class GrievanceCreate(BaseModel):
    unit_id: Optional[str] = None
    building_id: Optional[str] = None
    category: str
    description: str
    reporter_contact: Optional[str] = None


class GrievanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    grievance_number: str
    unit_id: Optional[str]
    building_id: Optional[str] = None
    category: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime


class GrievanceStatusUpdate(BaseModel):
    status: str
    assigned_to: Optional[str] = None


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    unit_id: Optional[str]
    building_id: Optional[str]
    check_type: str
    severity: str
    message: str
    resolved: bool
    created_at: datetime


class ProcessingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    building_id: Optional[str]
    stage: str
    progress_pct: int
    log: str
    created_at: datetime
    updated_at: datetime


class StartProcessingRequest(BaseModel):
    building_id: str


class DetectFootprintsRequest(BaseModel):
    crop_box: Optional[List[float]] = None


class FootprintCandidateOut(BaseModel):
    index: int
    confidence: float
    polygon_m: List[List[float]]
    bbox_px: List[float]


class DetectFootprintsResponse(BaseModel):
    building_id: str
    drone_image_path: str
    crop_box: Optional[List[float]] = None
    candidates: List[FootprintCandidateOut]
    ai_models_enabled: bool


class SelectFootprintRequest(BaseModel):
    candidate_index: int


class DetectFloorsRequest(BaseModel):
    crop_box: Optional[List[float]] = None


class FloorEstimateOut(BaseModel):
    floor_count: int
    height_m: float
    confidence: float
    band_count: int


class DetectFloorsResponse(BaseModel):
    building_id: str
    drone_image_path: str
    crop_box: Optional[List[float]] = None
    estimate: Optional[FloorEstimateOut] = None
    ai_models_enabled: bool
    current_num_floors: int
    current_height_m: Optional[float] = None


class SelectFloorsRequest(BaseModel):
    pass


class ParcelCreate(BaseModel):
    state_code: str
    district_code: str
    subdistrict_code: str
    village_code: str
    plot_code: str
    address: str
    khasra_number: Optional[str] = None
    land_use: Optional[str] = None
    centroid_lat: float
    centroid_lon: float
    footprint_geojson: str


class BuildingCreate(BaseModel):
    parcel_id: str
    name: str
    building_type: str
    num_floors: int
    height_m: float
    num_basement_levels: int = 0
    footprint_geojson: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class SystemStatusOut(BaseModel):
    redis_backed: bool
    smtp_configured: bool
    database_type: str
    database_url_masked: str


class AutoGenerateRequest(BaseModel):
    address: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    recipient_email: str
    event_type: str
    subject: str
    status: str
    error_message: Optional[str]
    created_at: datetime
    sent_at: Optional[datetime]


class UnitReviewAction(BaseModel):
    action: str
    edited_footprint_geojson: Optional[str] = None
    edited_z_min: Optional[float] = None
    edited_z_max: Optional[float] = None
    note: Optional[str] = None


class BulkReviewAction(BaseModel):
    action: str
    note: Optional[str] = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: Optional[str]
    action: str
    entity_type: str
    entity_id: str
    previous_value: Optional[str]
    new_value: Optional[str]
    record_hash: str
    created_at: datetime


class PendingModelRunOut(BaseModel):
    """A building still on footprint_source == 'manual' despite having
    imagery and/or a point cloud already uploaded for it -- i.e. a real
    model run would change something but hasn't been triggered yet.
    Surfaced by GET /api/processing/pending-model-run so surveyors have a
    single worklist instead of having to open every building to check."""
    building_id: str
    building_code: str
    building_name: Optional[str] = None
    parcel_id: str
    parcel_ulpin_2d: str
    parcel_address: Optional[str] = None
    has_drone_image: bool
    has_point_cloud: bool
    has_basement_point_cloud: bool
    footprint_source: str
    floor_source: str
    already_processed: bool
    created_at: datetime


class AnalyticsOut(BaseModel):
    total_parcels: int
    total_buildings: int
    total_units: int
    verified_units: int
    pending_units: int
    rejected_units: int
    active_conflicts: int
    open_grievances: int
    processing_jobs_running: int


class PartyCreate(BaseModel):
    party_type: str = "individual"
    reference_code: str
    display_label: Optional[str] = None


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    party_type: str
    reference_code: str
    display_label: Optional[str]
    created_at: datetime


class RRRCreate(BaseModel):
    spatial_unit_type: str
    spatial_unit_id: str
    party_id: Optional[str] = None
    right_type: Optional[str] = None
    restriction_type: Optional[str] = None
    responsibility_note: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class RRROut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    spatial_unit_type: str
    spatial_unit_id: str
    party_id: Optional[str]
    right_type: Optional[str]
    restriction_type: Optional[str]
    responsibility_note: Optional[str]
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_at: datetime
    party: Optional[PartyOut] = None


class GnssControlPointCreate(BaseModel):
    dataset_id: Optional[str] = None
    label: str
    latitude: float
    longitude: float
    ellipsoidal_height_m: Optional[float] = None
    horizontal_accuracy_m: Optional[float] = None
    source: Optional[str] = None


class GnssControlPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_id: Optional[str]
    label: str
    latitude: float
    longitude: float
    ellipsoidal_height_m: Optional[float]
    horizontal_accuracy_m: Optional[float]
    source: Optional[str]
    created_at: datetime
