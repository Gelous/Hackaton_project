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
from datetime import datetime, timedelta, timezone

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.background import BackgroundScheduler

from . import db
from .local_watch_monitor import evaluate_local_watch
from .monitor import check_for_updates
from .notify import send_email_notification
from .wishlist_monitor import evaluate_wishlist_item

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()

# Wishlist items have no fixed date, so they're checked on a slower, coarser
# cadence than trip milestones — weekly is enough to notice a meaningfully
# better window without hammering the weather/flight-estimate tools.
WISHLIST_CHECK_INTERVAL_DAYS = 7

# Local watches check more often than wishlist items — events (especially
# newly on-sale ones) are more time-sensitive than a travel-window forecast,
# and each check is just one real API call, not a repeated Bedrock cost.
LOCAL_WATCH_CHECK_INTERVAL_DAYS = 1

_LAST_SWEEP_SETTING_KEY = "last_sweep_completed_at"


def run_monitoring_sweep() -> dict:
    trip_stats = _process_trips()
    feedback_stats = _process_trip_feedback_requests()
    wishlist_stats = _process_wishlist_items()
    local_watch_stats = _process_local_watches()
    stats = {**trip_stats, **feedback_stats, **wishlist_stats, **local_watch_stats}
    logger.info(
        "Monitoring sweep: %d trip(s) checked / %d update(s), %d feedback request(s), "
        "%d wishlist item(s) checked / %d update(s), %d local watch(es) checked / %d update(s)",
        stats["trips_checked"],
        stats["trip_updates_surfaced"],
        stats["feedback_requests_sent"],
        stats["wishlist_checked"],
        stats["wishlist_updates_surfaced"],
        stats["local_watches_checked"],
        stats["local_watch_updates_surfaced"],
    )
    # Recorded so a restart can tell whether a full interval was missed while
    # the process was down (see _missed_a_sweep) instead of silently waiting
    # out the next scheduled tick, however far away that is.
    db.set_setting(_LAST_SWEEP_SETTING_KEY, datetime.now(timezone.utc).isoformat())
    return stats


def _process_trips() -> dict:
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
            # Without this, a milestone like "7 days out" or a persistent
            # rainy forecast would re-insert the same notification on every
            # sweep for the rest of that day.
            if db.notified_within(1, update["type"], trip_id=trip["id"]):
                continue
            db.add_notification(update["type"], update["message"], update.get("booking_link"), trip_id=trip["id"])
            surfaced += 1
            if trip["email"]:
                send_email_notification(trip["email"], update["message"], update.get("booking_link"))

    return {"trips_checked": swept, "trip_updates_surfaced": surfaced}


def _process_trip_feedback_requests() -> dict:
    """The post-trip loop: once a saved trip's dates have passed, ask how it
    went — real stored feedback, not fabricated personalization, that later
    gets woven into planning prompts (see agent.py's feedback-history
    injection). This is also where a trip stops being actively monitored:
    once it's over, there's nothing left to check a flight/hotel price for."""
    trips = db.list_trips_needing_feedback_request()
    requested = 0

    for trip in trips:
        message = (
            f"How was your trip to {trip['destination_city']}? Rate it and the agent will "
            "factor that into future recommendations."
        )
        db.add_notification("trip_feedback_request", message, None, trip_id=trip["id"])
        db.mark_feedback_requested(trip["id"])
        db.set_trip_status(trip["id"], "completed")
        requested += 1
        if trip["email"]:
            send_email_notification(trip["email"], message, None)

    return {"feedback_requests_sent": requested}


def _process_wishlist_items() -> dict:
    items = db.list_due_wishlist_items(stale_after_days=WISHLIST_CHECK_INTERVAL_DAYS)
    checked = 0
    surfaced = 0

    for item in items:
        try:
            result = evaluate_wishlist_item(item)
        except Exception:
            logger.exception("Wishlist check failed for item %s", item["id"])
            continue

        checked += 1
        db.mark_wishlist_checked(item["id"])

        if result["status"] == "expired":
            db.set_wishlist_status(item["id"], "expired")
            db.add_notification(
                "wishlist_expired",
                f"Your wishlist window for {item['destination_city']} has passed without a trip "
                "being booked. Update the dates if you're still interested.",
                None,
                wishlist_id=item["id"],
            )
            surfaced += 1
            continue

        db.add_notification("wishlist_outlook", result["message"], result["booking_link"], wishlist_id=item["id"])
        surfaced += 1
        if item["email"]:
            send_email_notification(item["email"], result["message"], result["booking_link"])

    return {"wishlist_checked": checked, "wishlist_updates_surfaced": surfaced}


def _process_local_watches() -> dict:
    """Proactive counterpart to the on-demand Day Planner — no LLM involved
    (see local_watch_monitor.py), so cost stays flat no matter how many
    watches exist or how long they run."""
    items = db.list_due_local_watches(stale_after_days=LOCAL_WATCH_CHECK_INTERVAL_DAYS)
    checked = 0
    surfaced = 0

    for item in items:
        try:
            result = evaluate_local_watch(item)
        except Exception:
            logger.exception("Local watch check failed for item %s", item["id"])
            continue

        checked += 1
        db.mark_local_watch_checked(item["id"], result["checked_event_urls"])

        if result["status"] == "ok":
            db.add_notification("local_watch_new_events", result["message"], result["booking_link"], local_watch_id=item["id"])
            surfaced += 1
            if item["email"]:
                send_email_notification(item["email"], result["message"], result["booking_link"])

    return {"local_watches_checked": checked, "local_watch_updates_surfaced": surfaced}


def _on_job_error(event) -> None:
    """APScheduler swallows a job's exception into an internal event by
    default — without this listener, a sweep that raises would fail silently
    from the app's point of view (no crash, but also nothing in our logs and
    no indication monitoring quietly stopped working)."""
    logger.error("Scheduled monitoring sweep raised an unhandled exception", exc_info=event.exception)


def _missed_a_sweep(interval_minutes: int) -> bool:
    """True if it's been longer than one full interval since the last
    recorded sweep — including "never recorded one," which covers both a
    genuinely first-ever run and a settings row that's gone missing. Either
    way, running one now beats silently waiting out however long is left on
    the regular schedule."""
    last = db.get_setting(_LAST_SWEEP_SETTING_KEY)
    if last is None:
        return True
    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    return elapsed > timedelta(minutes=interval_minutes)


def start_scheduler() -> None:
    interval_minutes = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "240"))
    _scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    _scheduler.add_job(
        run_monitoring_sweep,
        "interval",
        minutes=interval_minutes,
        id="monitoring_sweep",
        replace_existing=True,
    )

    # Catch-up: if the backend was down long enough to miss a full interval
    # (crash, redeploy, laptop sleep), don't leave saved trips/wishlist items
    # unchecked until the next regular tick — run one sweep shortly after
    # startup instead. The short delay just lets the app finish starting up
    # first; it isn't waiting on anything else.
    if _missed_a_sweep(interval_minutes):
        _scheduler.add_job(
            run_monitoring_sweep,
            "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=10),
            id="catchup_sweep",
            replace_existing=True,
        )
        logger.info("No recent sweep found — running a catch-up sweep in 10s")

    _scheduler.start()
    logger.info("Background monitoring scheduler started (every %d minutes)", interval_minutes)


def stop_scheduler() -> None:
    _scheduler.shutdown(wait=False)
