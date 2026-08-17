"""The actual autonomous piece: a background job that checks every saved trip
on a timer, with no user action involved. This is what turns Phase 2 from an
on-demand button into a real background agent — the sweep runs whether or not
anyone has the app open, and only writes something down when there's a real
decision worth surfacing.

MONITOR_INTERVAL_MINUTES controls the cadence (default 4 hours). For a live
demo, set it low (e.g. 1-2) so a sweep visibly fires during the recording
instead of making the audience wait hours.
"""

import json
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from . import db
from .monitor import check_for_updates
from .notify import send_email_notification

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()


def run_monitoring_sweep() -> dict:
    trips = db.list_active_trips()
    swept = 0
    surfaced = 0

    for trip in trips:
        plan = json.loads(trip["plan_json"])
        try:
            result = check_for_updates(plan)
        except Exception:
            logger.exception("Monitoring check failed for trip %s", trip["id"])
            continue

        swept += 1
        for update in result["updates"]:
            db.add_notification(trip["id"], update["type"], update["message"], update.get("booking_link"))
            surfaced += 1
            if trip["email"]:
                send_email_notification(trip["email"], update["message"], update.get("booking_link"))

    logger.info("Monitoring sweep: checked %d trip(s), surfaced %d update(s)", swept, surfaced)
    return {"trips_checked": swept, "updates_surfaced": surfaced}


def start_scheduler() -> None:
    interval_minutes = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "240"))
    _scheduler.add_job(
        run_monitoring_sweep,
        "interval",
        minutes=interval_minutes,
        id="monitoring_sweep",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Background monitoring scheduler started (every %d minutes)", interval_minutes)


def stop_scheduler() -> None:
    _scheduler.shutdown(wait=False)
