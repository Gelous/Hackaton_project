"""currency.py's pure math/caching logic, with the actual Frankfurter network
call mocked out — these should never depend on or be flaky because of a real
external API.
"""

from trip_agent import currency


class FakeResponse:
    def __init__(self, rate):
        self._rate = rate

    def raise_for_status(self):
        pass

    def json(self):
        return {"rates": {"XYZ": self._rate}}


def test_same_currency_short_circuits_without_a_network_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not hit the network for a same-currency conversion")

    monkeypatch.setattr(currency.httpx, "get", boom)
    assert currency.get_rate("USD", "USD") == 1.0
    assert currency.convert(42.5, "USD", "USD") == 42.5


def test_convert_applies_the_fetched_rate_and_rounds_to_cents(monkeypatch):
    currency._rate_cache.clear()
    monkeypatch.setattr(currency.httpx, "get", lambda *a, **k: FakeResponse(1.23456))
    assert currency.convert(10, "USD", "XYZ") == round(10 * 1.23456, 2)


def test_rate_is_cached_within_the_ttl(monkeypatch):
    currency._rate_cache.clear()
    calls = []
    monkeypatch.setattr(currency.httpx, "get", lambda *a, **k: (calls.append(1), FakeResponse(3.0))[1])

    currency.get_rate("USD", "XYZ")
    currency.get_rate("USD", "XYZ")
    assert len(calls) == 1


def test_cache_expires_after_the_ttl(monkeypatch):
    currency._rate_cache.clear()
    calls = []
    monkeypatch.setattr(currency.httpx, "get", lambda *a, **k: (calls.append(1), FakeResponse(3.0))[1])

    fake_time = [1000.0]
    monkeypatch.setattr(currency.time, "time", lambda: fake_time[0])

    currency.get_rate("USD", "XYZ")
    fake_time[0] += currency._CACHE_TTL_SECONDS + 1
    currency.get_rate("USD", "XYZ")
    assert len(calls) == 2


def test_supported_currencies_all_have_display_metadata():
    assert len(currency.SUPPORTED_CURRENCIES) == 12
    for code, meta in currency.SUPPORTED_CURRENCIES.items():
        assert meta["symbol"]
        assert meta["name"]
        assert len(code) == 3
