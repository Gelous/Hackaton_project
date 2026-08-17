import urllib.parse

import httpx
from strands import tool

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _maps_search_link(query: str) -> str:
    """Official Google Maps search deep link (developers.google.com/maps/documentation/urls) —
    not scraping, this is Google's documented URL scheme for linking out to a live search."""
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def _try_overpass(query: str) -> list[dict]:
    """Best-effort real POI lookup. The public Overpass instance is unreliable
    (rate limits / occasional outright rejections), so this is treated as a
    bonus enrichment, never the only source of truth — every result the agent
    can act on also gets a real Google Maps link regardless of whether this
    succeeds."""
    try:
        response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=8)
        if response.status_code != 200:
            return []
        return response.json().get("elements", [])
    except Exception:
        return []


@tool
def search_restaurants(latitude: float, longitude: float, city_name: str, dietary_needs: str = "none") -> dict:
    """Find restaurants near a destination, with a real, live, clickable link.

    Attempts a real OpenStreetMap lookup for specific named restaurants near
    the coordinates (best-effort, may return nothing if that data source is
    unavailable). Always also returns a real Google Maps search link scoped to
    the destination and dietary needs, which shows real current restaurants,
    ratings, and reviews the traveler can pick from and get directions to.

    Args:
        latitude: Latitude of the destination.
        longitude: Longitude of the destination.
        city_name: City name, used to build the maps search link.
        dietary_needs: Free-text dietary requirements, e.g. "vegetarian",
            "vegan", "gluten-free", "halal", or "none".
    """
    diet = dietary_needs.lower().strip()
    query = f"""
    [out:json][timeout:8];
    node["amenity"="restaurant"](around:3000,{latitude},{longitude});
    out body 20;
    """
    elements = _try_overpass(query)

    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if diet and diet != "none":
            diet_tag = tags.get(f"diet:{diet.replace(' ', '_')}")
            if diet_tag not in ("yes", "only") and diet not in (tags.get("cuisine", "") or "").lower():
                continue
        results.append(
            {
                "name": name,
                "cuisine": tags.get("cuisine", "unspecified"),
                "lat": el.get("lat"),
                "lon": el.get("lon"),
                "maps_link": _maps_search_link(f"{name}, {city_name}"),
            }
        )
        if len(results) >= 8:
            break

    diet_prefix = f"{dietary_needs} " if diet and diet != "none" else ""
    search_link = _maps_search_link(f"{diet_prefix}restaurants in {city_name}")

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "named_options": results,
                    "search_link": search_link,
                    "note": "named_options are specific real places when available. If empty, use "
                    "search_link and describe the meal by cuisine/theme rather than naming a place "
                    "you're not sure exists.",
                }
            }
        ],
    }


@tool
def search_activities(latitude: float, longitude: float, city_name: str, interests: str = "general sightseeing") -> dict:
    """Find attractions/activities near a destination, with a real, live, clickable link.

    Attempts a real OpenStreetMap lookup for specific named attractions near
    the coordinates (best-effort, may return nothing if that data source is
    unavailable). Always also returns a real Google Maps search link scoped to
    the destination and stated interests, which shows real current
    attractions and ratings the traveler can pick from.

    Args:
        latitude: Latitude of the destination.
        longitude: Longitude of the destination.
        city_name: City name, used to build the maps search link.
        interests: Free-text traveler interests, e.g. "hiking, art museums, local food".
    """
    query = f"""
    [out:json][timeout:8];
    (
      node["tourism"~"attraction|museum|viewpoint|gallery"](around:5000,{latitude},{longitude});
      way["leisure"="park"](around:5000,{latitude},{longitude});
    );
    out center 20;
    """
    elements = _try_overpass(query)

    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        results.append(
            {
                "name": name,
                "category": tags.get("tourism") or tags.get("leisure", "attraction"),
                "lat": lat,
                "lon": lon,
                "maps_link": _maps_search_link(f"{name}, {city_name}"),
            }
        )
        if len(results) >= 8:
            break

    search_link = _maps_search_link(f"{interests} things to do in {city_name}")

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "named_options": results,
                    "search_link": search_link,
                    "note": "named_options are specific real places when available. If empty, use "
                    "search_link and describe the activity by theme/interest rather than naming a "
                    "place you're not sure exists.",
                }
            }
        ],
    }
