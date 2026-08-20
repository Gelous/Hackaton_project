import math
import urllib.parse

from strands import tool

from .places import _maps_search_link, _try_overpass

# Same well-established leisure-travel seasonality used for flights (Northern
# Hemisphere summer break + winter holidays drive up demand; Feb/Oct are the
# classic cheap shoulder months) — hotel demand tracks the same real pattern,
# not a separate arbitrary number set.
_SEASONAL_MULTIPLIER = {
    1: 0.92, 2: 0.90, 3: 0.95, 4: 1.00, 5: 1.00, 6: 1.12,
    7: 1.18, 8: 1.15, 9: 0.92, 10: 0.90, 11: 0.95, 12: 1.20,
}

MAX_HOTEL_OPTIONS = 5
HOTEL_SEARCH_RADIUS_M = 4000


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_km * math.asin(math.sqrt(a))


def _search_real_hotels(lat: float, lon: float, city_name: str, pref: str) -> list[dict]:
    """Real, named hotels/hostels near the coordinates, via the same
    best-effort OpenStreetMap lookup already used for restaurants/
    activities (see places.py) — no fabricated name ever fills a gap here.
    OpenStreetMap doesn't reliably carry price or star-rating data (checked
    by hand — it's essentially never populated), so there's no honest way to
    rank these by "quality" or real price; sorting by distance to the
    destination center is a real, defensible proxy (closest to where the
    traveler will actually be spending their time) rather than a guessed
    value score."""
    want_budget_only = "budget" in pref or "hostel" in pref
    tag_filter = 'node["tourism"="hostel"]' if want_budget_only else 'node["tourism"~"hotel|hostel"]'
    query = f"""
    [out:json][timeout:8];
    (
      {tag_filter}(around:{HOTEL_SEARCH_RADIUS_M},{lat},{lon});
    );
    out body {MAX_HOTEL_OPTIONS * 4};
    """
    elements = _try_overpass(query)

    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        el_lat, el_lon = el.get("lat"), el.get("lon")
        if not name or el_lat is None or el_lon is None:
            continue
        results.append(
            {
                "name": name,
                "category": tags.get("tourism", "hotel"),
                "lat": el_lat,
                "lon": el_lon,
                "maps_link": _maps_search_link(f"{name}, {city_name}"),
                "_distance_km": _haversine_km(lat, lon, el_lat, el_lon),
            }
        )

    results.sort(key=lambda r: r["_distance_km"])
    for r in results:
        del r["_distance_km"]
    return results[:MAX_HOTEL_OPTIONS]


@tool
def search_hotels(
    destination_city: str,
    check_in: str,
    check_out: str,
    travelers: int,
    accommodation_preference: str = "any",
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    """Estimate nightly hotel cost, find real hotels the traveler can actually
    choose between, and get a real live booking link.

    There is no free, self-service real-time hotel pricing API available to
    independent developers with the coverage of Booking.com/Expedia (those
    require an approved partner/affiliate agreement), so the price is a
    realistic nightly RANGE (for budget planning only, weighted by the same
    real seasonal-demand pattern used for flights) — never a specific
    confirmed rate, even for a hotel named below. Real hotel *names* are a
    separate, achievable thing though: when latitude/longitude are given,
    this also searches OpenStreetMap for real hotels/hostels matching the
    requested tier near that location (best-effort, may come back empty) —
    genuinely real places the traveler can pick from, sorted by distance to
    the destination center (the only honest ranking signal available; OSM
    doesn't reliably carry price or star-rating data). Also returns a real
    Booking.com search link pre-filled with the destination, exact check-in/
    check-out dates, and traveler count — that link shows real current
    hotels, ratings, and prices, and the traveler completes the actual
    booking/payment there. (Google Hotels was tried first, but it has no
    reliable public URL parameter for dates — checkin/checkout query params
    are silently ignored — so this uses Booking.com's real, documented
    search URL instead, which was verified to correctly apply both dates.)

    Args:
        destination_city: City to search hotels in.
        check_in: Check-in date, format YYYY-MM-DD.
        check_out: Check-out date, format YYYY-MM-DD.
        travelers: Number of travelers (used to note if multiple rooms may be needed).
        accommodation_preference: Free-text preference, e.g. "budget hostel",
            "mid-range hotel", "luxury", "boutique". Defaults to "any".
        latitude: Latitude of the destination (from geocode_city) — enables
            the real named-hotel search. Always pass it through when you have it.
        longitude: Longitude of the destination (from geocode_city) — same as latitude.
    """
    pref = accommodation_preference.lower()
    if "budget" in pref or "hostel" in pref:
        base_range = (35, 95)
    elif "luxury" in pref:
        base_range = (280, 650)
    elif "boutique" in pref:
        base_range = (150, 320)
    else:
        base_range = (90, 220)

    month = int(check_in.split("-")[1])
    seasonal_multiplier = _SEASONAL_MULTIPLIER.get(month, 1.0)
    price_range = (round(base_range[0] * seasonal_multiplier, 2), round(base_range[1] * seasonal_multiplier, 2))

    if seasonal_multiplier >= 1.10:
        season_note = "peak-season"
    elif seasonal_multiplier <= 0.92:
        season_note = "off-peak"
    else:
        season_note = "shoulder-season"

    named_options = []
    if latitude is not None and longitude is not None:
        named_options = _search_real_hotels(latitude, longitude, destination_city, pref)

    booking_link = (
        "https://www.booking.com/searchresults.html?ss="
        + urllib.parse.quote(destination_city)
        + f"&checkin={check_in}&checkout={check_out}&group_adults={max(1, travelers)}"
    )

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "estimated_price_low_usd": price_range[0],
                    "estimated_price_high_usd": price_range[1],
                    "booking_link": booking_link,
                    "named_options": named_options,
                    "note": f"Nightly estimate based on the requested accommodation tier and "
                    f"{season_note} demand for {check_in[:7]} — a general range, not a confirmed "
                    "rate for any specific hotel, even a named one. Open the link for real current "
                    "hotels, ratings, and prices for these exact dates to actually book.",
                }
            }
        ],
    }
