# Architecture Mapping — SIH26011 (3D ULPIN)

This maps the 6-layer architecture (Data Sources → Ingestion/ETL → 3D
Reconstruction & AI/ML → 3D Cadastral Model & Registry → Services & APIs →
Applications & Visualization) to what's actually implemented in this repo,
so the diagram you submit is traceable to running code rather than
aspirational. UI colours/theme are untouched — this is a backend/data-model
and API-surface change only.

## Layer 1 — Data Sources & Acquisition
- `POST /api/processing/buildings/{id}/imagery` — drone/orthophoto upload
- `POST /api/processing/buildings/{id}/pointcloud` — LiDAR .las/.laz upload
- `POST /api/assets/gnss-control-points` — CORS/GCP ground-control points
- `POST /api/assets/datasets` — GIS parcel layers, floor plans, DEM/DSM
  (`Dataset.dataset_type`)
- **Not automated**: there is no public API that supplies GNSS/CORS
  points, DoLR parcel data, or DEM/DSM tiles — these are uploads of data
  *you* provide from your own survey/CORS account, not fetched by the app.

## Layer 2 — Ingestion & ETL
- `models.Dataset` — metadata catalog: `crs`, `gsd_m_per_px`, `capture_date`,
  `accuracy_m`, `storage_path` (added this pass — previously only
  filename/size/status were tracked, no georeferencing metadata)
- `models.GnssControlPoint` — control points used for georeferencing/
  registration, linkable to a `Dataset`
- File persistence: `routers/processing_router.py::_save_upload()`

## Layer 3 — 3D Reconstruction & AI/ML Engine
All model adapters live under `backend/app/ai/`, one subfolder per
detection domain — each independently falls back to a disclosed
deterministic/manual path when its model/weights/input isn't available:
- `ai/footprint/extractor.py` — `extract_footprint_from_imagery()`:
  two interchangeable building-extraction backends, selected by
  `FOOTPRINT_MODEL_BACKEND` (falls back automatically to whichever backend
  actually has weights configured, then to the disclosed heuristic if
  neither does):
  - SegFormer semantic segmentation — **default** (`SEGFORMER_WEIGHTS_PATH`)
  - YOLOv8-seg instance segmentation — optional, unchanged from before
    (`YOLO_SEG_WEIGHTS_PATH`)
- `ai/vegetation/ndvi_check.py` — **new this pass**, NDVI vegetation-vs-
  building disambiguation: for footprints the automated pipeline itself
  detected/predicted (never for a surveyor entry or a real OSM `building`
  tag — see `auto_pipeline._NDVI_TRUSTED_TYPE_SOURCES`), samples real
  Sentinel-2 L2A NDVI (Earth Search STAC API, AWS Open Data, anonymous
  HTTPS, no key) over the footprint and raises an
  `anomaly_possible_vegetation` review flag (`validation.check_vegetation_ndvi()`)
  when it reads as tree canopy rather than a built surface — never
  auto-rejects, only queues it for a human reviewer.
- `ai/floors/segmenter.py` — `segment_floors_from_point_cloud()`: Z-density
  above-ground floor clustering from aerial LiDAR; NEW this pass:
  `segment_basement_from_point_cloud()`, the same technique applied
  below-ground — but see its docstring: aerial sensors cannot see an
  enclosed basement, so this only produces a real result when fed an
  actual basement/mobile-LiDAR scan (`basement_point_cloud_path`), not
  the building's rooftop aerial cloud
- `ai/registration/alignment.py` — `align_via_control_points()` (Umeyama
  GCP fit) and `icp_refine()` (point-cloud-to-point-cloud ICP)
