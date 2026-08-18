"""tools/flights.py's estimate_driving_cost — the drive-mode fix. Two things
matter: it doesn't scale per traveler like a flight does, and the range
reflects the real benchmarks documented in the module (fuel-only vs. the IRS
standard mileage rate), not arbitrary numbers.
"""

from trip_agent.tools.flights import (
    DRIVING_FUEL_ONLY_PER_KM,
    DRIVING_FULL_COST_PER_KM,
    estimate_driving_cost,
)


def test_cost_scales_with_round_trip_distance():
    result = estimate_driving_cost("Austin", "Denver", distance_km=1000)["content"][0]["json"]

    assert result["estimated_price_low_usd"] == 1000 * 2 * DRIVING_FUEL_ONLY_PER_KM
    assert result["estimated_price_high_usd"] == 1000 * 2 * DRIVING_FULL_COST_PER_KM


def test_low_is_cheaper_than_high():
    result = estimate_driving_cost("Austin", "Denver", distance_km=500)["content"][0]["json"]
    assert result["estimated_price_low_usd"] < result["estimated_price_high_usd"]


def test_booking_link_is_real_driving_directions_not_a_flight_search():
    result = estimate_driving_cost("Austin, Texas", "Denver, Colorado", distance_km=1250)["content"][0]["json"]

    link = result["booking_link"]
    assert link.startswith("https://www.google.com/maps/dir/")
    assert "travelmode=driving" in link
    assert "Austin" in link
    assert "Denver" in link


def test_note_clarifies_this_is_not_per_traveler():
    result = estimate_driving_cost("Austin", "Denver", distance_km=500)["content"][0]["json"]
    assert "not per traveler" in result["note"]
