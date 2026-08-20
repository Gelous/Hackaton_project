import os
import urllib.parse
from datetime import date as date_cls
from datetime import timedelta

import httpx
from strands import tool

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"

# Ticketmaster's own top-level segment names — a real, structured filter
# (classificationName) as opposed to the free-text `keyword` field, which is
# literal/substring matching against titles. "" means no filter (any type).
EVENT_TYPES = ["Music", "Sports", "Arts & Theatre", "Film", "Miscellaneous"]

# Last-resort fallback radius (km) for the coordinate-based search — see
# _fetch_events below for why this exists. Tight enough to stay within the
# same metro area (not pull in a neighboring city's events), wide enough to
# catch major venues that sit a bit outside a city's literal center.
NEARBY_RADIUS_KM = 20


def _ticketmaster_search_link(city_name: str) -> str:
    """Official Ticketmaster search URL — not scraping, just a real link the
    traveler can open to see current listings themselves."""
    return "https://www.ticketmaster.com/search?q=" + urllib.parse.quote(city_name)


def _fetch_events_raw(
    location_params: dict, start_iso: str, end_iso: str, keyword: str, event_type: str, country_code: str, api_key: str, max_results: int
) -> list[dict]:
    """location_params is either {"city": name} or a coordinate locator
    ({"latlong": "lat,lon", "radius": N, "unit": "km"}) — see _fetch_events."""
    params = {
        "apikey": api_key,
        "startDateTime": start_iso,
        "endDateTime": end_iso,
        "size": max_results,
        "sort": "relevance,desc",
        **location_params,
    }
    if keyword:
        params["keyword"] = keyword
    if event_type:
        params["classificationName"] = event_type
    if country_code:
        params["countryCode"] = country_code

    try:
        response = httpx.get(TICKETMASTER_URL, params=params, timeout=8)
        response.raise_for_status()
        events = response.json().get("_embedded", {}).get("events", [])
    except Exception:
        return []

    results = []
    for ev in events:
        name = ev.get("name")
        ticket_link = ev.get("url")
        if not name or not ticket_link:
            continue
        venue = (ev.get("_embedded", {}).get("venues") or [{}])[0]
        start = ev.get("dates", {}).get("start", {})
        classification = (ev.get("classifications") or [{}])[0]
        location = venue.get("location", {})
        results.append(
            {
                "name": name,
                "category": (classification.get("segment") or {}).get("name", "Event"),
                "date": start.get("localDate", ""),
                "time": start.get("localTime", ""),
                "venue_name": venue.get("name", ""),
                "ticket_link": ticket_link,
                "lat": float(location["latitude"]) if location.get("latitude") else None,
                "lon": float(location["longitude"]) if location.get("longitude") else None,
            }
        )
        if len(results) >= max_results:
            break

    return results