- `ai/underground/` — **new this pass**, underground utility auto-detection:
  - `surface_assets.py` — YOLO detection of manholes/valve boxes/chambers
    on drone orthophoto (the QL-C "surveyed surface feature" half)
  - `gpr_detection.py` — hyperbola detection on GPR B-scan radargrams +
    real physics (`travel_time_to_depth()`, standard two-way-travel-time
    formula) to convert a detection into an actual 3D position — this is
    the only sensor here that can see buried pipes/cables at all; drone/
    aerial LiDAR cannot
  - `fusion.py` — DBSCAN clustering + robust line-fitting to turn scattered
    GPR hits into utility traces, snaps to nearby surveyed surface assets,
    tags each trace with a real PAS 128 / ASCE 38 quality level (QL-A–D)
- `ai/heights/ndsm_estimator.py` — **new this pass**, DEM-based height
  estimation: the lowest-confidence tier (below real LiDAR and below
  surveyed/OSM-tagged height_m), used only when a building has neither —
  samples the public Copernicus GLO-30 satellite DSM under a building's
  real footprint, with an annular-ring ground-level estimate by default
  (or true nDSM via OpenTopography's SRTM DEM if `OPENTOPOGRAPHY_API_KEY`
  is set). Gated by `DEM_HEIGHT_ESTIMATION_ENABLED`; wired into the OSM
  bulk-import commit path (`bulk_import_router.py`, only when OSM tagged
  neither height nor levels) and exposed standalone at `POST
  /api/processing/buildings/{id}/estimate-height-dem`. Every value it
  produces is tagged `floor_source="dem_estimated"`, distinct from
  `"manual"`/`"ml_model"`/`"unsurveyed"`.
- `routers/processing_router.py::extract_building_footprint()` /
  `segment_floors()` / `segment_basement_levels()` — try the model first,
  fall back to the disclosed deterministic heuristic when no model/input
  is configured
- `routers/underground_router.py` (new) — `/detect-surface-assets`,
  `/detect-gpr`, `/fuse` (auto-detection, separate from the manual
  underground-asset CRUD in `assets_router.py`)
- `routers/validation.py` — topology validation (adjacency/overlap checks)
- `training/train_yolo_seg.py`, `training/prepare_dataset.py` — the actual
  training pipeline for the footprint model (you run this yourself against
  real imagery + your GPU; see file docstrings for open starting datasets)

## Layer 4 — 3D Cadastral Data Model & Registry
- Spatial units: `Parcel` (surface, base 2D ULPIN), `Building` → `Floor`
  (now including basement levels, `floor_number < 0`) → `Unit`
  (condominium/flat, 3D ULPIN), `UndergroundAsset`, `AirRightCorridor` —
  covers all four spatial-unit kinds the problem statement calls out
