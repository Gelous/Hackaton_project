"""tools/events.py's date-window and keyword-fallback behavior — both
discovered from live testing once a real Ticketmaster key was configured.

1. Keyword fallback: Ticketmaster's keyword search is literal (matched
   against event titles/descriptions), not semantic, so a mood like "live
   music" can return zero results even when real relevant events exist that
   day. Falling back to an unfiltered search for the same real city/date
   surfaces real data instead of an honest-but-unhelpful empty list.

2. Local-date window: Ticketmaster's startDateTime/endDateTime filter is
   UTC, so naively converting a local calendar date straight to UTC midnight
   silently clips evening events in any timezone behind UTC (an 8pm New York
   show is already past midnight UTC). _fetch_events pads the API query
   window by a day on each side and filters back down using each event's
   real local date, so the requested calendar day is never partially clipped.
"""

from trip_agent.tools import events as events_module


def fake_event(name, url="https://tm.com/x", local_date="2026-08-18", local_time="19:00:00"):
    return {
        "name": name,
        "url": url,
        "dates": {"start": {"localDate": local_date, "localTime": local_time}},
        "_embedded": {"venues": [{"name": "Test Venue", "location": {}}]},
        "classifications": [{"segment": {"name": "Music"}}],
    }


def test_falls_back_to_unfiltered_search_when_keyword_finds_nothing(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if "keyword" in params:
                    return {"_embedded": {"events": []}}
                return {"_embedded": {"events": [fake_event("Hamilton")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "live music", "", "", 8)

    assert len(calls) == 2
    assert calls[0]["keyword"] == "live music"
    assert "keyword" not in calls[1]
    assert len(results) == 1
    assert results[0]["name"] == "Hamilton"


def test_no_fallback_call_when_keyword_search_already_finds_results(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": [fake_event("Jazz Night")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "live music", "", "", 8)

    assert len(calls) == 1
    assert len(results) == 1


def test_no_fallback_call_when_no_keyword_was_given(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": []}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "", "", "", 8)

    assert len(calls) == 1
    assert results == []


def test_event_type_is_passed_as_classification_name(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": [fake_event("Knicks vs Nets")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "", "Sports", "", 8)

    assert len(calls) == 1
    assert calls[0]["classificationName"] == "Sports"
    assert len(results) == 1


def test_event_type_is_not_dropped_by_keyword_fallback(monkeypatch):
    """event_type is an explicit hard filter (a dropdown choice), unlike the
    free-text mood — the keyword-miss fallback should retry without the
    keyword but must keep classificationName in every request."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if "keyword" in params:
                    return {"_embedded": {"events": []}}
                return {"_embedded": {"events": [fake_event("Rangers Game")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "hockey night", "Sports", "", 8)

    assert len(calls) == 2
    assert all(c["classificationName"] == "Sports" for c in calls)
    assert len(results) == 1


def test_country_code_is_passed_through(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": [fake_event("Ciudad de Mexico Show")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("Mexico City", "2026-08-18", "2026-08-18", "", "", "MX", 8)

    assert len(calls) == 1
    assert calls[0]["countryCode"] == "MX"
    assert len(results) == 1


def test_country_code_is_not_dropped_by_keyword_fallback(monkeypatch):
    """Like event_type, country_code is a real geocoded fact, not a fuzzy
    mood nudge — the keyword-miss fallback must never drop it."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if "keyword" in params:
                    return {"_embedded": {"events": []}}
                return {"_embedded": {"events": [fake_event("Mariachi Night")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("Mexico City", "2026-08-18", "2026-08-18", "salsa night", "", "MX", 8)

    assert len(calls) == 2
    assert all(c["countryCode"] == "MX" for c in calls)
    assert len(results) == 1


def test_no_country_code_param_sent_when_not_provided(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": []}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "", "", "", 8)

    assert "countryCode" not in calls[0]


def test_falls_back_to_coordinates_when_city_name_finds_nothing(monkeypatch):
    """The Mexico City / Ciudad de México problem: Ticketmaster's internal
    city-name spelling doesn't always match what geocoding returns. When the
    city-name search finds nothing at all, a coordinate-radius search is
    tried instead — no static translation table needed."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if "city" in params:
                    return {"_embedded": {"events": []}}
                return {"_embedded": {"events": [fake_event("Lucha Libre Night")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events(
        "Mexico City", "2026-08-18", "2026-08-18", "", "", "MX", 8, latitude=19.4285, longitude=-99.1277
    )

    assert len(calls) == 2
    assert calls[0]["city"] == "Mexico City"
    assert calls[1]["latlong"] == "19.4285,-99.1277"
    assert calls[1]["radius"] == events_module.NEARBY_RADIUS_KM
    assert calls[1]["unit"] == "km"
    assert calls[1]["countryCode"] == "MX"
    assert len(results) == 1
    assert results[0]["name"] == "Lucha Libre Night"


def test_no_coordinate_fallback_when_city_name_search_already_finds_results(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": [fake_event("Real Madrid Match")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    events_module._fetch_events("Madrid", "2026-08-18", "2026-08-18", "", "", "ES", 8, latitude=40.4168, longitude=-3.7038)

    assert len(calls) == 1
    assert "latlong" not in calls[0]


def test_no_coordinate_fallback_when_no_coordinates_given(monkeypatch):
    """Graceful degradation for callers that don't have coordinates yet —
    stays exactly as honest as before (empty list), no crash."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": []}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("Mexico City", "2026-08-18", "2026-08-18", "", "", "MX", 8)

    assert len(calls) == 1
    assert results == []


def test_coordinate_fallback_keyword_also_falls_back_to_unfiltered(monkeypatch):
    """The coordinate tier gets the same keyword-relaxation treatment as the
    city-name tier — a mood/interest is still just a soft nudge there too.
    Both tiers try keyword-then-unfiltered before giving up, so a keyword
    that never matches anything costs 4 calls total: city+keyword,
    city+unfiltered, coords+keyword, coords+unfiltered."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if "city" in params or "keyword" in params:
                    return {"_embedded": {"events": []}}
                return {"_embedded": {"events": [fake_event("Mariachi Festival")]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events(
        "Mexico City", "2026-08-18", "2026-08-18", "live music", "", "MX", 8, latitude=19.4285, longitude=-99.1277
    )

    assert len(calls) == 4
    assert calls[0]["city"] == "Mexico City" and calls[0]["keyword"] == "live music"
    assert calls[1]["city"] == "Mexico City" and "keyword" not in calls[1]
    assert calls[2]["latlong"] == "19.4285,-99.1277" and calls[2]["keyword"] == "live music"
    assert calls[3]["latlong"] == "19.4285,-99.1277" and "keyword" not in calls[3]
    assert len(results) == 1


def test_search_events_clamps_max_events_between_1_and_5(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": [fake_event(f"Event {i}") for i in range(10)]}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    output = events_module.search_events("New York", "2026-08-18", max_events=9)
    results = output["content"][0]["json"]["named_options"]

    assert len(results) == 5


def test_query_window_is_padded_a_day_on_each_side(monkeypatch):
    """The bug this guards against: querying startDateTime=2026-08-18T00:00:00Z
    to endDateTime=2026-08-18T23:59:59Z misses an 8pm New York show, since
    that's already past midnight UTC (into the 19th). The API call itself
    must span a wider UTC window than the requested calendar day."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params))

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"_embedded": {"events": []}}

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "", "", "", 5)

    assert calls[0]["startDateTime"] == "2026-08-17T00:00:00Z"
    assert calls[0]["endDateTime"] == "2026-08-19T23:59:59Z"


def test_events_outside_requested_local_date_are_filtered_out(monkeypatch):
    """Even though the query window is padded wider than the requested day,
    an event that's genuinely on an adjacent day (returned because it fell
    inside the padded UTC window) must not leak into the result."""

    def fake_get(url, params=None, timeout=None):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "_embedded": {
                        "events": [
                            fake_event("Late Night Show", local_date="2026-08-18", local_time="23:30:00"),
                            fake_event("Next Day Matinee", local_date="2026-08-19", local_time="14:00:00"),
                            fake_event("Prior Day Closing Night", local_date="2026-08-17", local_time="22:00:00"),
                        ]
                    }
                }

        return FakeResponse()

    monkeypatch.setattr(events_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TICKETMASTER_API_KEY", "fake-key")

    results = events_module._fetch_events("New York", "2026-08-18", "2026-08-18", "", "", "", 5)

    assert [r["name"] for r in results] == ["Late Night Show"]
