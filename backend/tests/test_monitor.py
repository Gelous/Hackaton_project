"""monitor.py's re-check logic: booking-milestone math is pure date
arithmetic (tested directly), and the weather check is tested with the real
get_weather_forecast tool call mocked out.
"""

from datetime import datetime, timedelta, timezone

from trip_agent import monitor


def make_plan(**overrides):
    plan = {
        "origin_city": "Austin",
        "destination_city": "Denver",
        "destination_lat": 1.0,
        "destination_lon": 2.0,
        "days": [{"date": "2026-09-01"}, {"date": "2026-09-03"}],
        "flight": {"booking_link": "flight-link"},
        "hotel": {"booking_link": "hotel-link", "suggested_neighborhood": "RiNo"},
    }
    plan.update(overrides)
    return plan


def test_booking_reminders_fire_on_milestone_days():
    today = datetime.now(timezone.utc).date()
    departure = today + timedelta(days=7)  # one of the real milestones
    plan = make_plan(days=[{"date": departure.isoformat()}])

    reminders = monitor._check_booking_reminders(plan)

    assert {r["type"] for r in reminders} == {"flight_price_reminder", "hotel_price_reminder"}
    flight_reminder = next(r for r in reminders if r["type"] == "flight_price_reminder")
    assert flight_reminder["booking_link"] == "flight-link"
    assert "7 days" in flight_reminder["message"]


def test_booking_reminders_silent_off_milestone_days():
    today = datetime.now(timezone.utc).date()
    departure = today + timedelta(days=8)  # not in (21, 14, 7, 3, 1)
    plan = make_plan(days=[{"date": departure.isoformat()}])

    assert monitor._check_booking_reminders(plan) == []


def test_weather_check_flags_high_rain_chance_days_only(monkeypatch):
    def fake_forecast(**kwargs):
        return {
            "content": [
                {
                    "json": {
                        "days": [
                            {"date": "2026-09-01", "precipitation_chance_pct": 80},
                            {"date": "2026-09-02", "precipitation_chance_pct": 10},
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(monitor, "get_weather_forecast", fake_forecast)

    update = monitor._check_weather(make_plan())

    assert update is not None
    assert update["type"] == "weather_change"
    assert "2026-09-01" in update["message"]
    assert "2026-09-02" not in update["message"]


def test_weather_check_silent_when_no_day_crosses_the_threshold(monkeypatch):
    def fake_forecast(**kwargs):
        return {"content": [{"json": {"days": [{"date": "2026-09-01", "precipitation_chance_pct": 5}]}}]}

    monkeypatch.setattr(monitor, "get_weather_forecast", fake_forecast)

    assert monitor._check_weather(make_plan()) is None


def test_weather_check_swallows_a_tool_failure_instead_of_crashing(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("weather API unreachable")

    monkeypatch.setattr(monitor, "get_weather_forecast", boom)

    assert monitor._check_weather(make_plan()) is None
