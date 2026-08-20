"""Deterministic post-processing, run after the agent finishes — never by
the LLM itself, same reasoning as server.py's currency conversion (an LLM
estimating a distance is just guessing at a plausible number). Adds a
straight-line distance/time/mode estimate from a real anchor point (a trip's
hotel area, or a day out's chosen location/city center) to each real-named
activity, restaurant, and event, using the same real coordinates already
collected into map_pins (PlaceRec/EventRec carry no lat/lon in the agent's
structured output, so each place is matched back to its map_pin by name).

There's no free turn-by-turn walking/transit routing API at the scale needed
here — the same gap already documented for flight/hotel pricing — so this is
straight-line distance at realistic walking/city-driving/bus speeds, not real
routing, always paired with that place's real Google Maps link for the
precise actual route.

Every place gets `commute_options`: 1-2 real alternatives (walk+drive when
close, drive+bus when farther) so the traveler can pick, not just a single
suggested mode — `travel_minutes`/`travel_mode` at the top level mirror
commute_options[0] for callers that just want "the" estimate.
"""

import math

# ~a 15-20 min walk. Beyond this, driving/transit reads as more realistic
# than framing it as a walk.
WALK_THRESHOLD_KM = 1.5
WALK_SPEED_KMH = 4.8  # average adult walking pace
CITY_DRIVE_SPEED_KMH = 25  # urban driving average incl. lights/traffic/parking — not highway
BUS_SPEED_KMH = 18  # average urban bus incl. stops — faster than walking, slower than door-to-door driving
BUS_WAIT_MINUTES = 8  # average wait for an urban bus headway, added on top of ride time

# Guards the substring fallback below against matching on a near-trivial
# fragment (e.g. a 2-3 character leftover after stripping the city name).
MIN_FUZZY_CORE_LEN = 4


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_km * math.asin(math.sqrt(a))


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _strip_city(text: str, city: str) -> str:
    """Map-pin labels often get the city name tacked on ("Union Station
    Denver"), which the activity name it's matched against usually doesn't
    repeat ("Explore LoDo & Union Station area") — stripped so the substring
    check below lines up on the actual place name, not the city suffix."""
    if not city:
        return text.strip()
    t, c = text.strip(), city.strip()
    if t.lower().endswith(c.lower()):
        t = t[: len(t) - len(c)].rstrip(" ,")
    elif t.lower().startswith(c.lower()):
        t = t[len(c):].lstrip(" ,")
    return t.strip()


def _commute_options(distance_km: float) -> list[dict]:
    """Real alternatives, not just one suggested mode — close by: walk or
    drive; farther: drive or bus. First entry is the "primary" one (mirrored
    onto travel_mode/travel_minutes for simple callers)."""
    if distance_km <= WALK_THRESHOLD_KM:
        return [
            {"mode": "walk", "minutes": max(1, round(distance_km / WALK_SPEED_KMH * 60))},
            {"mode": "drive", "minutes": max(1, round(distance_km / CITY_DRIVE_SPEED_KMH * 60))},
        ]
    bus_minutes = round(distance_km / BUS_SPEED_KMH * 60) + BUS_WAIT_MINUTES
    return [
        {"mode": "drive", "minutes": max(1, round(distance_km / CITY_DRIVE_SPEED_KMH * 60))},
        {"mode": "bus", "minutes": max(1, bus_minutes)},
    ]


def _estimate(anchor_lat: float, anchor_lon: float, place_lat: float, place_lon: float) -> dict:
    distance_km = round(_haversine_km(anchor_lat, anchor_lon, place_lat, place_lon), 1)
    options = _commute_options(distance_km)
    primary = options[0]
    return {
        "distance_km": distance_km,
        "travel_minutes": primary["minutes"],
        "travel_mode": primary["mode"],
        "commute_options": options,
    }


def _find_pin(name: str, exact_pins: dict, fuzzy_pins: list) -> dict | None:
    norm = _normalize(name)
    if norm in exact_pins:
        return exact_pins[norm]
    # Fuzzy fallback: the agent sometimes writes a more scene-setting
    # activity name than the plain place name it used for the matching map
    # pin (e.g. activity "Explore LoDo & Union Station area" vs. pin "Union
    # Station Denver") — a substring match on the pin's core name (city
    # prefix/suffix stripped) catches this without guessing at a wrong
    # place: it only ever matches a real pin's real name, never invents one.
    for core, pin in fuzzy_pins:
        if core in norm:
            return pin
    return None


