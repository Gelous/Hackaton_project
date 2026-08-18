"""Wishlist evaluation — deliberately NOT an LLM call.

The one Strands agent invocation the wishlist feature needs happens once, at
creation time, to pick a destination (see agent.recommend_destination).
Ongoing re-checks just call the same tool functions the main agent uses
(weather, distance, flights) directly, compare a few candidate windows within
the traveler's flexible date range, and report the one with the best-looking
weather — same real-data-only principle as the rest of the app, at a fraction
of the cost of a repeated Bedrock call per item per week.
"""

from datetime import date, timedelta

from .currency import SUPPORTED_CURRENCIES, convert
from .tools.flights import search_flights
from .tools.routing import estimate_distance
from .tools.weather import get_weather_forecast

MAX_CANDIDATE_WINDOWS = 3


def _candidate_start_dates(earliest: date, latest: date, trip_length_days: int, today: date) -> list[date]:
    """Up to MAX_CANDIDATE_WINDOWS evenly spaced start dates spanning
    whatever's left of the traveler's flexible range."""
    start_floor = max(earliest, today)
    last_possible_start = latest - timedelta(days=trip_length_days - 1)
    if start_floor > last_possible_start:
        return []
    span_days = (last_possible_start - start_floor).days
    if span_days <= 0:
        return [start_floor]
    offsets = sorted({0, span_days // 2, span_days})
    return [start_floor + timedelta(days=o) for o in offsets]


def evaluate_wishlist_item(item: dict) -> dict:
    """Returns {"status": "expired"} once the range no longer fits a trip of
    the requested length, otherwise {"status": "ok", "message", "booking_link",
    "start_date", "end_date"} for whichever candidate window looked best."""
    earliest = date.fromisoformat(item["earliest_date"])
    latest = date.fromisoformat(item["latest_date"])
    trip_length = item["trip_length_days"]
    today = date.today()

    candidates = _candidate_start_dates(earliest, latest, trip_length, today)
    if not candidates:
        return {"status": "expired"}

    scored_windows = []
    for start in candidates:
        end = start + timedelta(days=trip_length - 1)
        weather = get_weather_forecast(
            latitude=item["destination_lat"],
            longitude=item["destination_lon"],
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        days = weather["content"][0]["json"]["days"]
        avg_rain = sum(d["precipitation_chance_pct"] for d in days) / len(days)
        avg_temp_max = sum(d["temp_max_c"] for d in days) / len(days)
        scored_windows.append(
            {"start": start, "end": end, "avg_rain": avg_rain, "avg_temp_max": avg_temp_max}
        )

    best = min(scored_windows, key=lambda w: w["avg_rain"])
    compared_note = (
        f" (compared {len(scored_windows)} windows across your range)" if len(scored_windows) > 1 else ""
    )

    distance = estimate_distance(
        lat1=item["origin_lat"],
        lon1=item["origin_lon"],
        lat2=item["destination_lat"],
        lon2=item["destination_lon"],
    )
    distance_km = distance["content"][0]["json"]["distance_km"]

    flight = search_flights(
        origin_city=item["origin_city"],
        destination_city=item["destination_city"],
        departure_date=best["start"].isoformat(),
        return_date=best["end"].isoformat(),
        travelers=1,
        distance_km=distance_km,
    )["content"][0]["json"]

    wishlist_currency = item.get("currency", "USD")
    symbol = SUPPORTED_CURRENCIES.get(wishlist_currency, {}).get("symbol", wishlist_currency + " ")
    price_low = convert(flight["estimated_price_low_usd"], "USD", wishlist_currency)
    price_high = convert(flight["estimated_price_high_usd"], "USD", wishlist_currency)

    weather_quality = "good" if best["avg_rain"] < 40 else "mixed"
    message = (
        f"Best-looking window for {item['destination_city']} so far{compared_note}: "
        f"{best['start'].isoformat()} to {best['end'].isoformat()} — {weather_quality} weather "
        f"(avg high {best['avg_temp_max']:.0f}°C, ~{best['avg_rain']:.0f}% rain chance). "
        f"Estimated flights {symbol}{price_low:.0f}-{symbol}{price_high:.0f} "
        f"for one traveler — open the link for real current prices."
    )

    return {
        "status": "ok",
        "message": message,
        "booking_link": flight["booking_link"],
        "start_date": best["start"].isoformat(),
        "end_date": best["end"].isoformat(),
    }
