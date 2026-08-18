from datetime import date as date_cls, timedelta

import httpx
from strands import tool

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_YEARS_BACK = (1, 2, 3)
RAIN_THRESHOLD_MM = 1.0


@tool
def get_weather_forecast(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    """Get the daily weather forecast for a location between two dates.

    Uses the free Open-Meteo forecast API (no key required) within its ~16 day
    forecast horizon. Beyond that horizon, falls back to real historical
    weather (same calendar dates, averaged across the last three years) rather
    than a generic guess, so the estimate is grounded in actual past data for
    that specific location and time of year.

    Args:
        latitude: Latitude of the location.
        longitude: Longitude of the location.
        start_date: First day to forecast, format YYYY-MM-DD.
        end_date: Last day to forecast, format YYYY-MM-DD.
    """
    try:
        response = httpx.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                "timezone": "auto",
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout=10,
        )
        response.raise_for_status()
        daily = response.json().get("daily")
        if not daily or not daily.get("time"):
            raise ValueError("empty forecast window")
    except Exception:
        return _historical_estimate(latitude, longitude, start_date, end_date)

    days = []
    for i, date in enumerate(daily["time"]):
        days.append(
            {
                "date": date,
                "temp_max_c": daily["temperature_2m_max"][i],
                "temp_min_c": daily["temperature_2m_min"][i],
                "precipitation_chance_pct": daily["precipitation_probability_max"][i],
            }
        )

    return {"status": "success", "content": [{"json": {"source": "forecast", "days": days}}]}


def _shift_year(d: date_cls, years: int) -> date_cls:
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # Feb 29 in a non-leap target year
        return d.replace(month=2, day=28, year=d.year - years)


def _fetch_archive_year(latitude: float, longitude: float, start: date_cls, end: date_cls) -> dict | None:
    try:
        response = httpx.get(
            ARCHIVE_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            timeout=10,
        )
        response.raise_for_status()
        daily = response.json().get("daily")
        if not daily or not daily.get("time"):
            return None
        return daily
    except Exception:
        return None


def _historical_estimate(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    """Average actual weather from the same calendar dates over the last few
    years, since Open-Meteo's forecast only covers ~16 days ahead."""
    start = date_cls.fromisoformat(start_date)
    end = date_cls.fromisoformat(end_date)
    num_days = (end - start).days + 1

    per_day_samples: list[list[dict]] = [[] for _ in range(num_days)]
    for years_back in HISTORICAL_YEARS_BACK:
        shifted_start = _shift_year(start, years_back)
        shifted_end = _shift_year(end, years_back)
        daily = _fetch_archive_year(latitude, longitude, shifted_start, shifted_end)
        if not daily:
            continue
        for i in range(min(num_days, len(daily["time"]))):
            per_day_samples[i].append(
                {
                    "temp_max_c": daily["temperature_2m_max"][i],
                    "temp_min_c": daily["temperature_2m_min"][i],
                    "precipitation_mm": daily["precipitation_sum"][i],
                }
            )

    days = []
    for i in range(num_days):
        current_date = (start + timedelta(days=i)).isoformat()
        samples = [s for s in per_day_samples[i] if s["temp_max_c"] is not None]
        if samples:
            temp_max = round(sum(s["temp_max_c"] for s in samples) / len(samples), 1)
            temp_min = round(sum(s["temp_min_c"] for s in samples) / len(samples), 1)
            rainy_years = sum(1 for s in samples if (s["precipitation_mm"] or 0) > RAIN_THRESHOLD_MM)
            precipitation_chance = round(rainy_years / len(samples) * 100)
        else:
            # Archive API unreachable too — last-resort generic guess so
            # planning can still proceed.
            is_northern = latitude >= 0
            month = start.month
            northern_summer = 5 <= month <= 9
            warm_season = northern_summer if is_northern else not northern_summer
            temp_max, temp_min, precipitation_chance = (26, 15, 30) if warm_season else (10, 2, 30)

        days.append(
            {
                "date": current_date,
                "temp_max_c": temp_max,
                "temp_min_c": temp_min,
                "precipitation_chance_pct": precipitation_chance,
            }
        )

    years_used = len(HISTORICAL_YEARS_BACK) if any(per_day_samples[0]) else 0
    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "source": "historical_average" if years_used else "seasonal_estimate",
                    "note": f"outside the forecast horizon — averaged from actual weather on these "
                    f"calendar dates over the last {years_used} year(s)"
                    if years_used
                    else "outside forecast horizon and historical data unavailable, using a generic seasonal guess",
                    "days": days,
                }
            }
        ],
    }
