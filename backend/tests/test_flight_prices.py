"""tools/flights.py's real-price integration (Travelpayouts Data API) — a
free, self-serve alternative to the flight-pricing APIs that require a paid
or approved account (Duffel, Amadeus Enterprise). Two independent pieces:

1. Nearest-coordinate IATA lookup, since Travelpayouts is keyed by city/
   airport code, not city name, and this app only has geocoded coordinates
   (from geocode_city) to work with.
2. The real-price fetch + fallback in search_flights — a real cached fare
   when one is found, the existing distance/season estimate otherwise, never
   a fabricated price either way.
"""

from trip_agent.tools import flights as flights_module


def fake_city_codes():
    return [
        {"name": "New York", "country": "US", "code": "NYC", "lat": 40.7128, "lon": -74.0060},
        {"name": "London", "country": "GB", "code": "LON", "lat": 51.5074, "lon": -0.1278},
    ]


def fake_airline_names():
    return {"BA": "British Airways", "AA": "American Airlines"}


def fake_real_price(**overrides):
    base = {
        "price_usd": 500,
        "real_departure_date": "2026-09-15",
        "real_return_date": "2026-09-22",
        "real_departure_at": "2026-09-15T14:00:00-04:00",  # 2pm = afternoon
        "airline_name": None,
        "flight_number": None,
    }
    base.update(overrides)
    return base


def test_nearest_iata_code_matches_close_coordinate(monkeypatch):
    monkeypatch.setattr(flights_module, "_load_city_codes", fake_city_codes)
    # A few km from central New York, well within the match threshold.
    code = flights_module._nearest_iata_code(40.75, -73.98)
    assert code == "NYC"


def test_nearest_iata_code_returns_none_when_nothing_close_enough(monkeypatch):
    monkeypatch.setattr(flights_module, "_load_city_codes", fake_city_codes)
    # The middle of the Pacific Ocean — nowhere near either fixture city.
    code = flights_module._nearest_iata_code(0.0, -160.0)
    assert code is None


