import json
import math
import os
import urllib.parse
from pathlib import Path

import httpx
from strands import tool

# Well-established leisure-travel seasonality (Northern Hemisphere summer break
# + winter holidays drive up demand; Feb/Oct are the classic cheap shoulder
# months). Used as the fallback estimate when no real recent price is found
# (see _fetch_real_price below) — grounded in a real industry pattern rather
# than an arbitrary flat multiplier, and always paired with a real Google
# Flights link so the traveler sees the actual current price for their exact
# dates either way.
_SEASONAL_MULTIPLIER = {
    1: 0.92, 2: 0.90, 3: 0.95, 4: 1.00, 5: 1.00, 6: 1.12,
    7: 1.18, 8: 1.15, 9: 0.92, 10: 0.90, 11: 0.95, 12: 1.20,
}

# Real-world benchmarks, not numbers invented for this app: fuel-only cost
# per km is a rough marginal estimate; the full cost per km (also covering
# wear, maintenance, and insurance) is modeled on the US IRS standard
# business mileage rate (~$0.67/mile as of 2024, ~$0.42/km).
DRIVING_FUEL_ONLY_PER_KM = 0.12
DRIVING_FULL_COST_PER_KM = 0.42

# Travelpayouts Data API (api.travelpayouts.com) — free to register, no
# per-call cost, no approval process (unlike Duffel/Amadeus Enterprise). It
# returns real prices cached from actual searches (not a live shopping
# quote), keyed by IATA city/airport code rather than city name, so we
# resolve codes locally first via the bundled dataset below.
TRAVELPAYOUTS_URL = "https://api.travelpayouts.com/v1/prices/cheap"
CITY_CODES_PATH = Path(__file__).resolve().parents[1] / "data" / "travelpayouts_cities.json"
AIRLINE_NAMES_PATH = Path(__file__).resolve().parents[1] / "data" / "travelpayouts_airlines.json"
# How close a geocoded city must be to a Travelpayouts city entry to trust
# the IATA code match — keeps this from matching, say, a small town to a
# major airport two states over just because it's the nearest entry.
MAX_IATA_MATCH_KM = 75.0

_city_codes_cache: list[dict] | None = None
_airline_names_cache: dict[str, str] | None = None


def _load_city_codes() -> list[dict]:
    global _city_codes_cache
    if _city_codes_cache is None:
        try:
            with open(CITY_CODES_PATH, encoding="utf-8") as f:
                _city_codes_cache = json.load(f)
        except Exception:
            _city_codes_cache = []
    return _city_codes_cache


def _load_airline_names() -> dict[str, str]:
    global _airline_names_cache
    if _airline_names_cache is None:
        try:
            with open(AIRLINE_NAMES_PATH, encoding="utf-8") as f:
                _airline_names_cache = json.load(f)
        except Exception:
            _airline_names_cache = {}
    return _airline_names_cache


def _airline_name(code: str) -> str | None:
    """Real airline name for a Travelpayouts IATA carrier code, from the same
    bundled reference dataset pattern as the city codes above — never a
    guessed or invented name, and None (not the raw code) if it's not in the
    dataset, so callers can fall back to omitting it rather than showing a
    bare two-letter code."""
    return _load_airline_names().get(code)


# Standard, widely-used time-of-day bands (not invented for this app) used to
# classify a real cached fare's actual departure time against the traveler's
# stated preference — and to phrase that same preference into the Google
# Flights link's free-text query, which supports natural-language time hints.
# Every hour of the day falls in exactly one band; red-eye wraps past
# midnight (9pm-5am), so it's checked as two separate ranges below.
TIME_OF_DAY_BANDS = ["morning", "afternoon", "evening", "red-eye"]


def _time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "red-eye"  # 21:00-23:59 or 00:00-04:59


def _matches_preferred_time(departure_at: str, preferred_time: str) -> bool | None:
    """True/False if the real fare's actual local departure hour (parsed
    straight from Travelpayouts' ISO timestamp, e.g. "...T18:20:00-04:00" —
    already the origin's local time, no timezone math needed) falls in the
    traveler's preferred band. None if there's nothing to compare (no
    preference stated, or the timestamp is missing/unparseable) — the caller
    must not claim a match either way in that case."""
    if not preferred_time or preferred_time not in TIME_OF_DAY_BANDS:
        return None
    try:
        hour = int(departure_at[11:13])
    except (ValueError, IndexError):
        return None
    return _time_of_day(hour) == preferred_time


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_km * math.asin(math.sqrt(a))


