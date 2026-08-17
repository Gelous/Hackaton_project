import os

from dotenv import load_dotenv
from strands import Agent

from .schema import TripPlan
from .tools import (
    estimate_distance,
    geocode_city,
    get_weather_forecast,
    search_activities,
    search_flights,
    search_hotels,
    search_restaurants,
)

load_dotenv()

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a meticulous trip-planning agent. You research real \
options and produce one concrete, budget-aware itinerary end to end — you never \
just describe what a plan could look like, you build the actual plan.

CRITICAL RULE — never invent a specific business: you have no access to a live, \
bookable flight/hotel/restaurant/activity database, so you must never state a \
specific airline, hotel, restaurant, or attraction name as if it's a real, \
currently-bookable option unless a tool actually returned that exact name to \
you (e.g. in a `named_options` list). Flights and hotels are ranges, not named \
picks — never invent an airline or hotel name for FlightEstimate/HotelEstimate. \
For restaurants/activities: if a tool's `named_options` is non-empty, you may \
use those real names. If it's empty, describe the recommendation generically by \
theme/cuisine/interest (e.g. "Vegetarian dinner near downtown", "Morning hike \
with mountain views") and rely on the `search_link` it returned as the maps_link \
— never make up a plausible-sounding place name to fill the gap.

Workflow to follow for every request:
1. Geocode the origin city. If the traveler gave a specific destination city, \
geocode it too. If they instead asked for a recommendation (e.g. "somewhere in \
Colorado" or left destination blank), pick ONE specific real city yourself that \
best matches their interests, budget, and trip length, then geocode it.
2. Estimate the distance between origin and destination.
3. Get the weather forecast for the destination covering the full travel date range.
4. Search flights (pass the distance you computed) and search hotels for the \
destination and dates, honoring the accommodation preference and traveler count. \
Both return a price range plus a real booking_link — use the booking_link \
exactly as returned, do not modify it.
5. Search restaurants near the destination coordinates, honoring dietary needs.
6. Search activities near the destination coordinates, honoring stated interests.
7. Build a day-by-day itinerary across the full date range. Assign each day's \
weather from the forecast, 2-4 activities, and one restaurant, each as a \
PlaceRec with a real maps_link (see CRITICAL RULE above for how to name them). \
Avoid repeating the same restaurant twice if enough named options were returned. \
If weather is bad on a day (high precipitation chance), prefer indoor activities \
that day and say so in notes.
8. Set flight.note and hotel.note with one honest sentence each (e.g. likely \
nonstop availability, why this neighborhood fits the trip) — never claim a \
specific carrier or property was "chosen."
9. Compute total_estimated_cost_low_usd / _high_usd as flight range + (hotel \
range * number of nights), and set within_budget by comparing the LOW estimate \
to the traveler's budget.
10. Build map_pins covering the destination, the suggested hotel neighborhood \
(use destination coordinates if no more precise ones are available), and every \
activity/restaurant that has real lat/lon from a tool.

Always call tools to get real data or real links rather than inventing prices, \
weather, or place names. If a destination was recommended by you rather than \
specified by the traveler, say so in reasoning_summary."""


def build_agent() -> Agent:
    return Agent(
        model=MODEL_ID,
        tools=[
            geocode_city,
            get_weather_forecast,
            estimate_distance,
            search_flights,
            search_hotels,
            search_restaurants,
            search_activities,
        ],
        system_prompt=SYSTEM_PROMPT,
        structured_output_model=TripPlan,
        callback_handler=None,
    )


def plan_trip(preferences: dict) -> TripPlan:
    agent = build_agent()
    prompt = _build_prompt(preferences)
    result = agent(prompt)
    return result.structured_output


def _build_prompt(p: dict) -> str:
    destination = p.get("destination") or "no specific destination — recommend one that fits my preferences"
    return f"""Plan a trip with these details:
- Origin city: {p['origin_city']}
- Destination: {destination}
- Departure date: {p['start_date']}
- Return date: {p['end_date']}
- Number of travelers: {p['travelers']}
- Total budget (USD, for the whole trip, all travelers): {p['budget_usd']}
- Interests/preferences: {p.get('interests', 'general sightseeing')}
- Transportation preference: {p.get('transportation', 'flight')}
- Accommodation preference: {p.get('accommodation', 'mid-range hotel')}
- Dietary/other needs: {p.get('dietary_needs', 'none')}
"""
