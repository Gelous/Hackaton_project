import os

from dotenv import load_dotenv
from strands import Agent

from .schema import DayOutPlan, DestinationRecommendation, TripPlan
from .tools import (
    estimate_distance,
    estimate_driving_cost,
    geocode_city,
    get_weather_forecast,
    search_activities,
    search_events,
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
you (e.g. in a `named_options` list, or named directly in search_flights' \
`note`). HotelEstimate's *price* is always a range, never a confirmed rate for \
a specific hotel — but search_hotels' `named_options` (real hotels/hostels from \
OpenStreetMap, when found) IS real data you should copy through into \
HotelEstimate.named_options verbatim; never invent a hotel name yourself, and \
never imply the price range is that specific hotel's confirmed rate just \
because it's named. Flights are usually a range too, EXCEPT when \
search_flights' note names a real airline and flight number (a real cached \
fare it found) — in that case you may repeat that exact airline/flight number \
in FlightEstimate.note, but never invent one when the note doesn't name one. \
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
4. Search hotels for the destination and dates, honoring the accommodation \
preference and traveler count, and passing the destination's exact latitude/ \
longitude from geocode_city (enables the real named-hotel search) — it \
returns a price range plus a real booking_link, use it exactly as returned, \
and copy its `named_options` into HotelEstimate.named_options exactly as \
returned (empty list if it found none — never invent one to fill it). For \
the travel-cost field: if the \
transportation preference is "drive", call estimate_driving_cost (pass the \
distance you computed) instead of search_flights — driving cost doesn't \
scale per traveler the way airfare does, and its booking_link is real \
driving directions, not a flight search. Otherwise (flight, or no strong \
preference), call search_flights, passing the exact origin/destination \
latitude and longitude you got from geocode_city (it uses them to look up \
real flight prices), and the traveler's exact preferred_departure_time if \
they stated one — never pick a time preference yourself. Either way, set \
transportation to whichever one you actually called ("drive" or "flight").
5. Search restaurants near the destination coordinates, honoring dietary needs.
6. Search activities near the destination coordinates, honoring stated interests.
7. Build a day-by-day itinerary across the full date range. Assign each day's \
weather from the forecast, 2-4 activities, and one restaurant, each as a \
PlaceRec with a real maps_link (see CRITICAL RULE above for how to name them). \
Avoid repeating the same restaurant twice if enough named options were returned. \
If weather is bad on a day (high precipitation chance), prefer indoor activities \
that day and say so in notes. For each day, also call search_events with the \
destination and that exact day's date, using the traveler's stated interests as \
mood_or_interest, leaving event_type unset (any type), and passing the \
destination's country_code, latitude, and longitude from geocode_city \
(disambiguates a city name that exists in multiple countries, and lets the \
tool fall back to a coordinate search if the city name doesn't match \
Ticketmaster's own spelling for it) — include the real \
events it returns (0-2 per day) in that day's `events` list, same honesty rule \
as activities/restaurants: never invent one to fill the list, an empty list is a \
fine, honest answer for a quiet day.
8. Set flight.note and hotel.note with one honest sentence each. For flight.note, \
check search_flights' `real_price_observed` field: if true, say plainly that this \
is a real recent price (its `note` already tells you whether it matches the exact \
dates or nearby cached ones, names a real airline/flight number if one was found, \
and — if a preferred_departure_time was given — whether this specific fare's \
departure time actually matches it or not — carry all of that over faithfully, \
don't claim "exact dates" if it wasn't, only name a carrier if the tool's note \
actually named one, and never claim a time-of-day match the tool didn't confirm); \
if false, describe it as an estimate as usual. Never claim a price \
is real when `real_price_observed` is false, and never claim a specific carrier or \
property was "chosen."
9. Compute total_estimated_cost_low / _high as flight range + (hotel range * \
number of nights), and set within_budget by comparing the LOW estimate to the \
traveler's budget.
10. Build map_pins covering the destination, the suggested hotel neighborhood \
(use destination coordinates if no more precise ones are available), and every \
activity/restaurant/event that has real lat/lon from a tool. For each activity \
and restaurant pin, set its `label` to that exact place's `name` field, character \
for character — a downstream step matches them by that label to compute a real \
travel-time estimate, so a mismatched label silently loses that for the traveler.
11. Always set currency to "USD" — every number you produce is in US dollars, \
regardless of what currency the traveler asked for. If they need a different \
currency, that conversion happens outside your response using a real exchange \
rate; you never estimate or state a currency conversion yourself. For this \
same reason, never quote a specific dollar figure inside reasoning_summary or \
any day's notes — those are free text that won't get converted, so a number \
written there could end up silently wrong for a traveler in another currency. \
Talk about budget qualitatively instead ("comfortably within budget", "leaves \
room for a few nice dinners") — the exact numbers are already shown precisely \
in the structured fields.

Always call tools to get real data or real links rather than inventing prices, \
weather, or place names. If a destination was recommended by you rather than \
specified by the traveler, say so in reasoning_summary.

If past trip feedback from this traveler is included in the request, use it: lean \
into places/activities similar to what they rated highly, and steer away from \
patterns in trips they rated poorly. Don't over-fit to one data point, and don't \
mention the feedback mechanically — just let it genuinely inform the choice."""


def build_agent() -> Agent:
    return Agent(
        model=MODEL_ID,
        tools=[
            geocode_city,
            get_weather_forecast,
            estimate_distance,
            search_flights,
            estimate_driving_cost,
            search_hotels,
            search_restaurants,
            search_activities,
            search_events,
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


TOOL_PROGRESS_MESSAGES = {
    "geocode_city": "Finding coordinates...",
    "get_weather_forecast": "Checking the weather...",
    "estimate_distance": "Calculating distance & travel time...",
    "search_flights": "Comparing flight options...",
    "search_hotels": "Comparing hotel options...",
    "search_restaurants": "Finding restaurants...",
    "search_activities": "Finding activities & attractions...",
    "search_events": "Finding local events...",
    "TripPlan": "Composing your itinerary...",
    "DayOutPlan": "Putting your day together...",
}


async def plan_trip_stream(preferences: dict):
    """Async generator yielding live progress while the agent works, ending
    with {"type": "done", "plan": <TripPlan dict>}. Backs the streaming
    /api/plan/stream endpoint so the UI can show real step-by-step progress
    ("Checking the weather...", "Comparing flights...") instead of one long
    silent wait — and it's a genuine trace of what the agent is doing, not a
    fake progress bar."""
    agent = build_agent()
    prompt = _build_prompt(preferences)

    seen_tool_use_ids = set()
    async for event in agent.stream_async(prompt):
        current_tool_use = event.get("current_tool_use")
        if current_tool_use:
            tool_use_id = current_tool_use.get("toolUseId")
            tool_name = current_tool_use.get("name")
            if tool_use_id and tool_name and tool_use_id not in seen_tool_use_ids:
                seen_tool_use_ids.add(tool_use_id)
                message = TOOL_PROGRESS_MESSAGES.get(tool_name, f"Running {tool_name}...")
                yield {"type": "progress", "message": message}

        if "result" in event:
            yield {"type": "done", "plan": event["result"].structured_output.model_dump()}


DAY_SYSTEM_PROMPT = """You are a local-day planning agent — given a city, a specific date, and \
a traveler's mood or interest, you build one real, concrete plan for that single day: a couple \
of activities, a restaurant, and any real local events (concerts, shows, etc.) actually \
happening that day. This is for someone planning a single day out in a city, not a multi-day \
trip — there is no flight or hotel involved.

CRITICAL RULE — never invent a specific business or event: you have no access to a live, \
bookable database, so you must never state a specific restaurant, attraction, or event name as \
if it's real unless a tool actually returned that exact name to you (e.g. in a `named_options` \
list). If a tool's `named_options` is empty, describe the recommendation generically by \
theme/mood (e.g. "Live music somewhere downtown") and rely on its `search_link` — never make up \
a plausible-sounding name to fill the gap. This applies doubly to events: never invent a \
concert, show, or event name, or claim one is happening on a date you didn't get from \
search_events. An empty events list is a perfectly honest result.

Workflow:
1. Get a search anchor point. If the prompt already gives you exact coordinates (the traveler's \
real device location, more precise than any city center), use those directly as latitude/ \
longitude/country/country_code for every step below — do not call geocode_city in that case, \
it would only throw away precision you already have. Otherwise, geocode the city to get its \
center coordinates and use those. Set city_lat/city_lon in the output to this exact anchor \
point either way — server.py uses it to compute real travel times from here to everything else.
2. Get the weather forecast covering the given date, at the anchor point.
3. Search activities near the anchor point, honoring the stated mood/interest.
4. Search restaurants near the anchor point, honoring any dietary needs mentioned.
5. Search events for the city and date. Always pass the traveler's exact event_type and \
max_events through to search_events unchanged — these are explicit choices from a form, not \
yours to reinterpret. Also pass the anchor point's country_code, latitude, and longitude from \
step 1, so a city name that exists in multiple countries resolves to the right one, and so the \
tool can fall back to a coordinate search if the city name doesn't match Ticketmaster's own \
spelling for it. Use mood/interest only as the tool's soft bias, not a hard filter. Include the \
real events returned (0 to max_events) in the `events` list, never padded with an invented one.
6. Build map_pins covering the anchor point and every activity/restaurant/event that has real \
lat/lon from a tool. This is a day out, not a trip — never include a hotel pin or any \
accommodation suggestion; there is nowhere to stay overnight in this plan.
7. Write a short reasoning_summary tying the day together around the stated mood/interest.

Always call tools to get real data or real links rather than inventing weather, place names, \
or event names.

If past day-out feedback from this traveler is included in the request, use it: lean into \
cities/moods similar to what they rated highly, and steer away from patterns in days they \
rated poorly. Don't over-fit to one data point, and don't mention the feedback mechanically — \
just let it genuinely inform the choice."""


def build_day_agent() -> Agent:
    return Agent(
        model=MODEL_ID,
        tools=[geocode_city, get_weather_forecast, search_restaurants, search_activities, search_events],
        system_prompt=DAY_SYSTEM_PROMPT,
        structured_output_model=DayOutPlan,
        callback_handler=None,
    )


def _format_day_feedback_history(history: list[dict] | None) -> str:
    """Real, stored feedback from this traveler's past day plans — same
    honesty rule as _format_feedback_history below (never fabricated, and
    omitted entirely rather than invented when there's none yet)."""
    if not history:
        return ""
    lines = []
    for h in history:
        line = f"- {h['city']} ({h['mood_or_interest']}): {h['rating']}/5"
        if h.get("feedback_text"):
            line += f' — "{h["feedback_text"]}"'
        lines.append(line)
    return "\n- Past day-out feedback from this traveler:\n" + "\n".join(lines) + "\n"


def _build_day_prompt(p: dict) -> str:
    location_line = f"- City: {p['city']}"
    if p.get("lat") is not None and p.get("lon") is not None:
        # Real device geolocation (see /api/reverse-geocode) — more precise
        # than a city center, so the agent is told to use it directly rather
        # than re-geocoding away that precision (see DAY_SYSTEM_PROMPT step 1).
        location_line += (
            f"\n- Exact anchor point (the traveler's real current location — use directly, do not "
            f"call geocode_city): latitude={p['lat']}, longitude={p['lon']}, "
            f"country={p.get('country') or 'unknown, infer from coordinates if needed'}, "
            f"country_code={p.get('country_code') or 'unknown, infer from coordinates if needed'}"
        )
    return f"""Plan a single day out with these details:
{location_line}
- Date: {p['date']}
- Mood/interest: {p.get('mood_or_interest', 'general sightseeing')}
- Event type filter: {p.get('event_type') or 'Any (pass event_type="" to search_events)'}
- Max number of events to include (pass to search_events exactly as-is): {p.get('max_events', 5)}
- Dietary/other needs: {p.get('dietary_needs', 'none')}
{_format_day_feedback_history(p.get('feedback_history'))}"""


def plan_day(preferences: dict) -> DayOutPlan:
    agent = build_day_agent()
    prompt = _build_day_prompt(preferences)
    result = agent(prompt)
    return result.structured_output


async def plan_day_stream(preferences: dict):
    """Same streaming-progress pattern as plan_trip_stream, for the day planner."""
    agent = build_day_agent()
    prompt = _build_day_prompt(preferences)

    seen_tool_use_ids = set()
    async for event in agent.stream_async(prompt):
        current_tool_use = event.get("current_tool_use")
        if current_tool_use:
            tool_use_id = current_tool_use.get("toolUseId")
            tool_name = current_tool_use.get("name")
            if tool_use_id and tool_name and tool_use_id not in seen_tool_use_ids:
                seen_tool_use_ids.add(tool_use_id)
                message = TOOL_PROGRESS_MESSAGES.get(tool_name, f"Running {tool_name}...")
                yield {"type": "progress", "message": message}

        if "result" in event:
            yield {"type": "done", "plan": event["result"].structured_output.model_dump()}


DESTINATION_SYSTEM_PROMPT = """You help travelers pick ONE real destination city that fits \
their interests, budget, and a flexible travel window — you are not building a full \
itinerary, just choosing where. This is for a wishlist entry with no fixed dates yet, so \
consider the whole window (e.g. don't recommend a ski town for a summer-only window).

Workflow:
1. Geocode the origin city.
2. Pick ONE specific real city that best matches the traveler's interests and budget.
3. Geocode your chosen destination to get real coordinates.
4. Estimate the distance from origin, then check a rough flight price estimate (for a trip \
of the stated length, starting near the middle of the flexible window) to sanity-check it \
leaves enough of the budget for hotel/food — if it doesn't fit, pick a more affordable \
destination and check again.
5. Briefly explain your reasoning.

Always call tools to verify the destination is real and roughly affordable rather than \
guessing — same rule as everywhere else in this app: never invent a fact you can check.

If past trip feedback from this traveler is included in the request, use it: lean \
into destinations similar to what they rated highly, and steer away from patterns \
in trips they rated poorly."""


def build_destination_agent() -> Agent:
    return Agent(
        model=MODEL_ID,
        tools=[geocode_city, get_weather_forecast, estimate_distance, search_flights],
        system_prompt=DESTINATION_SYSTEM_PROMPT,
        structured_output_model=DestinationRecommendation,
        callback_handler=None,
    )


def recommend_destination(preferences: dict) -> DestinationRecommendation:
    """The only LLM call the wishlist feature needs — picks a real destination
    once, at creation time. Ongoing wishlist re-checks are pure tool calls
    (see wishlist_monitor.py), no repeated agent/Bedrock cost."""
    agent = build_destination_agent()
    prompt = f"""Pick one destination for a traveler with these details:
- Origin city: {preferences['origin_city']}
- Flexible travel window: {preferences['earliest_date']} through {preferences['latest_date']}
- Trip length: {preferences['trip_length_days']} days
- Budget ceiling (USD, total): {preferences['budget_usd']}
- Interests: {preferences.get('interests', 'general sightseeing')}
{_format_feedback_history(preferences.get('feedback_history'))}"""
    result = agent(prompt)
    return result.structured_output


def _format_feedback_history(history: list[dict] | None) -> str:
    """Real, stored feedback from this traveler's past trips — never
    fabricated. Empty string (no section at all) when there's none yet."""
    if not history:
        return ""
    lines = []
    for h in history:
        line = f"- {h['destination_city']}: {h['feedback_rating']}/5"
        if h.get("feedback_text"):
            line += f' — "{h["feedback_text"]}"'
        lines.append(line)
    return "\n- Past trip feedback from this traveler:\n" + "\n".join(lines) + "\n"


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
- Preferred departure time: {p.get('preferred_departure_time') or 'no preference'}
- Accommodation preference: {p.get('accommodation', 'mid-range hotel')}
- Dietary/other needs: {p.get('dietary_needs', 'none')}
{_format_feedback_history(p.get('feedback_history'))}"""
