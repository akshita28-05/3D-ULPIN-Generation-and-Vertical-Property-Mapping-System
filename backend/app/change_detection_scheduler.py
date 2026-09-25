"""
Periodic scheduling for app/change_detection.py. Off by default
(CHANGE_DETECTION_ENABLED=false) so the zero-setup demo doesn't spin up a
background scheduler nobody asked for; set the env vars below and it
sweeps every building with uploaded imagery/point cloud on an interval,
same as a cron job would, without needing separate infrastructure
(Celery beat, etc) for this prototype's scale.
"""
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from . import models, cache
from .change_detection import check_building_for_change
from .database import SessionLocal

logger = logging.getLogger("landsphere.change_detection")

ENABLED = os.getenv("CHANGE_DETECTION_ENABLED", "false").lower() == "true"
INTERVAL_HOURS = float(os.getenv("CHANGE_DETECTION_INTERVAL_HOURS", "24"))

_scheduler = None


def run_sweep_once():
    """Runs one sweep synchronously -- used by both the scheduled job and
    the on-demand POST /api/change-detection/sweep endpoint, so 'run it
    now' and 'run it on a timer' are exactly the same code path."""
    db = SessionLocal()
    try:
        buildings = db.query(models.Building).filter(
            (models.Building.drone_image_path.isnot(None)) | (models.Building.point_cloud_path.isnot(None))
        ).all()
        flagged = 0
        for b in buildings:
            try:
                if check_building_for_change(b, db):
                    flagged += 1
            except Exception:
                logger.exception(f"Change-detection check failed for building {b.id}")
        db.commit()
        if flagged:
            cache.cache_invalidate("analytics:")
        logger.info(f"Change-detection sweep complete: {len(buildings)} buildings checked, {flagged} flagged")
        return {"buildings_checked": len(buildings), "flagged": flagged}
    finally:
        db.close()


def start():
    global _scheduler
    if not ENABLED or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(run_sweep_once, "interval", hours=INTERVAL_HOURS, id="change_detection_sweep")
    _scheduler.start()
    logger.info(f"Change-detection scheduler started (every {INTERVAL_HOURS}h)")


def stop():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
