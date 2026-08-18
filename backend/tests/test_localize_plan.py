"""server._localize_plan: the deterministic post-agent currency conversion
step (agent.py's system prompt forbids the agent from ever doing this math
itself — see that module's docstring)."""

from trip_agent import server


def make_plan_dict():
    return {
        "flight": {"estimated_price_low": 100.0, "estimated_price_high": 200.0, "booking_link": "x", "note": "x"},
        "hotel": {"estimated_price_low": 50.0, "estimated_price_high": 80.0, "suggested_neighborhood": "x", "booking_link": "x", "note": "x"},
        "total_estimated_cost_low": 150.0,
        "total_estimated_cost_high": 280.0,
        "currency": "USD",
        "budget": 999.0,
    }


def test_usd_is_a_no_op_and_never_calls_convert(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not convert when the target currency is already USD")

    monkeypatch.setattr(server, "convert", boom)
    plan = make_plan_dict()

    result = server._localize_plan(plan, original_budget=1234.0, currency="USD")

    assert result["flight"]["estimated_price_low"] == 100.0
    assert result["currency"] == "USD"
    assert result["budget"] == 1234.0


def test_every_monetary_field_gets_converted(monkeypatch):
    monkeypatch.setattr(server, "convert", lambda amount, from_cur, to_cur: amount * 2)
    plan = make_plan_dict()

    result = server._localize_plan(plan, original_budget=500.0, currency="EUR")

    assert result["flight"]["estimated_price_low"] == 200.0
    assert result["flight"]["estimated_price_high"] == 400.0
    assert result["hotel"]["estimated_price_low"] == 100.0
    assert result["hotel"]["estimated_price_high"] == 160.0
    assert result["total_estimated_cost_low"] == 300.0
    assert result["total_estimated_cost_high"] == 560.0
    assert result["currency"] == "EUR"


def test_budget_is_the_original_input_never_reconverted(monkeypatch):
    # Regression guard for the exact rounding-drift bug this function exists
    # to avoid: budget must equal what the traveler actually typed, not the
    # echoed-then-reconverted USD figure (which could drift by a cent or two
    # after two lossy conversions).
    monkeypatch.setattr(server, "convert", lambda amount, from_cur, to_cur: round(amount * 0.857, 2))
    plan = make_plan_dict()

    result = server._localize_plan(plan, original_budget=1738.95, currency="EUR")

    assert result["budget"] == 1738.95
