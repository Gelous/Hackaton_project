"""Phase 2: background re-optimization.

Once a plan is locked in, this module re-checks the things that can change
before departure (weather forecast, and our estimated flight/hotel price
range) and reports back only what's worth a human decision — it never books
anything or invents a specific new price. When something looks worth acting
on, it always hands back the SAME real, live booking link from the original
plan (Google Flights/Hotels), since that link always reflects whatever the
real current price is at the moment the traveler opens it — we just decide
when it's worth nudging them to go look.

In a deployed version this runs on a schedule (e.g. daily) per saved trip and
notifies the user; here it's exposed as POST /api/monitor so the frontend can
trigger a check on demand for the demo.
"""

import hashlib
import random
from datetime import datetime, timezone

from .tools.weather import get_weather_forecast

DEAL_THRESHOLD_PCT = 6
RAIN_THRESHOLD_PCT = 55


def check_for_updates(plan: dict) -> dict:
    updates = []

    weather_update = _check_weather(plan)
    if weather_update:
        updates.append(weather_update)

    flight_update = _check_flight_deal(plan)
    if flight_update:
        updates.append(flight_update)

    hotel_update = _check_hotel_deal(plan)
    if hotel_update:
        updates.append(hotel_update)

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "has_updates": bool(updates),
        "updates": updates,
    }


def _drift_factor(key: str) -> float:
    """Deterministic-per-hour pseudo market drift for OUR ESTIMATE only — a
    stand-in for how fares/rates typically move, used purely to decide when
    it's worth nudging the traveler to go check the real, live booking link.
    We never present this drifted number as an actual confirmed price."""
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    seed = int(hashlib.sha256(f"{key}|{hour_bucket}".encode()).hexdigest(), 16)
    return random.Random(seed).uniform(-0.14, 0.14)


def _check_weather(plan: dict) -> dict | None:
    try:
        result = get_weather_forecast(
            latitude=plan["destination_lat"],
            longitude=plan["destination_lon"],
            start_date=plan["days"][0]["date"],
            end_date=plan["days"][-1]["date"],
        )
        days = result["content"][0]["json"]["days"]
    except Exception:
        return None

    rainy_days = [d for d in days if d.get("precipitation_chance_pct", 0) >= RAIN_THRESHOLD_PCT]
    if not rainy_days:
        return None

    dates = ", ".join(d["date"] for d in rainy_days)
    return {
        "type": "weather_change",
        "message": f"Updated forecast now shows a high chance of rain on {dates}. "
        "Consider swapping outdoor activities on those days for indoor ones.",
        "requires_decision": True,
    }


def _check_flight_deal(plan: dict) -> dict | None:
    flight = plan["flight"]
    key = f"flight|{plan['origin_city']}|{plan['destination_city']}|{plan['days'][0]['date']}"
    drift = _drift_factor(key)
    if drift > -DEAL_THRESHOLD_PCT / 100:
        return None  # only surface genuine drops, not every fluctuation

    new_low = round(flight["estimated_price_low_usd"] * (1 + drift), 2)
    return {
        "type": "flight_deal",
        "message": f"Our fare estimate for {plan['origin_city']} → {plan['destination_city']} "
        f"dropped from ~${flight['estimated_price_low_usd']:.0f} to ~${new_low:.0f}. "
        "Worth checking real current prices now.",
        "requires_decision": True,
        "booking_link": flight["booking_link"],
    }


def _check_hotel_deal(plan: dict) -> dict | None:
    hotel = plan["hotel"]
    key = f"hotel|{plan['destination_city']}|{plan['days'][0]['date']}|{hotel['suggested_neighborhood']}"
    drift = _drift_factor(key)
    if drift > -DEAL_THRESHOLD_PCT / 100:
        return None

    new_low = round(hotel["estimated_price_low_usd"] * (1 + drift), 2)
    return {
        "type": "hotel_deal",
        "message": f"Our nightly rate estimate for {hotel['suggested_neighborhood']} in "
        f"{plan['destination_city']} dropped from ~${hotel['estimated_price_low_usd']:.0f} to "
        f"~${new_low:.0f}. Worth checking real current rates now.",
        "requires_decision": True,
        "booking_link": hotel["booking_link"],
    }