def _fetch_events(
    city_name: str,
    start_date: str,
    end_date: str,
    mood_or_interest: str,
    event_type: str,
    country_code: str,
    max_results: int,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[dict]:
    """Shared Ticketmaster fetch + parse behind search_events (single day,
    exposed to the Day Planner agent) and search_events_range (multi-day
    window, called directly by local_watch_monitor.py with no LLM involved —
    same pattern as wishlist_monitor.py calling search_flights directly).
    Returns an empty list — never a fabricated event — if no API key is
    configured or the request fails.

    start_date/end_date are plain YYYY-MM-DD calendar dates in the venue's
    local time. Ticketmaster's startDateTime/endDateTime filter is UTC, so
    naively converting a local calendar date straight to UTC midnight (e.g.
    2026-08-18T00:00:00Z to 2026-08-18T23:59:59Z) silently clips evening
    events in any timezone behind UTC — an 8pm New York show is already past
    midnight UTC. To stay correct for any city, the API query window is
    padded a day on each side, then results are filtered back down using
    each event's real local date (which Ticketmaster returns per-event) so
    the window always matches what the traveler actually asked for.

    country_code (ISO 3166-1 alpha-2, e.g. "MX") disambiguates city names
    that exist in multiple countries (a bare "city" match alone can't tell
    Paris, France from Paris, Texas) — real, structured data from
    geocode_city, never guessed.

    If the city-name search finds nothing at all, and real coordinates were
    given, this retries once more using a coordinate-radius search instead
    of the city name — Ticketmaster's own internal city-name spelling
    doesn't always match what geocoding returns (e.g. "Mexico City" vs. the
    "Ciudad de México" their database actually stores), and there's no
    complete, reliable static translation table for every city on Earth.
    Searching by real coordinates sidesteps the spelling question entirely
    instead of guessing at a name."""
    api_key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    if not api_key:
        return []

    query_start = (date_cls.fromisoformat(start_date) - timedelta(days=1)).isoformat() + "T00:00:00Z"
    query_end = (date_cls.fromisoformat(end_date) + timedelta(days=1)).isoformat() + "T23:59:59Z"
    # Padding pulls in extra days we then filter out, so fetch a larger page
    # than max_results to still have enough left after the local-date filter.
    fetch_size = min(200, max(50, max_results * 10))

    def _in_range_events(keyword: str, location_params: dict) -> list[dict]:
        raw = _fetch_events_raw(location_params, query_start, query_end, keyword, event_type, country_code, api_key, fetch_size)
        in_range = [ev for ev in raw if ev.get("date") and start_date <= ev["date"] <= end_date]
        return in_range[:max_results]

    keyword = mood_or_interest.strip()
    event_type = event_type.strip()
    country_code = country_code.strip()

    city_loc = {"city": city_name}
    results = _in_range_events(keyword, city_loc)

    if not results and keyword:
        # Ticketmaster's keyword search is literal (matched against event
        # titles/descriptions), not semantic — a mood like "live music" won't
        # match an event literally titled "Hamilton" even though it's a real
        # live show. Falling back to an unfiltered-by-keyword search for the
        # same real date/city — instead of reporting nothing when real events
        # do exist — is still fully honest: every event is real, just not
        # guaranteed to match the stated mood as literally as the keyword
        # filter would. event_type/country_code are left in place here:
        # unlike the mood text, they're explicit hard filters (a dropdown, a
        # geocoded fact), not a fuzzy nudge, so they're never what gets
        # relaxed.
        results = _in_range_events("", city_loc)

    if not results and latitude is not None and longitude is not None:
        coord_loc = {"latlong": f"{latitude},{longitude}", "radius": NEARBY_RADIUS_KM, "unit": "km"}
        results = _in_range_events(keyword, coord_loc)
        if not results and keyword:
            results = _in_range_events("", coord_loc)

    return results


@tool
def search_events(
    city_name: str,
    date: str,
    mood_or_interest: str = "",
    event_type: str = "",
    max_events: int = 5,
    country_code: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    """Find real local events (concerts, shows, sports, etc.) happening in a city on a given day.

    Uses the Ticketmaster Discovery API — real event names, venues, times, and
    ticket links — when a TICKETMASTER_API_KEY is configured (free signup at
    developer.ticketmaster.com). This never invents an event: if no API key is
    set, or the API returns nothing for that city/date, this returns an empty
    list plus a real Ticketmaster search link so the traveler can still check
    themselves — an empty list is the honest answer, not a reason to make one up.

    Args:
        city_name: City to search events in.
        date: The day to search, format YYYY-MM-DD. Events are searched for
            that full calendar day.
        mood_or_interest: Optional free-text mood/interest to softly bias
            results, e.g. "live music", "chill", "romantic". This is a nudge,
            not a hard filter — pass through exactly what the traveler said,
            don't invent your own.
        event_type: Optional hard category filter — one of "Music", "Sports",
            "Arts & Theatre", "Film", "Miscellaneous", or "" for any type.
            Always pass through the traveler's exact stated choice; never pick
            one yourself.
        max_events: Maximum number of events to return, 1-5. Always pass
            through the traveler's exact stated count; never pick one yourself.
        country_code: The ISO 3166-1 alpha-2 country_code geocode_city returned
            for this city (e.g. "MX", "FR") — always pass it through when you
            have it, so a city name that exists in multiple countries (e.g.
            Paris, France vs. Paris, Texas) resolves to the right one.
        latitude: The latitude geocode_city returned for this city — always
            pass it through when you have it. Used only as a last-resort
            fallback if searching by city name finds nothing at all, since
            Ticketmaster's own internal spelling for a city doesn't always
            match what geocoding returns.
        longitude: The longitude geocode_city returned for this city — same
            as latitude above, always pass it through when you have it.
    """
    max_events = max(1, min(5, max_events))
    results = _fetch_events(
        city_name, date, date, mood_or_interest, event_type, country_code, max_events, latitude, longitude
    )

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "named_options": results,
                    "search_link": _ticketmaster_search_link(city_name),
                    "note": "named_options are specific real events from Ticketmaster when "
                    "available. Ticketmaster's mood/interest matching is literal, not semantic — "
                    "if the mood search found nothing, this falls back to real events unfiltered "
                    "by mood (still respecting event_type) for the same city/date, so don't claim "
                    "a listed event matches the stated mood unless its name or category actually "
                    "suggests it does. If still empty, use search_link and don't invent a specific "
                    "event, date, or ticket price.",
                }
            }
        ],
    }


def search_events_range(
    city_name: str,
    start_date: str,
    end_date: str,
    mood_or_interest: str = "",
    event_type: str = "",
    country_code: str = "",
    max_results: int = 20,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[dict]:
    """Not an agent tool — called directly by local_watch_monitor.py (no LLM
    involved) to check for real events across a multi-day window, e.g. the
    next 14 days, for a proactive "watch this city" subscription. Returns an
    empty list if no API key is configured or nothing was found; the caller
    is responsible for treating that as an honest "nothing new," never a
    reason to invent something. latitude/longitude are the same last-resort
    coordinate fallback as search_events — see _fetch_events."""
    return _fetch_events(
        city_name, start_date, end_date, mood_or_interest, event_type, country_code, max_results, latitude, longitude
    )
