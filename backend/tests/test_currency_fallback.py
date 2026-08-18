"""currency.py's ECB fallback path — used when Frankfurter (the primary
source) is unreachable. Mirrors places.py's Overpass mirror-chain pattern:
degrade to a second real source before giving up."""

import httpx
import pytest

from trip_agent import currency

ECB_XML_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-08-17">
      <Cube currency="USD" rate="1.16"/>
      <Cube currency="GBP" rate="0.855"/>
      <Cube currency="JPY" rate="170.5"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


class FakeXmlResponse:
    def raise_for_status(self):
        pass

    @property
    def text(self):
        return ECB_XML_FIXTURE


class FakeFrankfurterResponse:
    def __init__(self, rate):
        self._rate = rate

    def raise_for_status(self):
        pass

    def json(self):
        return {"rates": {"XYZ": self._rate}}


def _reset_caches():
    currency._rate_cache.clear()
    currency._ecb_rates_cache = None


def test_ecb_xml_is_parsed_into_eur_pivoted_rates(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(currency.httpx, "get", lambda *a, **k: FakeXmlResponse())

    rates = currency._fetch_ecb_eur_rates()

    assert rates["EUR"] == 1.0
    assert rates["USD"] == 1.16
    assert rates["GBP"] == 0.855


def test_get_rate_from_ecb_pivots_through_eur(monkeypatch):
    _reset_caches()
    monkeypatch.setattr(currency.httpx, "get", lambda *a, **k: FakeXmlResponse())

    # USD->GBP should be (EUR->GBP) / (EUR->USD)
    assert currency._get_rate_from_ecb("USD", "GBP") == pytest.approx(0.855 / 1.16)


def test_get_rate_falls_back_to_ecb_when_frankfurter_fails(monkeypatch):
    _reset_caches()

    def fake_get(url, *a, **k):
        if url == currency.FRANKFURTER_URL:
            raise httpx.ConnectError("simulated Frankfurter outage")
        return FakeXmlResponse()

    monkeypatch.setattr(currency.httpx, "get", fake_get)

    rate = currency.get_rate("EUR", "USD")

    assert rate == 1.16


def test_get_rate_raises_currency_unavailable_when_both_sources_fail(monkeypatch):
    _reset_caches()

    def boom(*a, **k):
        raise httpx.ConnectError("simulated total outage")

    monkeypatch.setattr(currency.httpx, "get", boom)

    with pytest.raises(currency.CurrencyUnavailableError):
        currency.get_rate("USD", "EUR")


def test_frankfurter_success_never_touches_ecb(monkeypatch):
    _reset_caches()

    def ecb_boom(*a, **k):
        raise AssertionError("should not fall back to ECB when Frankfurter succeeds")

    def fake_get(url, *a, **k):
        if url == currency.FRANKFURTER_URL:
            return FakeFrankfurterResponse(2.0)
        return ecb_boom()

    monkeypatch.setattr(currency.httpx, "get", fake_get)

    assert currency.get_rate("USD", "XYZ") == 2.0
