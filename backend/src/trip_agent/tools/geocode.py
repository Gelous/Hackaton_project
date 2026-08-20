import httpx
from strands import tool

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


@tool
def geocode_city(city_name: str) -> dict:
    """Look up the latitude, longitude, country, and admin region for a city name.

    Uses the free Open-Meteo geocoding API (no key required). Use this first for
    any city (origin or destination) before calling weather or distance tools,
    since those need coordinates.

    Args:
        city_name: The city to look up, e.g. "Austin" or "Portland, Oregon".
    """
    response = httpx.get(GEOCODE_URL, params={"name": city_name, "count": 1}, timeout=10)
    response.raise_for_status()
    results = response.json().get("results")
    if not results:
        return {"status": "error", "content": [{"text": f"No location found for '{city_name}'"}]}

    place = results[0]
    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "name": place.get("name"),
                    "country": place.get("country"),
                    "country_code": place.get("country_code"),
                    "admin1": place.get("admin1"),
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "timezone": place.get("timezone"),
                }
            }
        ],
    }
