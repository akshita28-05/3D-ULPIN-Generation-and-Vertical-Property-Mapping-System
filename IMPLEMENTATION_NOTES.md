# Implementation notes: 4 requested features

All four are implemented and every changed/new Python file passes
`py_compile`. Frontend JSX changes are brace-balanced but not built with
Vite in this environment (no network access to install node_modules) --
review before merging. Nothing here was run against a live Postgres
instance either (no network access), so treat the SQL/PostGIS pieces as
carefully written but not integration-tested.

## 1. Duplicate-detection dashboard -- fully built

- `GET /api/processing/pending-model-run` (backend/app/routers/processing_router.py)
  -- finds every building where `footprint_source`/`floor_source` is
  still `"manual"` despite a drone image / point cloud already being
  uploaded for it. Only flags a building if the uploaded file could
  actually change something (imagery only matters while
  `footprint_source == "manual"`, a point cloud only while
  `floor_source == "manual"`).
- `frontend/src/pages/admin/PendingModelRuns.jsx` -- new admin page,
  wired into `App.jsx` routing and the sidebar nav
  (`/admin/pending-model-run`).

## 2. PostGIS migration -- additive, not a rip-and-replace

Swapping the existing `footprint_geojson`/`geometry_geojson` Text columns
outright would touch 12 files across routers, seed scripts, and the ML
adapters. Instead:

- `backend/app/database.py` -- `IS_POSTGIS` flag derived from
  `DATABASE_URL`.
- `backend/app/models.py` -- `Parcel`, `Building`, `UndergroundAsset`,
  `AirRightCorridor` each get a `geom` (`geoalchemy2.Geometry`) column +
  GiST index, but **only** when `IS_POSTGIS` is true, so SQLite (the
  zero-setup demo default) is completely unaffected and doesn't need
  `geoalchemy2` installed.
- `backend/app/geo.py` -- `sync_geom_from_geojson(obj)` helper to call
  after writing a `*_geojson` column, keeping `geom` in step. Not yet
  wired into every existing create/update endpoint -- see "Follow-ups"
  below.
- `backend/scripts/migrate_to_postgis.py` -- one-time script: enables the
  `postgis` extension, creates the new columns, backfills `geom` from
  existing GeoJSON via `ST_GeomFromGeoJSON`.
- `backend/app/routers/spatial_router.py` -- your two example queries,
  for real:
  - `GET /api/spatial/parcels/near?lat=&lon=&radius_m=` -- `ST_DWithin`
    on a `geography` cast (correct meter-radius math, not degrees).
  - `POST /api/spatial/underground-assets/intersecting` -- `ST_Intersects`
    against a posted excavation-zone GeoJSON polygon.
  - Both return `501` on SQLite instead of silently doing the wrong thing.

**Follow-up work, not done here:** call `sync_geom_from_geojson()` from
every router that currently writes `footprint_geojson`/`geometry_geojson`
(`parcels_router.py`, `processing_router.py`, `assets_router.py`, etc.) so
`geom` stays live going forward instead of only being backfilled once.

## 3. 3D Tiles pipeline -- core engine built and wired

- `backend/app/tiles/build_tileset.py` -- real WGS84 geodesy
  (`geodetic_to_ecef`, `enu_to_ecef_transform`), footprint extrusion into
  a mesh, a proper glTF/GLB writer (`pygltflib`), assembled into a 3D
  Tiles 1.1 `tileset.json` per parcel (one child tile per building, glTF
  content directly -- no `b3dm` wrapper needed under 1.1).
- `backend/app/routers/tiles_router.py` -- `POST
  /api/tiles/parcels/{parcel_id}/rebuild` (background task, same
  fire-and-poll pattern as `/api/processing/start`).
- `backend/app/main.py` -- router registered, `/tiles` mounted as static
  files serving `TILES_DIR` (default `./tiles_output`) so a CesiumJS
  `Cesium3DTileset` can point straight at
  `/tiles/{parcel_id}/tileset.json`.

**Documented limitations (in the code, not hidden):**
- Georeferencing assumes each building's local-meter footprint is offset
  from its *parcel's* `centroid_lat`/`centroid_lon` -- nothing in the
  current schema records a real per-building survey origin. Fix once
  GNSS control-point registration (already in `ai/registration/`) reaches
  building level.
- Triangulation is a fan triangulation, correct only for convex
  footprints. Every footprint this app currently generates (bounding-box
  grids, YOLO boxes) is convex, so this holds today; swap in ear-clipping
  (e.g. `mapbox_earcut`) before accepting arbitrary hand-drawn concave
  footprints.
- No LOD/tile-splitting for very large parcels (one tile per building,
  flat hierarchy) -- fine at prototype scale, revisit with a real
  quadtree/octree if a parcel ever has hundreds of buildings.

