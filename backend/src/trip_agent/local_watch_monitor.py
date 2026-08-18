"""Local-watch evaluation — deliberately NOT an LLM call, same principle as
wishlist_monitor.py: this runs on a repeating background schedule, so it goes
straight to the real data source (search_events_range) instead of paying for
a Bedrock call every sweep. There's no destination to pick here either — a
watch is just a fixed city — so unlike the wishlist feature, a local watch
never needs an LLM call at all, not even once at creation.

The whole point of a proactive watch is surfacing what's NEW, not repeating
the same static listing every sweep — so this diffs against the watch's
notified_event_urls and only reports events that haven't already been
surfaced for it.
"""

import json
from datetime import date, timedelta

from .tools.events import search_events_range

CHECK_WINDOW_DAYS = 14
MAX_TRACKED_EVENT_URLS = 100


def evaluate_local_watch(item: dict) -> dict:
    """Returns {"status": "no_new_events", "checked_event_urls": [...]} or
    {"status": "ok", "message", "booking_link", "checked_event_urls": [...]}.
    checked_event_urls is always returned — the caller persists it via
    db.mark_local_watch_checked regardless of whether anything new was found,
    so "already seen" stays accurate even on a quiet sweep."""
    today = date.today()
    window_end = today + timedelta(days=CHECK_WINDOW_DAYS)

    events = search_events_range(
        city_name=item["city"],
        start_date=today.isoformat(),
        end_date=window_end.isoformat(),
        mood_or_interest=item.get("mood_or_interest") or "",
    )

    already_notified = set(json.loads(item.get("notified_event_urls") or "[]"))
    new_events = [ev for ev in events if ev["ticket_link"] not in already_notified]

    # Bounded so a long-lived watch doesn't grow this column forever — the
    # most recently seen events are what matter for future dedup.
    seen_urls = (list(already_notified) + [ev["ticket_link"] for ev in new_events])[-MAX_TRACKED_EVENT_URLS:]

    if not new_events:
        return {"status": "no_new_events", "checked_event_urls": seen_urls}

    top = new_events[0]
    where = f" at {top['venue_name']}" if top["venue_name"] else ""
    when = f" on {top['date']}" if top["date"] else ""
    extra = f" (+{len(new_events) - 1} more new event{'s' if len(new_events) > 2 else ''})" if len(new_events) > 1 else ""
    message = f"New in {item['city']}: {top['name']}{where}{when}.{extra}"

    return {
        "status": "ok",
        "message": message,
        "booking_link": top["ticket_link"],
        "checked_event_urls": seen_urls,
    }