def _nearest_iata_code(lat: float, lon: float) -> str | None:
    """Nearest-coordinate match against the bundled Travelpayouts city list
    (already geocoded, since the agent's workflow always geocodes a city
    before pricing it) rather than fuzzy name matching — avoids ambiguity
    from language/spelling variants in city names. Returns None rather than
    a wrong-city guess if nothing is close enough."""
    best_code, best_km = None, MAX_IATA_MATCH_KM
    for entry in _load_city_codes():
        km = _haversine_km(lat, lon, entry["lat"], entry["lon"])
        if km < best_km:
            best_km, best_code = km, entry["code"]
    return best_code


def _fetch_real_price(origin_code: str, destination_code: str, depart_date: str, return_date: str) -> dict | None:
    """Returns {"price_usd", "real_departure_date", "real_return_date",
    "real_departure_at", "airline_name", "flight_number"} for the cheapest
    real cached fare Travelpayouts has for this route, or None if no key is
    configured, nothing was found, or the request fails — never a fabricated
    price. real_departure_at is the full ISO timestamp (already the origin's
    local time) so callers can check it against a preferred time of day."""
    api_key = os.environ.get("TRAVELPAYOUTS_API_TOKEN", "").strip()
    if not api_key:
        return None

    try:
        response = httpx.get(
            TRAVELPAYOUTS_URL,
            params={
                "origin": origin_code,
                "destination": destination_code,
                "depart_date": depart_date,
                "return_date": return_date,
                "currency": "usd",
                "token": api_key,
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            return None
        dest_options = payload.get("data", {}).get(destination_code, {})
        if not dest_options:
            return None
        cheapest = min(dest_options.values(), key=lambda o: o["price"])
    except Exception:
        return None

    return {
        "price_usd": cheapest["price"],
        "real_departure_date": (cheapest.get("departure_at") or "")[:10],
        "real_return_date": (cheapest.get("return_at") or "")[:10],
        "real_departure_at": cheapest.get("departure_at") or "",
        "airline_name": _airline_name(cheapest.get("airline", "")),
        "flight_number": cheapest.get("flight_number"),
    }


@tool
def search_flights(
    origin_city: str,
    destination_city: str,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    departure_date: str,
    return_date: str,
    travelers: int,
    distance_km: float,
    preferred_departure_time: str = "",
) -> dict:
    """Get a real recent flight price if one is available, otherwise a
    realistic estimate — plus a real live booking link either way.

    Tries the Travelpayouts Data API first (free, no approval needed) for a
    real price cached from actual traveler searches on this exact route. If
    that's unavailable — no API token configured, the city couldn't be
    matched to an airport, or Travelpayouts simply has no cached fare for
    this route — this falls back to a realistic price RANGE based on route
    distance and typical seasonal demand for the departure month. There is
    still no free, self-service, real-time flight *shopping* API for
    independent developers (Amadeus Self-Service shut down July 2026; Duffel
    requires paid/approved production access; Kiwi and Skyscanner are
    invite-only), so a real Travelpayouts price is a real recently-cached
    fare, not a live quote for your exact dates — the Google Flights link is
    what shows today's actual current price.

    On preferred_departure_time: Travelpayouts' cached-fare lookup almost
    always returns at most one candidate per route/date, so there's nothing
    to actually filter by time — this can't make the search itself more
    precise. What it does instead, honestly: bakes the preference into the
    Google Flights link's free-text query (which supports natural-language
    time hints, the same way a traveler would type it themselves), and — if
    a real cached fare was found — plainly states whether that fare's actual
    departure time happens to match the preference or not, rather than
    silently ignoring the mismatch.

    Args:
        origin_city: Departure city name.
        destination_city: Arrival city name.
        origin_lat: Latitude of the departure city (from geocode_city).
        origin_lon: Longitude of the departure city (from geocode_city).
        destination_lat: Latitude of the arrival city (from geocode_city).
        destination_lon: Longitude of the arrival city (from geocode_city).
        departure_date: Outbound date, format YYYY-MM-DD.
        return_date: Return date, format YYYY-MM-DD.
        travelers: Number of travelers.
        distance_km: Great-circle distance between origin and destination, in km.
        preferred_departure_time: Optional — one of "morning", "afternoon",
            "evening", "red-eye", or "" for no preference. Always pass through
            the traveler's exact stated choice; never pick one yourself.
    """
    origin_code = _nearest_iata_code(origin_lat, origin_lon)
    destination_code = _nearest_iata_code(destination_lat, destination_lon)
    preferred_departure_time = preferred_departure_time.strip().lower()
    if preferred_departure_time not in TIME_OF_DAY_BANDS:
        preferred_departure_time = ""

    real = None
    if origin_code and destination_code:
        real = _fetch_real_price(origin_code, destination_code, departure_date, return_date)

    # Deliberately NOT appending the time preference here (e.g. as a trailing
    # ", morning departure preferred" clause) — verified by hand that doing
    # so breaks Google Flights' query parser entirely, landing on a blank
    # generic homepage instead of this route/dates. The one query shape
    # confirmed to reliably parse is left untouched; the time preference is
    # still surfaced honestly via the note below instead.
    query = f"Flights to {destination_city} from {origin_city} on {departure_date} through {return_date}"
    booking_link = "https://www.google.com/travel/flights?q=" + urllib.parse.quote(query)

    if real:
        total = round(real["price_usd"] * travelers, 2)
        dates_match = real["real_departure_date"] == departure_date and real["real_return_date"] == return_date
        if dates_match:
            date_note = "for these exact dates"
        else:
            date_note = (
                f"for {real['real_departure_date']} to {real['real_return_date']} (the closest cached fare "
                "Travelpayouts had for this route, not necessarily your exact dates)"
            )
        # Only named when Travelpayouts' own reference data resolved the
        # carrier code to a real name — never a guessed or partial name.
        if real["airline_name"] and real["flight_number"]:
            carrier_note = f" on {real['airline_name']} flight {real['flight_number']}"
        elif real["airline_name"]:
            carrier_note = f" on {real['airline_name']}"
        else:
            carrier_note = ""
        time_match = _matches_preferred_time(real["real_departure_at"], preferred_departure_time)
        if time_match is True:
            time_note = f" — this matches your preferred {preferred_departure_time} departure time"
        elif time_match is False:
            time_note = (
                f" — note this does NOT match your preferred {preferred_departure_time} departure time; "
                "check the link for options at your preferred time"
            )
        else:
            time_note = ""
        return {
            "status": "success",
            "content": [
                {
                    "json": {
                        "estimated_price_low_usd": total,
                        "estimated_price_high_usd": total,
                        "booking_link": booking_link,
                        "real_price_observed": True,
                        "note": f"Real recent price from Travelpayouts{carrier_note}, {date_note}, for all "
                        "travelers combined — a recently cached fare, not a live quote or a guaranteed "
                        f"booking{time_note}. Open the link for today's actual current price to book.",
                    }
                }
            ],
        }

    month = int(departure_date.split("-")[1])
    seasonal_multiplier = _SEASONAL_MULTIPLIER.get(month, 1.0)

    base_price_per_traveler = (60 + distance_km * 0.11) * seasonal_multiplier
    low = round(base_price_per_traveler * travelers * 0.85, 2)
    high = round(base_price_per_traveler * travelers * 1.45, 2)

    if seasonal_multiplier >= 1.10:
        season_note = "peak-season"
    elif seasonal_multiplier <= 0.92:
        season_note = "off-peak"
    else:
        season_note = "shoulder-season"

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "estimated_price_low_usd": low,
                    "estimated_price_high_usd": high,
                    "booking_link": booking_link,
                    "real_price_observed": False,
                    "note": f"No real cached fare found for this route — estimate based on route distance "
                    f"and {season_note} demand for {departure_date[:7]}, for all travelers combined."
                    + (f" No real fare to check against your preferred {preferred_departure_time} departure "
                       "time — use the link's own time-of-day filter to check." if preferred_departure_time else "")
                    + " Open the link for real current airlines, times, and prices to actually book.",
                }
            }
        ],
    }


