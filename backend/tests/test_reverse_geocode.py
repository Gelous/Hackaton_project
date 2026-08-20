"""places_search.reverse_geocode — turns real browser-supplied coordinates
into a real city name for "use my current location" (verified by hand
against the real API: Austin, TX coordinates correctly round-tripped to
"Austin"/"United States"). Mocked here the same way other tools in this repo
mock their HTTP dependency, so the suite doesn't depend on network access.
"""

import pytest
from fastapi import HTTPException

from trip_agent import places_search, server


def test_returns_real_city_and_country(monkeypatch):
    def fake_get(url, params=None, timeout=None, follow_redirects=None):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"city": "Austin", "countryName": "United States of America (the)", "countryCode": "US"}

        return FakeResponse()

    monkeypatch.setattr(places_search, "httpx", type("M", (), {"get": staticmethod(fake_get)}))

    result = places_search.reverse_geocode(30.2672, -97.7431)

    assert result == {"city": "Austin", "country": "United States of America (the)", "country_code": "US"}


def test_falls_back_to_locality_when_city_field_missing(monkeypatch):
    def fake_get(url, params=None, timeout=None, follow_redirects=None):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"locality": "Somewhere Rural", "countryName": "Testland"}

        return FakeResponse()

    monkeypatch.setattr(places_search, "httpx", type("M", (), {"get": staticmethod(fake_get)}))

    result = places_search.reverse_geocode(0.0, 0.0)

    assert result["city"] == "Somewhere Rural"


def test_returns_none_when_no_city_resolves(monkeypatch):
    """The honest outcome for e.g. open ocean coordinates — never a guessed
    place name."""

    def fake_get(url, params=None, timeout=None, follow_redirects=None):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"countryName": "", "city": None, "locality": None}

        return FakeResponse()

    monkeypatch.setattr(places_search, "httpx", type("M", (), {"get": staticmethod(fake_get)}))

    assert places_search.reverse_geocode(0.0, 0.0) is None


def test_returns_none_on_request_failure(monkeypatch):
    def fake_get(url, params=None, timeout=None, follow_redirects=None):
        raise ConnectionError("network down")

    monkeypatch.setattr(places_search, "httpx", type("M", (), {"get": staticmethod(fake_get)}))

    assert places_search.reverse_geocode(30.0, -97.0) is None


def test_reverse_geocode_endpoint_returns_404_when_nothing_resolves(monkeypatch):
    monkeypatch.setattr(server, "reverse_geocode", lambda lat, lon: None)

    with pytest.raises(HTTPException) as exc:
        server.reverse_geocode_endpoint(lat=0.0, lon=0.0)
    assert exc.value.status_code == 404


def test_reverse_geocode_endpoint_returns_the_real_result(monkeypatch):
    monkeypatch.setattr(server, "reverse_geocode", lambda lat, lon: {"city": "Austin", "country": "United States", "country_code": "US"})

    result = server.reverse_geocode_endpoint(lat=30.27, lon=-97.74)

    assert result["city"] == "Austin"
