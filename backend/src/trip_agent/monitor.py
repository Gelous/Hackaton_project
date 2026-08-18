"""Phase 2: background re-optimization.

Once a plan is locked in, this module re-checks the things that can change
before departure and reports back only what's worth a human decision — it
never books anything, and it never invents a number it can't back up.

Two checks, both grounded in something real:
- Weather: re-queries the live forecast; surfaces a nudge only if a day now
  shows a high chance of rain.
- Booking reminders: fires only on well-known travel-advice milestones
  (21/14/7/3/1 days before departure — real dates, not simulated), pointing
  back at the same real Google Flights/Hotels booking link so the traveler
  can see whatever the actual current price is when they open it. This
  deliberately does NOT claim a specific price changed — we have no live
  pricing feed, so asserting a number would be a fabrication.

In a deployed version this runs on a schedule (e.g. daily) per saved trip and
notifies the user; here it's exposed as POST /api/monitor so the frontend can
trigger a check on demand for the demo.
"""

from datetime import date, datetime, timezone

from .tools.weather import get_weather_forecast

RAIN_THRESHOLD_PCT = 55
BOOKING_REMINDER_MILESTONES_DAYS = (21, 14, 7, 3, 1)


def check_for_updates(plan: dict) -> dict:
    updates = []

    weather_update = _check_weather(plan)
    if weather_update:
        updates.append(weather_update)

    updates.extend(_check_booking_reminders(plan))

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "has_updates": bool(updates),
        "updates": updates,
    }


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


def _check_booking_reminders(plan: dict) -> list[dict]:
    departure = date.fromisoformat(plan["days"][0]["date"])
    days_until = (departure - datetime.now(timezone.utc).date()).days
    if days_until not in BOOKING_REMINDER_MILESTONES_DAYS:
        return []

    when = f"{days_until} day{'s' if days_until != 1 else ''}"
    return [
        {
            "type": "flight_price_reminder",
            "message": f"{when} until departure — worth checking current flight prices for "
            f"{plan['origin_city']} → {plan['destination_city']} in case fares have shifted.",
            "requires_decision": True,
            "booking_link": plan["flight"]["booking_link"],
        },
        {
            "type": "hotel_price_reminder",
            "message": f"{when} until departure — worth checking current hotel rates near "
            f"{plan['hotel']['suggested_neighborhood']} in {plan['destination_city']}.",
            "requires_decision": True,
            "booking_link": plan["hotel"]["booking_link"],
        },
    ]
