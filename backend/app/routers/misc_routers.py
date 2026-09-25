import csv
import io
import json
from datetime import datetime

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr as qr_barcode
from reportlab.graphics.shapes import Drawing

from .. import models, schemas, auth, cache, lifecycle
from ..database import get_db

audit_router = APIRouter(prefix="/api/audit", tags=["audit"])
export_router = APIRouter(prefix="/api/export", tags=["export"])
analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@audit_router.get("", response_model=list[schemas.AuditLogOut])
def list_audit_logs(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin")), limit: int = 200, offset: int = 0):
    limit = min(limit, 500)
    return db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).offset(offset).limit(limit).all()


notifications_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@notifications_router.get("", response_model=list[schemas.NotificationOut])
def list_notifications(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin")), limit: int = 200, offset: int = 0):
    limit = min(limit, 500)
    return db.query(models.Notification).order_by(models.Notification.created_at.desc()).offset(offset).limit(limit).all()


@export_router.get("/units.geojson")
def export_units_geojson(db: Session = Depends(get_db)):
    units = db.query(models.Unit).filter(models.Unit.verification_status == models.VerificationStatus.approved).all()
    features = []
    for u in units:
        try:
            coords = json.loads(u.footprint_geojson)
        except Exception:
            coords = []
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "ulpin_3d": u.ulpin_3d, "parcel_type": u.parcel_type,
                "area_sqm": u.area_sqm, "volume_cum": u.volume_cum,
                "z_min": u.z_min, "z_max": u.z_max, "status": "approved",
            },
        })
    geojson = {"type": "FeatureCollection", "features": features}
    return StreamingResponse(
        io.BytesIO(json.dumps(geojson, indent=2).encode()),
        media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=verified_units.geojson"},
    )


@export_router.get("/svamitva-format")
def export_svamitva_format(db: Session = Depends(get_db)):
    """
    Prototype mockup of a SVAMITVA-compatible export envelope.

    Honesty note: this is a representative export format demonstrating
    ecosystem integration awareness (the actual SVAMITVA scheme schema is
    not publicly documented for third-party integration), not a certified
    or DoLR-validated SVAMITVA payload. It packages verified units into a
    structure that mirrors SVAMITVA's property-record shape (parcel,
    building, ownership reference, verification metadata) as a starting
    point for a real integration.
    """
    units = db.query(models.Unit).filter(models.Unit.verification_status == models.VerificationStatus.approved).all()
    records = []
    for u in units:
        parcel = u.floor.building.parcel if u.floor and u.floor.building else None
        records.append({
            "property_record_id": u.ulpin_3d,
            "base_ulpin": parcel.ulpin_2d if parcel else None,
            "village": parcel.village_code if parcel else None,
            "building_ref": u.floor.building.building_code if u.floor and u.floor.building else None,
            "floor_ref": u.floor.floor_code if u.floor else None,
            "unit_ref": u.unit_code,
            "property_type": u.parcel_type,
            "area_sqm": u.area_sqm,
            "ownership_reference": u.owner_reference,
            "verification_status": "verified",
            "verified_on": u.verified_at.isoformat() if u.verified_at else None,
        })
    envelope = {
        "export_format": "SVAMITVA_COMPATIBLE_PROTOTYPE_V1",
        "note": "Representative export mockup — not a certified SVAMITVA payload. See API docs for details.",
        "generated_at": datetime.utcnow().isoformat(),
        "record_count": len(records),
        "records": records,
    }
    return StreamingResponse(
        io.BytesIO(json.dumps(envelope, indent=2).encode()),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=svamitva_compatible_export.json"},
    )


@export_router.get("/units.csv")
def export_units_csv(db: Session = Depends(get_db)):
    units = db.query(models.Unit).filter(models.Unit.verification_status == models.VerificationStatus.approved).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ulpin_3d", "parcel_type", "area_sqm", "volume_cum", "z_min", "z_max", "owner_reference", "verification_status"])
    for u in units:
        writer.writerow([u.ulpin_3d, u.parcel_type, u.area_sqm, u.volume_cum, u.z_min, u.z_max, u.owner_reference, "approved"])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=verified_units.csv"},
    )