## 4. Change-detection automation -- built, off by default

- `backend/app/models.py` -- `Building` gets
  `last_change_check_footprint_geojson`, `last_change_check_num_floors`,
  `last_change_check_at` -- a rolling baseline, distinct from the
  existing `manual_*` snapshot fields (which capture the one-time
  pre-AI values).
- `backend/app/change_detection.py` -- `check_building_for_change()`
  re-runs the *existing* real model adapters
  (`ai/footprint/extractor.py`, `ai/floors/segmenter.py`) against a
  building's current imagery/point cloud and diffs the result against the
  stored baseline. Flags footprint area drift >=15% or a floor-count
  increase, and creates a real `ChangeDetection` row -- never a second,
  separate "model," and never invented if there's nothing to compare
  against yet (first-ever check just establishes the baseline).
- `backend/app/change_detection_scheduler.py` -- `APScheduler`
  `BackgroundScheduler`, gated by `CHANGE_DETECTION_ENABLED` (default
  `false`) and `CHANGE_DETECTION_INTERVAL_HOURS` (default `24`). Started/
  stopped from `main.py`'s FastAPI startup/shutdown events.
- `backend/app/routers/assets_router.py` -- `POST
  /api/change-detection/sweep` (admin/verifier only) runs the identical
  sweep on demand, same code path as the scheduled job.
- `frontend/src/pages/admin/ChangeDetection.jsx` -- "Run sweep now"
  button for admins/verifiers, shows how many buildings were checked and
  flagged.

**Honesty/scope note (also in the code):** this only checks footprint
area and floor count -- the two signals available from the *existing*
real model adapters without re-running full unit delineation (which this
prototype doesn't yet support re-running on an already-processed
building). It is not a pixel-level satellite change-detection model; if
one gets plugged in later, wire it in as its own adapter under
`ai/change_detection/` and call it from `check_building_for_change()`
alongside the existing checks, following the same disclosed-heuristic vs.
real-model pattern already used everywhere else in this codebase.

## New/changed dependencies (all optional, gated by env var / `IS_POSTGIS`)

```
psycopg2-binary==2.9.9   # Postgres driver
geoalchemy2==0.15.2      # PostGIS ORM types
numpy==2.1.1             # mesh math for 3D Tiles
pygltflib==1.16.2        # glTF/GLB writer
apscheduler==3.10.4      # change-detection scheduler
```

None of these are required for the SQLite demo path to keep working
exactly as before.

## 5. PostgreSQL + PostGIS promoted from optional to default database

- `backend/app/database.py` -- `DATABASE_URL` now defaults to
  `postgresql://sih_user:sih_password@localhost:5432/sih_ulpin` (was
  `sqlite:///./sih_ulpin.db`), matching the new `docker-compose.yml` at
  the repo root. `_ensure_postgis_extension()` runs
  `CREATE EXTENSION IF NOT EXISTS postgis;` on startup (best-effort,
  logs and continues on failure) so a fresh Postgres database needs no
  manual `psql` step before `Base.metadata.create_all()` adds the
  `geoalchemy2.Geometry` columns already declared in `models.py` behind
  `IS_POSTGIS` (see section 3 above -- that branching logic is
  unchanged, only which DB it points at by default). SQLite remains a
  fully working fallback (`DATABASE_URL=sqlite:///./sih_ulpin.db`) for
  offline/no-Docker use; every non-spatial router behaves identically
  either way.
- `backend/requirements.txt` -- `psycopg2-binary` / `geoalchemy2` moved
  from the "optional, only if you switch to Postgres" comment block into
  the plain required list, since Postgres is now what a fresh
  `pip install -r requirements.txt` + default env actually connects to.
- `docker-compose.yml` (new, repo root) -- a `postgis/postgis` container
  with credentials matching the new default `DATABASE_URL` exactly, so
  `docker compose up -d` is the entire "set up the database" step.
- `backend/.env.example`, `README.md` -- updated install steps, the
  top-of-file "Honesty notes", and the old "Moving to PostgreSQL +
  PostGIS (production)" section (which described a manual column-by-
  column swap that `models.py`'s existing `IS_POSTGIS` branching had
  already made unnecessary) rewritten to describe what actually happens
  automatically now, plus how to opt back into SQLite.
- No schema, router, or model logic changed -- this pass only flips
  which database backend is used by default and makes sure a brand-new
  Postgres instance bootstraps itself without manual steps.

## 6. CesiumJS viewer added alongside the existing Three.js viewer

