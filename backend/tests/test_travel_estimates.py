"""travel_estimates.py — the "how far/how long from here" feature, for both
a trip's hotel area (add_travel_estimates) and a day out's chosen location or
city center (add_day_travel_estimates). Deterministic, run after the agent
finishes, never by the LLM itself (same principle as server.py's currency
conversion). Matches each activity/restaurant/event back to its real
coordinates via map_pins (PlaceRec/EventRec carry no lat/lon themselves),
since that's the only place in the agent's structured output real
coordinates live.
"""

from trip_agent.travel_estimates import (
    _commute_options,
    _estimate,
    _haversine_km,
    add_day_travel_estimates,
    add_travel_estimates,
)


def make_plan(days, map_pins, destination_lat=39.7392, destination_lon=-104.9903, destination_city="Denver"):
    return {
        "destination_lat": destination_lat,
        "destination_lon": destination_lon,
        "destination_city": destination_city,
        "map_pins": map_pins,
        "days": days,
    }


def test_haversine_matches_a_known_real_distance():
    # Denver to Boulder, CO — a well-known real-world distance (~40 km).
    km = _haversine_km(39.7392, -104.9903, 40.0150, -105.2705)
    assert 38 <= km <= 42


def test_estimate_classifies_short_distance_as_walk():
    result = _estimate(39.7392, -104.9903, 39.7395, -104.9905)  # ~40m away
    assert result["travel_mode"] == "walk"
    assert result["distance_km"] < 1.5
    assert result["travel_minutes"] >= 1


def test_estimate_classifies_long_distance_as_drive():
    result = _estimate(39.7392, -104.9903, 40.0150, -105.2705)  # ~40km away
    assert result["travel_mode"] == "drive"
    assert result["distance_km"] > 1.5


# ---- commute_options: real alternatives, not just one suggested mode ----


def test_commute_options_close_by_offers_walk_and_drive():
    options = _commute_options(0.8)
    modes = [o["mode"] for o in options]
    assert modes == ["walk", "drive"]


def test_commute_options_farther_away_offers_drive_and_bus():
    options = _commute_options(6.0)
    modes = [o["mode"] for o in options]
    assert modes == ["drive", "bus"]


def test_bus_option_accounts_for_wait_time_not_just_ride_time():
    options = _commute_options(6.0)
    bus = next(o for o in options if o["mode"] == "bus")
    drive = next(o for o in options if o["mode"] == "drive")
    # Bus is slower than driving door-to-door once wait time is folded in —
    # if this were just ride time at bus speed it could come out faster,
    # which wouldn't reflect a real commute.
    assert bus["minutes"] > drive["minutes"]


def test_estimate_mirrors_the_primary_commute_option():
    result = _estimate(39.7392, -104.9903, 39.80, -105.05)
    assert result["travel_mode"] == result["commute_options"][0]["mode"]
    assert result["travel_minutes"] == result["commute_options"][0]["minutes"]


def test_matches_activity_to_its_map_pin_by_name():
    days = [
        {
            "activities": [{"name": "Denver Art Museum", "category": "museum"}],
            "restaurant": {"name": "Root Down", "category": "restaurant"},
        }
    ]
    map_pins = [
        {"label": "Denver Art Museum", "category": "activity", "lat": 39.7371, "lon": -104.9899},
        {"label": "Root Down", "category": "restaurant", "lat": 39.7550, "lon": -105.0250},
    ]

    plan = add_travel_estimates(make_plan(days, map_pins))

    activity = plan["days"][0]["activities"][0]
    restaurant = plan["days"][0]["restaurant"]
    assert activity["distance_km"] is not None
    assert activity["travel_mode"] in ("walk", "drive")
    assert restaurant["distance_km"] is not None
    assert restaurant["travel_mode"] in ("walk", "drive")


def test_matching_is_case_and_whitespace_insensitive():
    """The agent writes the pin label and the place name in two separate
    structured-output fields — small casing/whitespace drift between them
    shouldn't silently lose the match."""
    days = [{"activities": [{"name": "  Denver Art Museum  ", "category": "museum"}], "restaurant": None}]
    map_pins = [{"label": "denver art museum", "category": "activity", "lat": 39.7371, "lon": -104.9899}]

    plan = add_travel_estimates(make_plan(days, map_pins))

    assert plan["days"][0]["activities"][0]["distance_km"] is not None


def test_fuzzy_match_when_activity_name_is_more_descriptive_than_pin_label():
    """Real observed case: the agent pinned "Union Station Denver" but wrote
    the activity itself as "Explore LoDo & Union Station area" — a scene-
    setting name, not the bare place name. An exact match would silently
    lose this real coordinate; the city-stripped substring match catches it."""
    days = [{"activities": [{"name": "Explore LoDo & Union Station area", "category": "landmark"}], "restaurant": None}]
    map_pins = [{"label": "Union Station Denver", "category": "activity", "lat": 39.7527, "lon": -105.0002}]

    plan = add_travel_estimates(make_plan(days, map_pins, destination_city="Denver"))

    assert plan["days"][0]["activities"][0]["distance_km"] is not None


def test_fuzzy_match_does_not_fire_on_a_trivially_short_leftover_core():
    """After stripping the city name, a pin label like "Denver" alone would
    leave an empty/near-empty core — that must never fuzzy-match everything."""
    days = [{"activities": [{"name": "Somewhere downtown Denver has stuff to see", "category": "landmark"}], "restaurant": None}]
    map_pins = [{"label": "Denver", "category": "activity", "lat": 39.7392, "lon": -104.9903}]

    plan = add_travel_estimates(make_plan(days, map_pins, destination_city="Denver"))

    assert plan["days"][0]["activities"][0]["distance_km"] is None


