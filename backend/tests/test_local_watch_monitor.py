"""local_watch_monitor.py: the proactive "watch this city" check. The whole
point is surfacing what's NEW, so the core thing to verify is the diffing
against notified_event_urls — a real event should be reported once, then
never again once it's been surfaced.
"""

import json

from trip_agent import local_watch_monitor as lwm


def fake_events(names_and_urls):
    return [
        {
            "name": name,
            "venue_name": "Test Venue",
            "date": "2026-09-01",
            "time": "19:00:00",
            "ticket_link": url,
            "category": "Music",
            "lat": None,
            "lon": None,
        }
        for name, url in names_and_urls
    ]


def test_first_check_reports_new_events(monkeypatch):
    monkeypatch.setattr(
        lwm, "search_events_range", lambda **kwargs: fake_events([("Concert A", "https://tm.com/a")])
    )
    item = {"city": "Denver", "mood_or_interest": "live music", "notified_event_urls": "[]"}

    result = lwm.evaluate_local_watch(item)

    assert result["status"] == "ok"
    assert "Concert A" in result["message"]
    assert result["booking_link"] == "https://tm.com/a"
    assert result["checked_event_urls"] == ["https://tm.com/a"]


def test_second_check_with_same_events_reports_nothing_new(monkeypatch):
    monkeypatch.setattr(
        lwm, "search_events_range", lambda **kwargs: fake_events([("Concert A", "https://tm.com/a")])
    )
    item = {
        "city": "Denver",
        "mood_or_interest": "live music",
        "notified_event_urls": json.dumps(["https://tm.com/a"]),
    }

    result = lwm.evaluate_local_watch(item)

    assert result["status"] == "no_new_events"
    assert result["checked_event_urls"] == ["https://tm.com/a"]


def test_only_the_genuinely_new_event_is_reported(monkeypatch):
    monkeypatch.setattr(
        lwm,
        "search_events_range",
        lambda **kwargs: fake_events([("Concert A", "https://tm.com/a"), ("Concert B", "https://tm.com/b")]),
    )
    item = {
        "city": "Denver",
        "mood_or_interest": "live music",
        "notified_event_urls": json.dumps(["https://tm.com/a"]),
    }

    result = lwm.evaluate_local_watch(item)

    assert result["status"] == "ok"
    assert "Concert B" in result["message"]
    assert result["booking_link"] == "https://tm.com/b"
    assert set(result["checked_event_urls"]) == {"https://tm.com/a", "https://tm.com/b"}


def test_no_events_at_all_is_an_honest_no_new_events(monkeypatch):
    monkeypatch.setattr(lwm, "search_events_range", lambda **kwargs: [])
    item = {"city": "Denver", "mood_or_interest": "live music", "notified_event_urls": "[]"}

    result = lwm.evaluate_local_watch(item)

    assert result["status"] == "no_new_events"
    assert result["checked_event_urls"] == []


def test_tracked_url_list_is_bounded(monkeypatch):
    many_urls = [f"https://tm.com/{i}" for i in range(lwm.MAX_TRACKED_EVENT_URLS)]
    monkeypatch.setattr(
        lwm, "search_events_range", lambda **kwargs: fake_events([("New one", "https://tm.com/new")])
    )
    item = {
        "city": "Denver",
        "mood_or_interest": "live music",
        "notified_event_urls": json.dumps(many_urls),
    }

    result = lwm.evaluate_local_watch(item)

    assert len(result["checked_event_urls"]) == lwm.MAX_TRACKED_EVENT_URLS
    assert "https://tm.com/new" in result["checked_event_urls"]
