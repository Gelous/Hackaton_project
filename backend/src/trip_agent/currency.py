"""Real currency conversion — deliberately NOT something the agent ever does
itself. An LLM "converting" currency would just be guessing at a plausible
number, which breaks the same no-fake-data rule the rest of this app follows
for prices, weather, and place names. Instead, the agent always reasons in
USD internally (unchanged), and this module does real conversion as a
deterministic step in server.py, before and after the agent runs.

Rates come from Frankfurter (ECB-backed, free, no API key, no rate limit) —
verified working live during development.
"""

import time
import xml.etree.ElementTree as ET

import httpx

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

# Real second source, not a fabricated fallback: the ECB itself publishes
# this free daily reference-rate feed (no key). Only used if Frankfurter
# (which is itself ECB-backed) is unreachable — used to mirror places.py's
# Overpass mirror-chain pattern instead of letting a single API's outage
# take down every plan/wishlist request that needs a non-USD conversion.
ECB_DAILY_XML_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_ECB_XML_NAMESPACE = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}

# A curated subset of world currencies, not the full ISO 4217 list — keeps
# the frontend dropdown usable. Symbol is for display only; conversion works
# for any pair Frankfurter supports.
SUPPORTED_CURRENCIES = {
    "USD": {"symbol": "$", "name": "US Dollar"},
    "EUR": {"symbol": "€", "name": "Euro"},
    "GBP": {"symbol": "£", "name": "British Pound"},
    "JPY": {"symbol": "¥", "name": "Japanese Yen"},
    "CAD": {"symbol": "C$", "name": "Canadian Dollar"},
    "AUD": {"symbol": "A$", "name": "Australian Dollar"},
    "CHF": {"symbol": "Fr", "name": "Swiss Franc"},
    "CNY": {"symbol": "¥", "name": "Chinese Yuan"},
    "INR": {"symbol": "₹", "name": "Indian Rupee"},
    "MXN": {"symbol": "$", "name": "Mexican Peso"},
    "BRL": {"symbol": "R$", "name": "Brazilian Real"},
    "SGD": {"symbol": "S$", "name": "Singapore Dollar"},
}

# Rates only update once per day (ECB publishes on business days); an hourly
# cache is already far more often than needed and avoids hammering the API.
_CACHE_TTL_SECONDS = 3600
_rate_cache: dict[tuple[str, str], tuple[float, float]] = {}
_ecb_rates_cache: tuple[dict[str, float], float] | None = None


class CurrencyUnavailableError(RuntimeError):
    """Raised when neither Frankfurter nor the ECB fallback can provide a
    live rate. server.py catches this specifically to return a clean 503
    ("try again shortly") instead of letting an unhandled exception 500 a
    request that never even reached the agent yet."""


def _fetch_ecb_eur_rates() -> dict[str, float]:
    global _ecb_rates_cache
    if _ecb_rates_cache and (time.time() - _ecb_rates_cache[1]) < _CACHE_TTL_SECONDS:
        return _ecb_rates_cache[0]

    response = httpx.get(ECB_DAILY_XML_URL, timeout=8)
    response.raise_for_status()
    root = ET.fromstring(response.text)

    rates = {"EUR": 1.0}
    for cube in root.findall(".//ecb:Cube[@currency]", _ECB_XML_NAMESPACE):
        rates[cube.attrib["currency"]] = float(cube.attrib["rate"])

    _ecb_rates_cache = (rates, time.time())
    return rates


def _get_rate_from_ecb(from_currency: str, to_currency: str) -> float:
    """The ECB only publishes EUR-based rates, so any other pair is pivoted
    through EUR — e.g. USD->GBP is (EUR->GBP) / (EUR->USD)."""
    rates = _fetch_ecb_eur_rates()
    if from_currency not in rates or to_currency not in rates:
        raise KeyError(f"ECB feed has no rate for {from_currency} or {to_currency}")
    return rates[to_currency] / rates[from_currency]


def get_rate(from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return 1.0

    key = (from_currency, to_currency)
    cached = _rate_cache.get(key)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        response = httpx.get(
            FRANKFURTER_URL, params={"base": from_currency, "symbols": to_currency}, timeout=8
        )
        response.raise_for_status()
        rate = response.json()["rates"][to_currency]
    except Exception:
        try:
            rate = _get_rate_from_ecb(from_currency, to_currency)
        except Exception as exc:
            raise CurrencyUnavailableError(
                f"Couldn't get a live {from_currency}->{to_currency} exchange rate from "
                "either Frankfurter or the ECB fallback — try again shortly."
            ) from exc

    _rate_cache[key] = (rate, time.time())
    return rate


def convert(amount: float, from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return amount
    return round(amount * get_rate(from_currency, to_currency), 2)
