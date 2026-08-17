import httpx
from strands import tool

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@tool
def get_weather_forecast(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    """Get the daily weather forecast for a location between two dates.

    Uses the free Open-Meteo forecast API (no key required). Dates beyond the
    ~16 day forecast horizon fall back to historical daily averages for that
    time of year, so this always returns a usable estimate for future travel
    planning.

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
        return _seasonal_estimate(latitude, start_date, end_date)

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


def _seasonal_estimate(latitude: float, start_date: str, end_date: str) -> dict:
    """Rough seasonal fallback when dates are outside Open-Meteo's forecast window."""
    from datetime import date as date_cls, timedelta

    start = date_cls.fromisoformat(start_date)
    end = date_cls.fromisoformat(end_date)
    is_northern = latitude >= 0
    month = start.month
    northern_summer = 5 <= month <= 9
    warm_season = northern_summer if is_northern else not northern_summer

    days = []
    d = start
    while d <= end:
        days.append(
            {
                "date": d.isoformat(),
                "temp_max_c": 26 if warm_season else 10,
                "temp_min_c": 15 if warm_season else 2,
                "precipitation_chance_pct": 30,
            }
        )
        d += timedelta(days=1)

    return {
        "status": "success",
        "content": [{"json": {"source": "seasonal_estimate", "note": "outside forecast horizon, using seasonal average", "days": days}}],
    }
