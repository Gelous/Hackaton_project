import math

from strands import tool


@tool
def estimate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Estimate straight-line distance and rough travel times between two coordinates.

    Returns great-circle distance in km/miles plus a rough drive-time estimate
    (assumes ~90 km/h average incl. stops) and flight-time estimate (assumes
    ~800 km/h cruise plus 45 min for taxi/takeoff/landing). Use this to compare
    how far candidate destinations or activities are from each other.

    Args:
        lat1: Latitude of point A.
        lon1: Longitude of point A.
        lat2: Latitude of point B.
        lon2: Longitude of point B.
    """
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    distance_km = 2 * r_km * math.asin(math.sqrt(a))

    drive_hours = distance_km / 90
    flight_hours = 0.75 + distance_km / 800

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "distance_km": round(distance_km, 1),
                    "distance_miles": round(distance_km * 0.621371, 1),
                    "estimated_drive_hours": round(drive_hours, 1),
                    "estimated_flight_hours": round(flight_hours, 1),
                }
            }
        ],
    }
