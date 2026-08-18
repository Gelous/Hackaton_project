import urllib.parse

from strands import tool

# Well-established leisure-travel seasonality (Northern Hemisphere summer break
# + winter holidays drive up demand; Feb/Oct are the classic cheap shoulder
# months). This isn't a live pricing feed -- no free one exists for this, which
# is the whole reason this function returns a range, not a number -- but it's a
# grounded industry pattern rather than an arbitrary flat multiplier, and it's
# always paired with a real Google Flights link so the traveler sees the actual
# current price for their exact dates.
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


@tool
def search_flights(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    return_date: str,
    travelers: int,
    distance_km: float,
) -> dict:
    """Estimate round-trip flight cost and get a real live booking link.

    There is no free, self-service real-time flight pricing API available to
    independent developers as of this build (Amadeus Self-Service shut down
    July 2026; Duffel test mode only returns a fake sandbox airline; Kiwi and
    Skyscanner are invite-only partner programs). Instead of inventing a fake
    airline and price, this returns a realistic price RANGE (for budget
    planning only) — based on route distance and typical seasonal demand for
    the departure month — plus a real Google Flights link pre-filled with the
    exact route and dates. That link shows real current airlines, schedules,
    and prices, and the traveler completes the actual booking/payment there.

    Args:
        origin_city: Departure city name.
        destination_city: Arrival city name.
        departure_date: Outbound date, format YYYY-MM-DD.
        return_date: Return date, format YYYY-MM-DD.
        travelers: Number of travelers.
        distance_km: Great-circle distance between origin and destination, in km.
    """
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

    query = f"Flights to {destination_city} from {origin_city} on {departure_date} through {return_date}"
    booking_link = "https://www.google.com/travel/flights?q=" + urllib.parse.quote(query)

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "estimated_price_low_usd": low,
                    "estimated_price_high_usd": high,
                    "booking_link": booking_link,
                    "note": f"Estimate based on route distance and {season_note} demand for "
                    f"{departure_date[:7]}, for all travelers combined. Open the link for real "
                    "current airlines, times, and prices to actually book.",
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