def _apply(place: dict, exact_pins: dict, fuzzy_pins: list, anchor_lat: float, anchor_lon: float) -> None:
    pin = _find_pin(place.get("name", ""), exact_pins, fuzzy_pins)
    if not pin:
        # A generic/themed suggestion (e.g. "Vegetarian dinner near
        # downtown") has no real coordinates to measure from — an honest
        # unknown, never a guessed distance.
        place["distance_km"] = None
        place["travel_minutes"] = None
        place["travel_mode"] = None
        place["commute_options"] = []
        return
    place.update(_estimate(anchor_lat, anchor_lon, pin["lat"], pin["lon"]))


def _collect_pins(map_pins: list[dict], city: str, categories: tuple[str, ...]) -> tuple[dict, list]:
    exact_pins: dict[str, dict] = {}
    fuzzy_pins: list[tuple[str, dict]] = []
    for pin in map_pins:
        if pin.get("category") not in categories or not pin.get("label"):
            continue
        exact_pins.setdefault(_normalize(pin["label"]), pin)
        core = _normalize(_strip_city(pin["label"], city))
        if len(core) >= MIN_FUZZY_CORE_LEN:
            fuzzy_pins.append((core, pin))
    return exact_pins, fuzzy_pins


def add_travel_estimates(plan_dict: dict, hotel_lat: float | None = None, hotel_lon: float | None = None) -> dict:
    """Mutates plan_dict in place (and returns it for convenience) — adds
    distance_km / travel_minutes / travel_mode / commute_options to every
    activity and the restaurant in every day of a TripPlan.

    hotel_lat/hotel_lon let a caller anchor the estimate to a specific real
    hotel the traveler picked (see server.py's /api/plan/choose-hotel) —
    defaults to the destination's geocoded center when omitted, the same
    approximation used for the initial plan before any hotel is chosen."""
    if hotel_lat is None or hotel_lon is None:
        hotel_lat = plan_dict.get("destination_lat")
        hotel_lon = plan_dict.get("destination_lon")
    if hotel_lat is None or hotel_lon is None:
        return plan_dict

    exact_pins, fuzzy_pins = _collect_pins(
        plan_dict.get("map_pins", []), plan_dict.get("destination_city", ""), ("activity", "restaurant")
    )

    for day in plan_dict.get("days", []):
        for place in day.get("activities", []):
            _apply(place, exact_pins, fuzzy_pins, hotel_lat, hotel_lon)
        restaurant = day.get("restaurant")
        if restaurant:
            _apply(restaurant, exact_pins, fuzzy_pins, hotel_lat, hotel_lon)

    return plan_dict


def add_day_travel_estimates(plan_dict: dict, precise_lat: float | None = None, precise_lon: float | None = None) -> dict:
    """The DayOutPlan counterpart to add_travel_estimates above — covers
    activities, the restaurant, and events (a day out has no separate
    "choose a hotel" step where events would otherwise get missed).

    Anchored to the traveler's real device/account coordinates when given
    (more precise than any city center — see /api/reverse-geocode and
    agent.py's DAY_SYSTEM_PROMPT step 1), otherwise the plan's own
    city_lat/city_lon (the same anchor point the agent already searched
    everything around, so distances stay consistent with what was actually
    found nearby)."""
    anchor_lat = precise_lat if precise_lat is not None else plan_dict.get("city_lat")
    anchor_lon = precise_lon if precise_lon is not None else plan_dict.get("city_lon")
    if anchor_lat is None or anchor_lon is None:
        return plan_dict

    exact_pins, fuzzy_pins = _collect_pins(
        plan_dict.get("map_pins", []), plan_dict.get("city", ""), ("activity", "restaurant", "event")
    )

    for place in plan_dict.get("activities", []):
        _apply(place, exact_pins, fuzzy_pins, anchor_lat, anchor_lon)
    restaurant = plan_dict.get("restaurant")
    if restaurant:
        _apply(restaurant, exact_pins, fuzzy_pins, anchor_lat, anchor_lon)
    for event in plan_dict.get("events", []):
        _apply(event, exact_pins, fuzzy_pins, anchor_lat, anchor_lon)

    return plan_dict