def test_no_matching_pin_leaves_all_fields_none():
    """A generic/themed suggestion (e.g. 'Vegetarian dinner near downtown')
    has no real coordinates — that must stay an honest unknown, never a
    guessed distance."""
    days = [{"activities": [{"name": "Vegetarian dinner near downtown", "category": "restaurant"}], "restaurant": None}]

    plan = add_travel_estimates(make_plan(days, map_pins=[]))

    place = plan["days"][0]["activities"][0]
    assert place["distance_km"] is None
    assert place["travel_minutes"] is None
    assert place["travel_mode"] is None
    assert place["commute_options"] == []


def test_ignores_non_activity_restaurant_pins_like_hotel_and_destination():
    """A same-named hotel/destination/event pin must never get matched as
    if it were the activity itself."""
    days = [{"activities": [{"name": "Denver", "category": "landmark"}], "restaurant": None}]
    map_pins = [
        {"label": "Denver", "category": "destination", "lat": 39.7392, "lon": -104.9903},
        {"label": "Denver", "category": "hotel", "lat": 39.75, "lon": -105.0},
    ]

    plan = add_travel_estimates(make_plan(days, map_pins))

    assert plan["days"][0]["activities"][0]["distance_km"] is None


def test_processes_every_day_and_every_activity_independently():
    days = [
        {
            "activities": [
                {"name": "Museum A", "category": "museum"},
                {"name": "Park B", "category": "park"},
            ],
            "restaurant": {"name": "Cafe C", "category": "restaurant"},
        },
        {
            "activities": [{"name": "Museum A", "category": "museum"}],  # same place, different day
            "restaurant": None,
        },
    ]
    map_pins = [
        {"label": "Museum A", "category": "activity", "lat": 39.74, "lon": -104.99},
        {"label": "Park B", "category": "activity", "lat": 39.70, "lon": -104.95},
        {"label": "Cafe C", "category": "restaurant", "lat": 39.75, "lon": -105.0},
    ]

    plan = add_travel_estimates(make_plan(days, map_pins))

    assert plan["days"][0]["activities"][0]["distance_km"] is not None
    assert plan["days"][0]["activities"][1]["distance_km"] is not None
    assert plan["days"][0]["restaurant"]["distance_km"] is not None
    assert plan["days"][1]["activities"][0]["distance_km"] is not None


def test_missing_destination_coordinates_does_not_crash():
    plan_dict = {"days": [{"activities": [{"name": "X"}], "restaurant": None}], "map_pins": []}
    result = add_travel_estimates(plan_dict)
    assert result["days"][0]["activities"][0].get("distance_km") is None


def test_explicit_hotel_coordinates_override_the_destination_center():
    """Powers /api/plan/choose-hotel — once the traveler picks a real hotel,
    distances should be measured from THAT hotel, not the destination's
    generic center anymore."""
    days = [{"activities": [{"name": "Museum A", "category": "museum"}], "restaurant": None}]
    map_pins = [{"label": "Museum A", "category": "activity", "lat": 39.74, "lon": -104.99}]

    plan = make_plan(days, map_pins, destination_lat=39.7392, destination_lon=-104.9903)
    from_center = add_travel_estimates(dict(plan))["days"][0]["activities"][0]["distance_km"]

    # A hotel much farther from Museum A than the destination center is.
    from_chosen_hotel = add_travel_estimates(dict(plan), hotel_lat=39.60, hotel_lon=-105.10)["days"][0]["activities"][0][
        "distance_km"
    ]

    assert from_chosen_hotel != from_center
    assert from_chosen_hotel > from_center


# ---- add_day_travel_estimates: the DayOutPlan counterpart ----


def make_day_plan(activities, restaurant, events, map_pins, city_lat=30.2672, city_lon=-97.7431, city="Austin"):
    return {
        "city": city,
        "city_lat": city_lat,
        "city_lon": city_lon,
        "activities": activities,
        "restaurant": restaurant,
        "events": events,
        "map_pins": map_pins,
    }


def test_day_plan_matches_activities_restaurant_and_events():
    plan = make_day_plan(
        activities=[{"name": "Zilker Park", "category": "park"}],
        restaurant=None,
        events=[{"name": "Live show", "category": "Music", "ticket_link": "https://example.com"}],
        map_pins=[
            {"label": "Zilker Park", "category": "activity", "lat": 30.2669, "lon": -97.7729},
            {"label": "Live show", "category": "event", "lat": 30.2650, "lon": -97.7500},
        ],
    )

    result = add_day_travel_estimates(plan)

    assert result["activities"][0]["distance_km"] is not None
    assert result["events"][0]["distance_km"] is not None


def test_day_plan_prefers_precise_coordinates_over_city_center():
    activities = [{"name": "Zilker Park", "category": "park"}]
    map_pins = [{"label": "Zilker Park", "category": "activity", "lat": 30.2669, "lon": -97.7729}]

    from_city_center = add_day_travel_estimates(make_day_plan(activities, None, [], map_pins))["activities"][0][
        "distance_km"
    ]
    # A precise point much farther from Zilker Park than the city center is.
    from_precise_point = add_day_travel_estimates(
        make_day_plan(activities, None, [], map_pins), precise_lat=30.45, precise_lon=-97.95
    )["activities"][0]["distance_km"]

    assert from_precise_point != from_city_center
    assert from_precise_point > from_city_center


def test_day_plan_missing_anchor_coordinates_does_not_crash():
    plan = {"city": "Austin", "activities": [{"name": "X"}], "restaurant": None, "events": [], "map_pins": []}
    result = add_day_travel_estimates(plan)
    assert result["activities"][0].get("distance_km") is None