- **Added this pass** (previously just a bare `owner_reference` string on
  `Unit`, and no ownership model at all for underground/air-rights):
  - `models.Party` — LADM Party (rights-holder), PII-free
  - `models.RightRestrictionResponsibility` — LADM RRR, generalized via
    `spatial_unit_type` + `spatial_unit_id` to attach to any of the four
    spatial-unit tables uniformly (this is the LADM "Basic Administrative
    Unit" link between spatial units and rights)
  - `UndergroundAsset.source` / `.quality_level` / `.detection_confidence`
    — distinguishes manually-asserted utilities from auto-detected ones,
    tagged with real PAS 128 / ASCE 38 quality levels
- `ulpin.py` — deterministic 3D ULPIN generation (base 2D ULPIN + building/
  floor/unit suffix)

## Layer 5 — Services & APIs
- `routers/rrr_router.py` (new) — `POST /api/rrr`, `GET
  /api/rrr/{spatial_unit_type}/{spatial_unit_id}`, party CRUD
- `routers/parcels_router.py` — parcel/building/unit CRUD, `GET
  /parcel/{ulpin}`-equivalent
- `routers/processing_router.py` — `POST /api/processing/start`, job
  status, imagery/point-cloud upload
- `routers/geocode_router.py`, `misc_routers.py` (audit/export/analytics/
  notifications) — supporting services
- Background processing: `ProcessingJob` model + stage machine (not a
  frontend animation timer — real backend state)

## Layer 6 — Applications & Visualization
- `frontend/` — UI theme/colours untouched; consumes the APIs above.
  Search-by-ULPIN, admin/surveyor upload tools, and grievance submission
  already exist. The viewer toolbar now offers two 3D renderers side by
  side: the original zero-dependency Three.js scene (default), and a
  `CesiumViewer.jsx` that streams each parcel's real Cesium 3D Tiles
  tileset (Layer 3/4 data, via `routers/tiles_router.py`) onto a
  genuinely georeferenced globe — free OSM imagery/ellipsoid terrain, no
  Cesium ion account. A transparent-legal-volume view and vertical
  section/slice tool remain the natural next additions on top of either
  renderer.

## Database — PostgreSQL + PostGIS by default
- `DATABASE_URL` now defaults to Postgres (`docker-compose.yml` at the
  repo root runs a matching local `postgis/postgis` instance); SQLite
  remains a supported fallback. `IS_POSTGIS`-gated geometry columns
  (Layer 4, `models.py`) and the `/api/spatial/*` endpoints (Layer 5,
  `spatial_router.py`) are therefore live out of the box instead of
  requiring a manual opt-in migration.

## Cross-cutting
- `auth.py` — RBAC (`surveyor` / `verifier` / `admin`), used by every new
  endpoint above via `auth.require_roles(...)`
- `cache.py`, `misc_routers.audit_router` — caching + audit logging

## What's still a deliberate stand-in (disclosed, not hidden)
- Point-cloud floor detection uses histogram peak-finding, not a trained
  PointNet++/SPVCNN instance-segmentation model — the interface
  (`segment_floors_from_point_cloud`) is where that model would plug in.
- No real DoLR/GNSS-CORS API exists to integrate with; uploads are manual.
- YOLOv8-seg needs real trained weights (see `training/`) before
  `AI_MODELS_ENABLED=true` produces production-quality results — an
  untrained/base checkpoint will not detect buildings correctly.
- Basement auto-detection needs an actual basement/mobile-LiDAR scan
  upload — aerial drone/LiDAR physically cannot see an enclosed basement,
  so without that separate upload, basement levels stay manual-entry only.
  Same for surface-asset (manhole) and GPR-hyperbola detection: both need
  real trained weights (`SURFACE_ASSET_WEIGHTS_PATH`,
  `GPR_HYPERBOLA_WEIGHTS_PATH`) that this project doesn't ship — the GPR
  depth-conversion physics is real and needs no training, but hyperbola
  *detection* on a radargram image does.
- "Parking" unit classification is a positional rule (basement level →
  parking), not visual detection of painted stalls/lines — a real
  parking-stall detector would need its own trained model on basement
  imagery.

## Corridor / air-right / parking detection (backend/app/ai/corridors)
- `osm_detector.py` -- OSM bridge/layer/viaduct tags -> typed corridors (metro, elevated_rail, flyover, elevated_road) and parking areas. Heights are planning defaults (confidence capped at 0.45) unless a height tag exists.
- `lidar_detector.py` -- flat, elongated, elevated, non-building structures in a point cloud -> MEASURED deck top; `fuse()` lets LiDAR override OSM's assumed heights. A top-only aerial scan cannot see a slab underside, so underside = top - disclosed depth unless the cloud has underside returns.
- `parking_detector.py` -- painted-stall detection (Hough, needs orthophoto <=0.10 m/px) and floor-plan stall-geometry rule. This supersedes the "basement = parking" positional rule ONLY where imagery/plans exist; delineate_units() itself still uses the positional rule.
- `conflicts.py` -- 3-D corridor-vs-building test (footprint overlap/setback + height ranges).
- API: `POST /api/detect/parcels/{id}/corridors` (preview, or `commit=true`), `POST /api/detect/parcels/{id}/parking`, `POST /api/detect/buildings/{id}/parking-stalls`.
- Tested on synthetic data only (`tests/test_corridor_detection.py`); endpoints not yet exercised against a live server. Existing SQLite DBs: run `python add_air_right_provenance_columns.py`.
