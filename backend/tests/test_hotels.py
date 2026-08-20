"""tools/hotels.py — the date-awareness fix: the nightly estimate now scales
with the same real seasonal-demand pattern flights already use (previously
static regardless of check_in month), and the booking link switched from
Google Hotels (whose checkin/checkout URL params were verified by hand to be
silently ignored) to Booking.com's real, documented search URL, which was
verified to correctly apply both dates. Also: real named hotel/hostel
options from OpenStreetMap (verified live to return real results, e.g. "The
Crawford Hotel" near downtown Denver), sorted by distance to the destination
— the only honest ranking signal available, since OSM doesn't reliably carry
price or star-rating data (checked by hand: every result came back with
stars=None).
"""

from trip_agent.tools import hotels as hotels_module
from trip_agent.tools.hotels import _SEASONAL_MULTIPLIER, search_hotels


def fake_overpass_element(name, lat, lon, tourism="hotel"):
    return {"tags": {"name": name, "tourism": tourism}, "lat": lat, "lon": lon}


def test_peak_season_costs_more_than_off_peak_for_the_same_tier():
    peak = search_hotels("Denver", "2026-07-10", "2026-07-14", travelers=2)["content"][0]["json"]
    off_peak = search_hotels("Denver", "2026-02-10", "2026-02-14", travelers=2)["content"][0]["json"]

    assert peak["estimated_price_low_usd"] > off_peak["estimated_price_low_usd"]
    assert peak["estimated_price_high_usd"] > off_peak["estimated_price_high_usd"]


def test_price_scales_by_the_documented_seasonal_multiplier():
    result = search_hotels("Denver", "2026-01-10", "2026-01-14", travelers=1)["content"][0]["json"]
    multiplier = _SEASONAL_MULTIPLIER[1]

    assert result["estimated_price_low_usd"] == round(90 * multiplier, 2)
    assert result["estimated_price_high_usd"] == round(220 * multiplier, 2)


def test_accommodation_tier_still_selects_the_right_base_range():
    budget = search_hotels("Denver", "2026-04-10", "2026-04-14", travelers=1, accommodation_preference="budget hostel")["content"][0]["json"]
    luxury = search_hotels("Denver", "2026-04-10", "2026-04-14", travelers=1, accommodation_preference="luxury")["content"][0]["json"]

    assert budget["estimated_price_low_usd"] < luxury["estimated_price_low_usd"]


def test_booking_link_applies_the_exact_requested_dates_and_destination():
    result = search_hotels("Denver", "2026-09-15", "2026-09-19", travelers=2)["content"][0]["json"]
    link = result["booking_link"]

    assert link.startswith("https://www.booking.com/searchresults.html?")
    assert "ss=Denver" in link
    assert "checkin=2026-09-15" in link
    assert "checkout=2026-09-19" in link
    assert "group_adults=2" in link


def test_booking_link_clamps_travelers_to_at_least_one():
    result = search_hotels("Denver", "2026-09-15", "2026-09-19", travelers=0)["content"][0]["json"]
    assert "group_adults=1" in result["booking_link"]


def test_note_mentions_the_season_and_exact_month():
    result = search_hotels("Denver", "2026-07-10", "2026-07-14", travelers=1)["content"][0]["json"]
    assert "peak-season" in result["note"]
    assert "2026-07" in result["note"]


def test_no_named_options_when_coordinates_not_given():
    """Matches the pre-coordinate behavior exactly — callers that don't have
    lat/lon yet (or older test calls) still work, just without real hotels."""
    result = search_hotels("Denver", "2026-09-15", "2026-09-19", travelers=1)["content"][0]["json"]
    assert result["named_options"] == []


def test_named_options_returns_real_hotels_sorted_by_distance(monkeypatch):
    monkeypatch.setattr(
        hotels_module,
        "_try_overpass",
        lambda query: [
            fake_overpass_element("Far Hotel", 39.80, -105.05),  # farther
            fake_overpass_element("Near Hotel", 39.7395, -104.9905),  # closer
        ],
    )

    result = search_hotels(
        "Denver", "2026-09-15", "2026-09-19", travelers=1, latitude=39.7392, longitude=-104.9903
    )["content"][0]["json"]

    names = [o["name"] for o in result["named_options"]]
    assert names == ["Near Hotel", "Far Hotel"]
    assert result["named_options"][0]["lat"] == 39.7395
    assert "maps_link" in result["named_options"][0]


def test_named_options_capped_at_max_hotel_options(monkeypatch):
    monkeypatch.setattr(
        hotels_module,
        "_try_overpass",
        lambda query: [fake_overpass_element(f"Hotel {i}", 39.74 + i * 0.001, -104.99) for i in range(10)],
    )

    result = search_hotels(
        "Denver", "2026-09-15", "2026-09-19", travelers=1, latitude=39.7392, longitude=-104.9903
    )["content"][0]["json"]

    assert len(result["named_options"]) == hotels_module.MAX_HOTEL_OPTIONS


def test_budget_preference_only_searches_hostels(monkeypatch):
    captured_query = {}

    def fake_overpass(query):
        captured_query["value"] = query
        return []

    monkeypatch.setattr(hotels_module, "_try_overpass", fake_overpass)

    search_hotels(
        "Denver", "2026-09-15", "2026-09-19", travelers=1,
        accommodation_preference="budget hostel", latitude=39.7392, longitude=-104.9903,
    )

    assert 'tourism"="hostel"' in captured_query["value"]
    assert "hotel|hostel" not in captured_query["value"]


def test_named_options_skips_elements_missing_a_name_or_coordinates(monkeypatch):
    monkeypatch.setattr(
        hotels_module,
        "_try_overpass",
        lambda query: [
            {"tags": {"tourism": "hotel"}, "lat": 39.74, "lon": -104.99},  # no name
            {"tags": {"name": "No Coords Hotel"}, "lat": None, "lon": None},
            fake_overpass_element("Valid Hotel", 39.74, -104.99),
        ],
    )

    result = search_hotels(
        "Denver", "2026-09-15", "2026-09-19", travelers=1, latitude=39.7392, longitude=-104.9903
    )["content"][0]["json"]

    assert [o["name"] for o in result["named_options"]] == ["Valid Hotel"]


def test_named_options_empty_when_overpass_fails(monkeypatch):
    monkeypatch.setattr(hotels_module, "_try_overpass", lambda query: [])

    result = search_hotels(
        "Denver", "2026-09-15", "2026-09-19", travelers=1, latitude=39.7392, longitude=-104.9903
    )["content"][0]["json"]

    assert result["named_options"] == []


def test_note_never_claims_named_hotel_has_a_confirmed_price(monkeypatch):
    monkeypatch.setattr(hotels_module, "_try_overpass", lambda query: [fake_overpass_element("Some Hotel", 39.74, -104.99)])

    result = search_hotels(
        "Denver", "2026-09-15", "2026-09-19", travelers=1, latitude=39.7392, longitude=-104.9903
    )["content"][0]["json"]

    assert "not a confirmed rate" in result["note"]
