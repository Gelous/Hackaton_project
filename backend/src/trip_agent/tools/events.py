import os
import urllib.parse

import httpx
from strands import tool

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


def _ticketmaster_search_link(city_name: str) -> str:
    """Official Ticketmaster search URL — not scraping, just a real link the
    traveler can open to see current listings themselves."""
    return "https://www.ticketmaster.com/search?q=" + urllib.parse.quote(city_name)


def _fetch_events(city_name: str, start_iso: str, end_iso: str, mood_or_interest: str, max_results: int) -> list[dict]:
    """Shared Ticketmaster fetch + parse behind search_events (single day,
    exposed to the Day Planner agent) and search_events_range (multi-day
    window, called directly by local_watch_monitor.py with no LLM involved —
    same pattern as wishlist_monitor.py calling search_flights directly).
    Returns an empty list — never a fabricated event — if no API key is
    configured or the request fails."""
    api_key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    if not api_key:
        return []

    params = {
        "apikey": api_key,
        "city": city_name,
        "startDateTime": start_iso,
        "endDateTime": end_iso,
        "size": max_results,
        "sort": "relevance,desc",
    }
    if mood_or_interest.strip():
        params["keyword"] = mood_or_interest.strip()

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


@tool
def search_events(city_name: str, date: str, mood_or_interest: str = "") -> dict:
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
        mood_or_interest: Optional free-text mood/interest to bias results,
            e.g. "live music", "chill", "family friendly", "comedy". Leave
            blank to search broadly.
    """
    results = _fetch_events(city_name, f"{date}T00:00:00Z", f"{date}T23:59:59Z", mood_or_interest, max_results=8)

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "named_options": results,
                    "search_link": _ticketmaster_search_link(city_name),
                    "note": "named_options are specific real events from Ticketmaster when "
                    "available. If empty, use search_link and don't invent a specific event, "
                    "date, or ticket price.",
                }
            }
        ],
    }


def search_events_range(city_name: str, start_date: str, end_date: str, mood_or_interest: str = "") -> list[dict]:
    """Not an agent tool — called directly by local_watch_monitor.py (no LLM
    involved) to check for real events across a multi-day window, e.g. the
    next 14 days, for a proactive "watch this city" subscription. Returns an
    empty list if no API key is configured or nothing was found; the caller
    is responsible for treating that as an honest "nothing new," never a
    reason to invent something."""
    return _fetch_events(city_name, f"{start_date}T00:00:00Z", f"{end_date}T23:59:59Z", mood_or_interest, max_results=20)