- `frontend/src/components/CesiumViewer.jsx` (new) -- renders the
  parcel's real Cesium 3D Tiles tileset (already built server-side by
  `backend/app/tiles/build_tileset.py`, served at
  `/tiles/{parcel_id}/tileset.json`, see `tiles_router.py`) on a genuine
  georeferenced Cesium globe: free OpenStreetMap imagery, plain WGS84
  ellipsoid terrain, no Cesium ion account/token anywhere. If a parcel's
  tileset hasn't been generated yet, shows a **Generate 3D Tiles**
  button (surveyor/verifier/admin only) that calls `POST
  /api/tiles/parcels/{id}/rebuild` and polls the static URL until it's
  ready, matching the existing fire-and-poll pattern used by
  `/api/processing/start`. Exposes the same imperative
  `resetView()` / `topView()` / `rotate()` / `zoomIn()` / `zoomOut()`
  surface as `ThreeScene.jsx` so the shared toolbar/directional-pad in
  `Viewer3D.jsx` works unchanged against whichever viewer is active.
- `frontend/src/pages/citizen/Viewer3D.jsx` -- added a third **Cesium**
  toggle next to the existing 3D View / 2D Map buttons; switches which
  viewer component is mounted under the same toolbar, panels, and
  selection logic. Reused as-is by the admin console
  (`pages/admin/Viewer.jsx` already just re-renders this component), so
  both citizen and admin/surveyor/verifier views get the Cesium option
  with no separate admin-side change needed.
- `frontend/package.json`, `vite.config.js` -- added `cesium` +
  `vite-plugin-cesium` (the plugin copies Cesium's static
  Workers/Assets/Widgets into the build and sets `CESIUM_BASE_URL`
  automatically); added a `/tiles` dev-server proxy alongside the
  existing `/api` one so `CesiumViewer` can fetch tilesets from
  `npm run dev` the same way it will in production.
- Three.js remains the default viewer and is untouched -- this is
  additive, not a replacement, per "don't change the context of the
  project."

## 7. DEM-based building height estimation (new lowest-confidence tier)

- `backend/app/ai/heights/ndsm_estimator.py` (new) -- for a building with
  neither a surveyed/OSM-tagged `height_m`/`num_floors` nor a LiDAR point
  cloud, estimates both from the public Copernicus GLO-30 satellite DSM
  (AWS Open Data, anonymous S3 access, verified real bucket/key format)
  sampled directly under the building's real-world footprint. Ground
  level defaults to an annular-ring estimate (median DSM elevation in a
  ~5-15m ring just outside the footprint, no API key needed); if
  `OPENTOPOGRAPHY_API_KEY` is set, a real bare-earth SRTM DEM is fetched
  instead for a true nDSM = DSM − DEM (higher confidence, tagged
  `copernicus_dsm_minus_srtm_dem` vs `copernicus_dsm_annular_ring`).
  Gated behind `DEM_HEIGHT_ESTIMATION_ENABLED` (off by default -- makes
  real network calls + needs `requirements-ml.txt`'s new `rasterio`/
  `boto3`). Every failure path (missing deps, no tile at that location,
  footprint smaller than one ~900 sqm DSM pixel, implausible result)
  returns `None` and logs why -- never a fabricated height, matching the
  rest of this codebase's disclosed-fallback convention.
- `backend/app/routers/bulk_import_router.py` -- wired in as a new tier
  in the OSM bulk-import commit path: only consulted when OSM gave a
  building *neither* a `height` *nor* a `building:levels` tag. On
  success, the building is created with `floor_source="dem_estimated"`
  (a new, distinct value from `"manual"`/`"unsurveyed"`/`"ml_model"`) --
  never silently relabelled as if it were a real survey.
- `backend/app/routers/processing_router.py` -- new standalone endpoint
  `POST /api/processing/buildings/{id}/estimate-height-dem` for
  retrofitting an existing unsurveyed building (surveyor/verifier/admin
  only; 400s if the building already has real height/floor data, since
  this fills a gap rather than overriding a survey). Accepts an optional
  `footprint_latlon` for accuracy; without it, approximates the real-world
  footprint by treating the building's stored local-metre geometry as
  centred on its parcel's `centroid_lat`/`centroid_lon` (documented
  approximation -- pass `footprint_latlon` explicitly for a multi-building
  parcel where that assumption doesn't hold).
- `backend/requirements-ml.txt`, `backend/.env.example` -- added
  `rasterio`/`boto3` and the `DEM_HEIGHT_ESTIMATION_ENABLED`/
  `OPENTOPOGRAPHY_API_KEY`/`DEM_CACHE_DIR` env vars, documented alongside
  the existing optional-ML install step.
- Prompted by a review of `Imad-81/SIH-26011` ("GeoVoxel-3D"), a public
  SIH26011 prototype that auto-fetches real OSM + Copernicus DEM data
  city-wide -- this closes the specific gap flagged against it (this
  project previously only accepted DEM/DSM as a manual Dataset upload,
  with no automated fetch path).
