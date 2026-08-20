"""agent._build_day_prompt — when the traveler used real device/account
location (see /api/reverse-geocode), the prompt tells the agent to anchor
every nearby search to that exact point instead of a city center, and skip
geocode_city entirely (see agent.py's DAY_SYSTEM_PROMPT step 1)."""

from trip_agent.agent import _build_day_prompt


def _base_prefs(**overrides):
    return {
        "city": "Austin",
        "date": "2026-09-01",
        "mood_or_interest": "chill evening",
        "event_type": "",
        "max_events": 5,
        "dietary_needs": "none",
        **overrides,
    }


def test_city_only_prompt_has_no_coordinates():
    prompt = _build_day_prompt(_base_prefs())
    assert "City: Austin" in prompt
    assert "Exact anchor point" not in prompt


def test_prompt_includes_exact_coordinates_when_given():
    prompt = _build_day_prompt(_base_prefs(lat=30.2672, lon=-97.7431, country="United States", country_code="US"))
    assert "latitude=30.2672" in prompt
    assert "longitude=-97.7431" in prompt
    assert "country=United States" in prompt
    assert "country_code=US" in prompt
    assert "do not call geocode_city" in prompt


def test_missing_country_falls_back_to_an_honest_placeholder_not_a_guess():
    prompt = _build_day_prompt(_base_prefs(lat=1.0, lon=2.0))
    assert "country=unknown, infer from coordinates if needed" in prompt
