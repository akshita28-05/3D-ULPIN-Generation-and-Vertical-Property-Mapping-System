# Vasudha 3D — 3D ULPIN Generation & Vertical Property Mapping System

A prototype for SIH26011: a system that gives surface parcels, multi-storey
units, underground infrastructure, and air-rights corridors their own
unique, standardized 3D identity — extending the existing 14-digit ULPIN
rather than replacing it.

**Stack:** FastAPI + PostgreSQL/PostGIS on the backend, React + Three.js/CesiumJS
on the frontend.

## How data moves through the system

1. **Ingestion.** Drone/orthophoto imagery, LiDAR point clouds (`.las`/`.laz`),
   GIS parcel layers, floor plans, GNSS/CORS control points, and DEM/DSM
   files come in as uploads tied to a parcel or building. OpenStreetMap
   buildings and infrastructure can also be pulled in automatically for a
   selected map area, without any manual upload.
2. **3D reconstruction & AI.** Building footprints are extracted from
   imagery (YOLOv8-seg or SegFormer), floors are segmented from point-cloud
   Z-density, and underground assets are detected from GPR B-scans and
   surface markers (manholes, valve boxes), then fused into utility traces
   with DBSCAN clustering and a PAS128/ASCE38 quality level. Every AI stage
   has a disclosed deterministic fallback (based on what a surveyor
   actually entered) when no model is configured — the API always records
   which path produced a given value.
3. **Cadastral model & registry.** The Parcel → Building → Floor → Unit
   hierarchy, plus `UndergroundAsset` and `AirRightCorridor`, are the four
   spatial-unit types. Each carries a 3D ULPIN and links into a
   rights/restrictions/responsibilities (RRR) registry — the LADM/ISO 19152
   pattern — so ownership is modeled as real data, not just a label.
4. **Validation.** Shapely-based (PostGIS when running on Postgres)
   topology checks catch overlaps, containment errors, floor-range
   conflicts, and underground clashes with building foundations before a
   record reaches a verifier.
5. **Review & lifecycle.** A verifier approves, corrects, or rejects each
   generated unit. Once verified, a unit's geometry is a locked baseline —
   further edits go through an owner-approved change-request workflow
   (one-time consent link, officer applies it, new baseline is locked and
   audit-logged) instead of a silent overwrite.
6. **Services & applications.** Citizens can search by ULPIN, browse the
   3D city map, view a unit's property passport (QR + PDF), and file a
   grievance. Officers get a review queue, conflict resolution, analytics,
   and CityJSON export for interoperability with other 3D cadastral tools.

## Core features

- 3D ULPIN generation for surface parcels, multi-storey units, underground
  assets, and air-rights corridors
- AI-assisted footprint extraction, floor segmentation, and underground
  utility detection, each with a disclosed non-AI fallback
- Topology/anomaly validation (overlap, containment, height-floor
  consistency, underground conflicts)
- One-click area automation: pan/zoom to a map area and run the full
  pipeline (footprints → parcels/buildings → floors → units → 3D ULPINs →
  validation → verifier queue) in one call
- Automatic underground and air-rights detection from OpenStreetMap
  (tunnels, cables, elevated transit, overhead lines)
- Ownership lifecycle: locked baselines, owner-approved change requests,
  tamper-evident property passports
- 3D city map (MapLibre GL) and a georeferenced Cesium 3D Tiles viewer
- Grievance submission and tracking, with email notifications for key
  status changes
- CityJSON export for interoperability
- Redis-backed caching and rate limiting, with an in-process fallback for
  local development

## Setup

**1. Install dependencies**

```bash
# Backend
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

**2. Start PostgreSQL + PostGIS**

```bash
docker compose up -d      # from the repo root
```

No Docker? Point `DATABASE_URL` at any Postgres instance with a
`CREATE EXTENSION postgis;`-capable connection — the app enables the
extension itself on startup.

**3. Configure environment variables**

```bash
# backend/.env
DATABASE_URL=postgresql://sih_user:sih_password@localhost:5432/sih_ulpin
JWT_SECRET_KEY=replace-with-a-long-random-string-in-production
```

**4. Redis (optional, recommended)**

```bash
docker run -d -p 6379:6379 redis:alpine
```

Without it, caching and rate limiting fall back to an in-process store —
fine for local development, not for a multi-instance deployment.

**5. Database tables**

Created automatically on first backend startup, including the PostGIS
`geom` columns — no separate migration step.

**6. Seed accounts**

```bash
cd backend
python -m app.seed
```

Creates one login per role. No property data is seeded — every parcel,
building, unit, underground asset, and air-rights corridor is created
through the app itself.

| Role | Email | Password |
|---|---|---|
| Surveyor | surveyor@sih.demo | Surveyor@123 |
| Verifier | verifier@sih.demo | Verifier@123 |
| Admin | admin@sih.demo | Admin@123 |

New surveyor accounts can also self-register from the Sign Up link;
verifier/admin roles require an existing admin to promote them.

**7. Run the backend**

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

**8. Run the frontend**

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api/*` to
`localhost:8000`.

## Typical workflow

- **Surveyor:** create a parcel and building, upload imagery/point clouds
  (or let the pipeline use entered dimensions), run the pipeline, add
  underground assets or air-rights corridors as needed.
- **Verifier:** review the generated units and validation flags, correct
  or approve/reject, resolve flagged conflicts.
- **Citizen:** search by ULPIN, explore the 3D map, view a unit's record,
  file and track a grievance.

## Production notes

This prototype demonstrates the application-layer patterns for scale
(stateless JWT auth, Redis-backed caching/rate limiting, async background
processing, pagination, gzip). A production deployment would add:
connection pooling in front of Postgres, a real task queue (Celery/RQ)
for heavy processing, object storage for uploads, a CDN for the frontend
build, and autoscaling at the infrastructure layer.

3D ULPINs generated here are proposed identifiers for a prototype, not an
official DoLR issuance.