@export_router.get("/units/{unit_id}.pdf")
def export_unit_pdf(unit_id: str, request: Request, db: Session = Depends(get_db)):
    u = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Unit not found")
    parcel_ulpin = u.floor.building.parcel.ulpin_2d if u.floor and u.floor.building and u.floor.building.parcel else "N/A"

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 80

    c.setFont("Helvetica-Bold", 18)
    c.drawString(60, y, "3D Property Record — Verified")
    y -= 30
    c.setFont("Helvetica", 10)
    c.drawString(60, y, "Ministry of Rural Development | Department of Land Resources (DoLR)")
    y -= 40

    rows = [
        ("3D ULPIN", u.ulpin_3d),
        ("Parent 2D ULPIN (representative)", parcel_ulpin),
        ("Building", u.floor.building.building_code if u.floor and u.floor.building else "N/A"),
        ("Floor", u.floor.floor_code if u.floor else "N/A"),
        ("Unit", u.unit_code),
        ("Property Type", u.parcel_type or "N/A"),
        ("Area (sqm)", str(u.area_sqm)),
        ("Volume (cum)", str(u.volume_cum)),
        ("Z-Min (m)", str(u.z_min)),
        ("Z-Max (m)", str(u.z_max)),
        ("Verification Status", str(u.verification_status.value if hasattr(u.verification_status, "value") else u.verification_status)),
        ("Owner Reference", u.owner_reference or "N/A"),
        ("Verified At", str(u.verified_at) if u.verified_at else "Pending"),
    ]
    c.setFont("Helvetica", 12)
    for label, value in rows:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(60, y, f"{label}:")
        c.setFont("Helvetica", 11)
        c.drawString(260, y, str(value))
        y -= 24

    integrity = lifecycle.integrity(db, u)
    base_url = os.getenv("PUBLIC_APP_URL") or str(request.base_url)
    passport_url = f"{base_url.rstrip('/')}/property/{u.id}"
    widget = qr_barcode.QrCodeWidget(passport_url)
    x0, y0, x1, y1 = widget.getBounds()
    size = 110
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, width - 60 - size, 130)
    c.setFont("Helvetica", 7)
    c.drawString(width - 60 - size, 118, "Scan: public property passport")

    y -= 10
    c.setFont("Helvetica-Bold", 11)
    c.drawString(60, y, "Integrity:")
    c.setFont("Helvetica", 10)
    if integrity["tampered"]:
        c.setFillColorRGB(0.7, 0.1, 0.1)
        c.drawString(260, y, "WARNING - geometry differs from the locked baseline")
        c.setFillColorRGB(0, 0, 0)
    elif integrity["locked"] and integrity["has_baseline"]:
        c.drawString(260, y, "Locked baseline OK  (SHA-256 " + integrity["baseline_hash"][:16] + "...)")
    elif integrity["locked"]:
        c.drawString(260, y, "Verified (approved before baseline locking existed)")
    else:
        c.drawString(260, y, "Not yet locked - pending verification")

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(60, 72, "Proposed 3D identifier for the SIH26011 prototype - not an official DoLR ULPIN issuance.")
    c.drawString(60, 60, "Prototype record — 2D ULPIN prefix is representative/sample, not a live DoLR system value.")
    c.showPage()
    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={u.ulpin_3d}.pdf"},
    )


@analytics_router.get("", response_model=schemas.AnalyticsOut)
def analytics(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("surveyor", "verifier", "admin"))):
    cached = cache.cache_get("analytics:summary")
    if cached:
        return schemas.AnalyticsOut(**cached)

    total_parcels = db.query(models.Parcel).count()
    total_buildings = db.query(models.Building).count()
    total_units = db.query(models.Unit).count()
    verified_units = db.query(models.Unit).filter(models.Unit.verification_status == models.VerificationStatus.approved).count()
    pending_units = db.query(models.Unit).filter(
        models.Unit.verification_status.in_([models.VerificationStatus.pending_review, models.VerificationStatus.ai_generated])
    ).count()
    rejected_units = db.query(models.Unit).filter(models.Unit.verification_status == models.VerificationStatus.rejected).count()
    active_conflicts = db.query(models.ValidationResult).filter(models.ValidationResult.resolved == False).count()
    open_grievances = db.query(models.Grievance).filter(
        models.Grievance.status.in_([models.GrievanceStatus.submitted, models.GrievanceStatus.under_review, models.GrievanceStatus.assigned])
    ).count()
    running_jobs = db.query(models.ProcessingJob).filter(models.ProcessingJob.progress_pct < 100).count()

    result = schemas.AnalyticsOut(
        total_parcels=total_parcels, total_buildings=total_buildings, total_units=total_units,
        verified_units=verified_units, pending_units=pending_units, rejected_units=rejected_units,
        active_conflicts=active_conflicts, open_grievances=open_grievances, processing_jobs_running=running_jobs,
    )
    cache.cache_set("analytics:summary", result.model_dump(), ttl_seconds=15)
    return result
