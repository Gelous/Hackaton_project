"""Worldwide city search for the frontend's autocomplete fields (starting city
and destination) — not an agent tool, just a UI helper endpoint. Backed by the
same free Open-Meteo geocoding API the agent itself uses, so results are real
cities worldwide rather than a small hand-picked list."""

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


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