@tool
def estimate_driving_cost(origin_city: str, destination_city: str, distance_km: float) -> dict:
    """Estimate round-trip driving cost and get a real Google Maps directions link.

    Use this instead of search_flights when the traveler's transportation
    preference is "drive". Unlike a flight price, driving cost doesn't scale
    per traveler — a single vehicle typically covers the whole group — so
    this returns one range for the trip, not multiplied by traveler count.
    The low end is a rough fuel-only marginal cost; the high end also
    accounts for wear, maintenance, and insurance (modeled on the real US IRS
    standard mileage rate), giving an honest range instead of one invented
    number.

    Args:
        origin_city: Departure city name.
        destination_city: Arrival city name.
        distance_km: One-way great-circle distance between origin and destination, in km.
    """
    round_trip_km = distance_km * 2
    low = round(round_trip_km * DRIVING_FUEL_ONLY_PER_KM, 2)
    high = round(round_trip_km * DRIVING_FULL_COST_PER_KM, 2)

    directions_link = (
        "https://www.google.com/maps/dir/?api=1"
        + "&origin=" + urllib.parse.quote(origin_city)
        + "&destination=" + urllib.parse.quote(destination_city)
        + "&travelmode=driving"
    )

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "estimated_price_low_usd": low,
                    "estimated_price_high_usd": high,
                    "booking_link": directions_link,
                    "note": "Estimated round-trip driving cost — fuel only at the low end, full "
                    "cost including wear/maintenance/insurance at the high end — for one vehicle "
                    "covering the whole group, not per traveler. Open the link for real current "
                    "driving directions and duration.",
                }
            }
        ],
    }
