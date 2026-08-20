"""server.choose_hotel: re-anchoring the plan to a real hotel the traveler
picked from HotelEstimate.named_options. Pure deterministic recompute (see
travel_estimates.py) — no agent/Bedrock call, so this is tested the same
direct-function way as server._localize_plan.
"""

from trip_agent import server


def make_plan():
    return {
        "destination_lat": 39.7392,
        "destination_lon": -104.9903,
        "destination_city": "Denver",
        "map_pins": [
            {"label": "Denver", "category": "destination", "lat": 39.7392, "lon": -104.9903},
            {"label": "Old Hotel Pin", "category": "hotel", "lat": 39.7392, "lon": -104.9903},
            {"label": "Museum A", "category": "activity", "lat": 39.74, "lon": -104.99},
        ],
        "days": [{"activities": [{"name": "Museum A", "category": "museum"}], "restaurant": None}],
        "hotel": {
            "estimated_price_low": 90.0,
            "estimated_price_high": 220.0,
            "suggested_neighborhood": "LoDo",
            "booking_link": "https://www.booking.com/searchresults.html?ss=Denver&checkin=2026-09-15&checkout=2026-09-19&group_adults=2",
            "note": "Some existing note.",
            "named_options": [],
        },
    }


def test_recomputes_travel_distances_from_the_chosen_hotel():
    req = server.ChooseHotelRequest(plan=make_plan(), hotel_name="The Crawford Hotel", hotel_lat=39.7533, hotel_lon=-105.0001)

    result = server.choose_hotel(req)

    assert result["days"][0]["activities"][0]["distance_km"] is not None


def test_replaces_the_old_hotel_map_pin_with_the_chosen_one():
    req = server.ChooseHotelRequest(plan=make_plan(), hotel_name="The Crawford Hotel", hotel_lat=39.7533, hotel_lon=-105.0001)

    result = server.choose_hotel(req)

    hotel_pins = [p for p in result["map_pins"] if p["category"] == "hotel"]
    assert len(hotel_pins) == 1
    assert hotel_pins[0]["label"] == "The Crawford Hotel"
    assert hotel_pins[0]["lat"] == 39.7533
    # Untouched pins (destination, activity) survive the swap.
    assert any(p["label"] == "Museum A" for p in result["map_pins"])
    assert any(p["category"] == "destination" for p in result["map_pins"])


def test_booking_link_targets_the_specific_hotel_but_keeps_the_original_dates():
    req = server.ChooseHotelRequest(plan=make_plan(), hotel_name="The Crawford Hotel", hotel_lat=39.7533, hotel_lon=-105.0001)

    result = server.choose_hotel(req)
    link = result["hotel"]["booking_link"]

    assert "ss=The+Crawford+Hotel" in link or "ss=The%20Crawford%20Hotel" in link
    assert "checkin=2026-09-15" in link
    assert "checkout=2026-09-19" in link
    assert "group_adults=2" in link


def test_price_range_is_left_untouched_since_it_was_never_hotel_specific():
    req = server.ChooseHotelRequest(plan=make_plan(), hotel_name="The Crawford Hotel", hotel_lat=39.7533, hotel_lon=-105.0001)

    result = server.choose_hotel(req)

    assert result["hotel"]["estimated_price_low"] == 90.0
    assert result["hotel"]["estimated_price_high"] == 220.0


def test_note_names_the_chosen_hotel_and_still_disclaims_the_price():
    req = server.ChooseHotelRequest(plan=make_plan(), hotel_name="The Crawford Hotel", hotel_lat=39.7533, hotel_lon=-105.0001)

    result = server.choose_hotel(req)

    assert "The Crawford Hotel" in result["hotel"]["note"]
    assert "not this hotel's confirmed rate" in result["hotel"]["note"]


def test_does_not_mutate_the_caller_s_original_plan_dict():
    original = make_plan()
    req = server.ChooseHotelRequest(plan=original, hotel_name="The Crawford Hotel", hotel_lat=39.7533, hotel_lon=-105.0001)

    server.choose_hotel(req)

    assert original["hotel"]["suggested_neighborhood"] == "LoDo"