def test_fetch_real_price_returns_none_without_a_token(monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_API_TOKEN", raising=False)
    result = flights_module._fetch_real_price("NYC", "LON", "2026-09-15", "2026-09-22")
    assert result is None


def test_fetch_real_price_parses_cheapest_option(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "success": True,
                    "data": {
                        "LON": {
                            "0": {
                                "price": 540,
                                "airline": "BA",
                                "flight_number": 178,
                                "departure_at": "2026-09-15T21:20:00Z",
                                "return_at": "2026-09-22T12:40:00Z",
                            },
                            "1": {
                                "price": 480,
                                "airline": "AA",
                                "flight_number": 100,
                                "departure_at": "2026-09-16T08:00:00Z",
                                "return_at": "2026-09-23T09:00:00Z",
                            },
                        }
                    },
                }

        return FakeResponse()

    monkeypatch.setattr(flights_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setattr(flights_module, "_load_airline_names", fake_airline_names)
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", "fake-token")

    result = flights_module._fetch_real_price("NYC", "LON", "2026-09-15", "2026-09-22")

    assert result["price_usd"] == 480
    assert result["real_departure_date"] == "2026-09-16"
    assert result["real_return_date"] == "2026-09-23"
    assert result["airline_name"] == "American Airlines"
    assert result["flight_number"] == 100
    assert captured["params"]["currency"] == "usd"
    assert captured["params"]["token"] == "fake-token"


def test_airline_name_resolves_known_code(monkeypatch):
    monkeypatch.setattr(flights_module, "_load_airline_names", fake_airline_names)
    assert flights_module._airline_name("BA") == "British Airways"


def test_airline_name_returns_none_for_unknown_code(monkeypatch):
    monkeypatch.setattr(flights_module, "_load_airline_names", fake_airline_names)
    assert flights_module._airline_name("ZZ") is None


def test_fetch_real_price_returns_none_when_route_has_no_data(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"success": True, "data": {}}

        return FakeResponse()

    monkeypatch.setattr(flights_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", "fake-token")

    assert flights_module._fetch_real_price("NYC", "LON", "2026-09-15", "2026-09-22") is None


def test_fetch_real_price_returns_none_on_request_failure(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise ConnectionError("network down")

    monkeypatch.setattr(flights_module, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", "fake-token")

    assert flights_module._fetch_real_price("NYC", "LON", "2026-09-15", "2026-09-22") is None


def test_search_flights_uses_real_price_multiplied_by_travelers(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(
        flights_module,
        "_fetch_real_price",
        lambda o, d, dep, ret: fake_real_price(real_departure_date=dep, real_return_date=ret),
    )

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22", travelers=2, distance_km=5570
    )["content"][0]["json"]

    assert result["real_price_observed"] is True
    assert result["estimated_price_low_usd"] == 1000
    assert result["estimated_price_high_usd"] == 1000
    assert "real recent price" in result["note"].lower()
    assert "exact dates" in result["note"]


def test_search_flights_notes_mismatched_dates_honestly(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(
        flights_module,
        "_fetch_real_price",
        lambda o, d, dep, ret: fake_real_price(real_departure_date="2026-09-16", real_return_date="2026-09-23"),
    )

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22", travelers=1, distance_km=5570
    )["content"][0]["json"]

    assert result["real_price_observed"] is True
    assert "not necessarily your exact dates" in result["note"]
    assert "2026-09-16" in result["note"]


def test_search_flights_names_real_airline_and_flight_number_when_available(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(
        flights_module,
        "_fetch_real_price",
        lambda o, d, dep, ret: fake_real_price(
            real_departure_date=dep, real_return_date=ret, airline_name="British Airways", flight_number=178
        ),
    )

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22", travelers=1, distance_km=5570
    )["content"][0]["json"]

    assert "on British Airways flight 178" in result["note"]


def test_search_flights_omits_carrier_when_airline_name_unresolved(monkeypatch):
    """A code Travelpayouts returned but that isn't in our bundled airline
    dataset must never be shown as a raw two-letter code, and must never be
    silently guessed at — just omitted from the note."""
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(
        flights_module,
        "_fetch_real_price",
        lambda o, d, dep, ret: fake_real_price(real_departure_date=dep, real_return_date=ret, flight_number=178),
    )

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22", travelers=1, distance_km=5570
    )["content"][0]["json"]

    assert "flight 178" not in result["note"]
    assert "Travelpayouts, for these exact dates" in result["note"]


def test_time_of_day_classifies_hours_correctly():
    assert flights_module._time_of_day(6) == "morning"
    assert flights_module._time_of_day(11) == "morning"
    assert flights_module._time_of_day(12) == "afternoon"
    assert flights_module._time_of_day(16) == "afternoon"
    assert flights_module._time_of_day(17) == "evening"
    assert flights_module._time_of_day(20) == "evening"
    assert flights_module._time_of_day(21) == "red-eye"
    assert flights_module._time_of_day(23) == "red-eye"
    assert flights_module._time_of_day(0) == "red-eye"
    assert flights_module._time_of_day(4) == "red-eye"


def test_matches_preferred_time_true_when_bands_align():
    assert flights_module._matches_preferred_time("2026-09-15T08:00:00-04:00", "morning") is True


def test_matches_preferred_time_false_when_bands_differ():
    assert flights_module._matches_preferred_time("2026-09-15T20:00:00-04:00", "morning") is False


def test_matches_preferred_time_none_when_no_preference_given():
    assert flights_module._matches_preferred_time("2026-09-15T08:00:00-04:00", "") is None


def test_matches_preferred_time_none_for_unparseable_timestamp():
    assert flights_module._matches_preferred_time("", "morning") is None


def test_search_flights_notes_real_fare_matches_preferred_time(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(
        flights_module,
        "_fetch_real_price",
        lambda o, d, dep, ret: fake_real_price(real_departure_at="2026-09-15T07:30:00-04:00"),
    )

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22",
        travelers=1, distance_km=5570, preferred_departure_time="morning",
    )["content"][0]["json"]

    assert "matches your preferred morning departure time" in result["note"]


def test_search_flights_notes_real_fare_does_not_match_preferred_time(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(
        flights_module,
        "_fetch_real_price",
        lambda o, d, dep, ret: fake_real_price(real_departure_at="2026-09-15T21:30:00-04:00"),
    )

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22",
        travelers=1, distance_km=5570, preferred_departure_time="morning",
    )["content"][0]["json"]

    assert "does NOT match your preferred morning departure time" in result["note"]


def test_search_flights_no_time_note_when_no_preference_given(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(flights_module, "_fetch_real_price", lambda o, d, dep, ret: fake_real_price())

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22", travelers=1, distance_km=5570
    )["content"][0]["json"]

    assert "matches your preferred" not in result["note"]
    assert "does NOT match" not in result["note"]


def test_search_flights_never_modifies_booking_link_for_time_preference(monkeypatch):
    """Regression guard: appending a time-of-day clause to the Google Flights
    query (e.g. ", evening departure preferred") was verified by hand to
    break Google's query parser entirely — it stops recognizing the
    route/dates and lands on a blank generic homepage instead. The booking
    link must always be built from route/dates only; the time preference is
    surfaced honestly via the note instead, never the link."""
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: None)

    baseline = flights_module.search_flights(
        "Austin", "Denver", 30.27, -97.74, 39.74, -104.98, "2026-09-15", "2026-09-22",
        travelers=1, distance_km=1250,
    )["content"][0]["json"]["booking_link"]

    with_preference = flights_module.search_flights(
        "Austin", "Denver", 30.27, -97.74, 39.74, -104.98, "2026-09-15", "2026-09-22",
        travelers=1, distance_km=1250, preferred_departure_time="evening",
    )["content"][0]["json"]["booking_link"]

    assert with_preference == baseline
    assert "evening" not in with_preference


def test_search_flights_ignores_invalid_time_preference(monkeypatch):
    """A bogus value (not one of the four bands) must degrade to no
    preference rather than crashing or silently misclassifying everything as
    a mismatch."""
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: "NYC")
    monkeypatch.setattr(flights_module, "_fetch_real_price", lambda o, d, dep, ret: fake_real_price())

    result = flights_module.search_flights(
        "New York", "London", 40.7128, -74.0060, 51.5074, -0.1278, "2026-09-15", "2026-09-22",
        travelers=1, distance_km=5570, preferred_departure_time="whenever, i dont care",
    )["content"][0]["json"]

    assert "matches your preferred" not in result["note"]
    assert "does NOT match" not in result["note"]
    assert "whenever" not in result["booking_link"]


def test_search_flights_falls_back_to_estimate_when_no_real_price(monkeypatch):
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: None)

    result = flights_module.search_flights(
        "Nowhere", "Alsonowhere", 0.0, 0.0, 1.0, 1.0, "2026-09-15", "2026-09-22", travelers=2, distance_km=1000
    )["content"][0]["json"]

    assert result["real_price_observed"] is False
    assert result["estimated_price_low_usd"] < result["estimated_price_high_usd"]
    assert "no real cached fare" in result["note"].lower()


def test_search_flights_booking_link_is_real_google_flights_search(monkeypatch):
    # Isolated from the real bundled dataset/network — this test only cares
    # about the booking_link, which is built the same way regardless of
    # whether a real price was found.
    monkeypatch.setattr(flights_module, "_nearest_iata_code", lambda lat, lon: None)

    result = flights_module.search_flights(
        "Austin", "Denver", 30.27, -97.74, 39.74, -104.98, "2026-09-15", "2026-09-22", travelers=1, distance_km=1250
    )["content"][0]["json"]

    link = result["booking_link"]
    assert link.startswith("https://www.google.com/travel/flights?q=")
    assert "Austin" in link
    assert "Denver" in link
