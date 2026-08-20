"""Worldwide city search for the frontend's autocomplete fields (starting city
and destination) — not an agent tool, just a UI helper endpoint. Backed by the
same free Open-Meteo geocoding API the agent itself uses, so results are real
cities worldwide rather than a small hand-picked list."""

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Open-Meteo only does forward geocoding (name -> coordinates); reverse
# (coordinates -> name) is a separate real, free, keyless API — verified by
# hand to correctly resolve real coordinates to a real city (Austin, TX
# round-tripped correctly). Proxied through the backend rather than called
# directly from the browser, same reason /api/cities proxies Open-Meteo
# instead of the frontend calling it directly: one place to swap providers,
# and no third-party endpoint hardcoded into client-side JS.
REVERSE_GEOCODE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"


def reverse_geocode(latitude: float, longitude: float) -> dict | None:
    """Real coordinates -> a real city/country, for "use my current
    location" (browser Geolocation API supplies the coordinates; this turns
    them into something a city-name field can actually show). None if the
    lookup fails or the coordinates don't resolve to a named city — never a
    guessed place name."""
    try:
        response = httpx.get(
            REVERSE_GEOCODE_URL,
            params={"latitude": latitude, "longitude": longitude, "localityLanguage": "en"},
            timeout=6,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    city = data.get("city") or data.get("locality")
    country = data.get("countryName")
    country_code = data.get("countryCode")
    if not city or not country:
        return None
    return {"city": city, "country": country, "country_code": country_code}


def search_cities(query: str, count: int = 8) -> list[dict]:
    try:
        response = httpx.get(GEOCODE_URL, params={"name": query, "count": count}, timeout=5)
        response.raise_for_status()
        results = response.json().get("results") or []
    except Exception:
        return []

    suggestions = []
    for r in results:
        name = r.get("name")
        country = r.get("country")
        if not name or not country:
            continue
        admin1 = r.get("admin1")
        region = admin1 if admin1 and admin1 != name else None
        label_parts = [name, region, country] if region else [name, country]
        suggestions.append(
            {
                "name": name,
                "admin1": region,
                "country": country,
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "label": ", ".join(label_parts),
            }
        )
    return suggestions
