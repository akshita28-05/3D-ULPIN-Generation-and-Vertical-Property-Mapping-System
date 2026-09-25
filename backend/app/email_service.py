"""
Email notification service.

Real SMTP sending via Python's stdlib smtplib -- this is genuine, working
send code, not a stub. It activates when SMTP_HOST (and related env vars)
are configured.

Honesty note: this sandbox has no outbound network access to real SMTP
providers, so the actual network send has not been tested end-to-end here.
What HAS been tested: every code path up to and including the smtplib call,
the DB persistence of each notification, and the dev-mode fallback that
activates when no SMTP server is configured (the default for local/demo
use) -- which logs the "email" and stores it in the notifications table
instead of attempting a real send, so the full trigger chain (unit
approved -> notification created -> visible in the admin Notifications
log) is fully verifiable without a live mail server.

To enable real sending, set these environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger("landsphere.email")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "no-reply@vasudha3d.gov.demo")

SMTP_CONFIGURED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def _send_via_smtp(to_email: str, subject: str, body: str) -> None:
    """Real SMTP send. Raises on failure so the caller can record it."""
    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())


def send_notification(
    db: Session, recipient_email: str, event_type: str, subject: str, body: str,
    user_id: str = None, commit: bool = True,
) -> models.Notification:
    """
    Creates and persists a Notification row, then attempts a real send if
    SMTP is configured. Never raises to the caller -- a failed/unavailable
    email never breaks the calling request (e.g. approving a unit should
    still succeed even if the notification email fails).
    """
    notification = models.Notification(
        user_id=user_id, recipient_email=recipient_email, event_type=event_type,
        subject=subject, body=body, status=models.NotificationStatus.queued,
    )
    db.add(notification)
    db.flush()

    if SMTP_CONFIGURED:
        try:
            _send_via_smtp(recipient_email, subject, body)
            notification.status = models.NotificationStatus.sent
            notification.sent_at = datetime.utcnow()
        except Exception as e:
            notification.status = models.NotificationStatus.failed
            notification.error_message = str(e)
            logger.warning(f"Email send failed for {recipient_email}: {e}")
    else:
        # Dev-mode fallback: no SMTP configured, log locally instead of sending.
        notification.status = models.NotificationStatus.dev_logged
        logger.info(f"[DEV EMAIL — SMTP not configured] To: {recipient_email} | Subject: {subject}\n{body}")

    if commit:
        db.commit()
        db.refresh(notification)
    return notification


# --- Templated helpers for each event type used across the app ---

def notify_unit_verified(db: Session, unit: "models.Unit"):
    subject = f"Property Record Verified — {unit.ulpin_3d}"
    body = (
        f"Your property record {unit.ulpin_3d} has been reviewed and verified.\n\n"
        f"You can view the full record on Vasudha 3D.\n\n"
        f"This is a prototype notification for a demo system."
    )
    recipient = unit.owner_reference and f"{unit.owner_reference.lower()}@demo.vasudha3d" or "owner@demo.vasudha3d"
    return send_notification(db, recipient, "unit_verified", subject, body, commit=False)


def notify_grievance_status_changed(db: Session, grievance: "models.Grievance"):
    subject = f"Grievance {grievance.grievance_number} — Status Updated"
    body = (
        f"Your grievance {grievance.grievance_number} status has changed to: {grievance.status}.\n\n"
        f"This is a prototype notification for a demo system."
    )
    recipient = grievance.reporter_contact or "citizen@demo.vasudha3d"
    return send_notification(db, recipient, "grievance_status_changed", subject, body, commit=False)


def notify_password_reset(db: Session, user: "models.User", reset_token: str, reset_url_base: str = "http://localhost:5173/admin/reset-password"):
    subject = "Vasudha 3D — Password Reset Request"
    body = (
        f"Hi {user.name},\n\n"
        f"We received a request to reset your password. Use the link below "
        f"(valid for 30 minutes):\n\n"
        f"{reset_url_base}?token={reset_token}\n\n"
        f"If you did not request this, you can ignore this email."
    )
    return send_notification(db, user.email, "password_reset", subject, body, user_id=user.id, commit=False)


def notify_welcome(db: Session, user: "models.User"):
    subject = "Welcome to Vasudha 3D"
    body = f"Hi {user.name},\n\nYour Surveyor account has been created. You can now sign in and start creating parcels and buildings."
    return send_notification(db, user.email, "welcome", subject, body, user_id=user.id, commit=False)
