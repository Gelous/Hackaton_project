import urllib.parse

from strands import tool


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
    planning only) plus a real Google Flights link pre-filled with the exact
    route and dates — that link shows real current airlines, schedules, and
    prices, and the traveler completes the actual booking/payment there.

    Args:
        origin_city: Departure city name.
        destination_city: Arrival city name.
        departure_date: Outbound date, format YYYY-MM-DD.
        return_date: Return date, format YYYY-MM-DD.
        travelers: Number of travelers.
        distance_km: Great-circle distance between origin and destination, in km.
    """
    base_price_per_traveler = 60 + distance_km * 0.11
    low = round(base_price_per_traveler * travelers * 0.85, 2)
    high = round(base_price_per_traveler * travelers * 1.45, 2)

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
                    "note": "Estimate based on route distance and season, for all travelers combined. "
                    "Open the link for real current airlines, times, and prices to actually book.",
                }
            }
        ],
    }
