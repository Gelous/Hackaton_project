from pydantic import BaseModel, Field


class FlightEstimate(BaseModel):
    estimated_price_low: float
    estimated_price_high: float = Field(description="Round-trip travel-cost range: for a flight, for all travelers combined; for driving, for one vehicle covering the whole group (see TripPlan.transportation)")
    booking_link: str = Field(description="A real link matching the mode used — Google Flights (pre-filled route/dates) if flying, or Google Maps driving directions if driving")
    note: str = Field(description="One sentence on what to expect (e.g. nonstop likelihood and best time to book for a flight; fuel vs. full-cost range for driving)")


class HotelEstimate(BaseModel):
    estimated_price_low: float
    estimated_price_high: float = Field(description="Nightly price range for the requested accommodation tier")
    suggested_neighborhood: str = Field(description="A real neighborhood/area in the destination worth staying in, based on the itinerary")
    booking_link: str = Field(description="Real Google Hotels link, pre-filled with the destination and dates, showing real hotels and current prices to book")
    note: str = Field(description="One sentence on why this neighborhood/tier fits the trip")


class PlaceRec(BaseModel):
    name: str = Field(description="A specific real place name if one was found, otherwise a short theme label like 'Vegetarian dinner near downtown'")
    category: str = Field(description="e.g. restaurant, museum, park, viewpoint, coffee shop")
    maps_link: str = Field(description="Real Google Maps link the traveler can open to see reviews, real current options, get directions, or reserve")


class DayPlan(BaseModel):
    day_number: int
    date: str
    weather_summary: str
    activities: list[PlaceRec] = Field(description="2-4 planned activities/attractions for the day, each with a real maps_link")
    restaurant: PlaceRec = Field(description="Recommended restaurant for the day, with a real maps_link")
    notes: str = Field(default="", description="Any weather/budget/logistics caveat for this day")


class MapPin(BaseModel):
    label: str
    category: str = Field(description="One of: destination, hotel, activity, restaurant, origin")
    lat: float
    lon: float


class EventRec(BaseModel):
    name: str = Field(description="A specific real event name if one was found, otherwise a short theme label like 'Live jazz somewhere downtown'")
    category: str = Field(description="e.g. Music, Comedy, Sports, Arts & Theatre, Film")
    date: str = Field(default="", description="Event date, YYYY-MM-DD, if a specific event was found")
    time: str = Field(default="", description="Event start time, if known")
    venue_name: str = Field(default="", description="Venue name, if a specific event was found")
    ticket_link: str = Field(description="Real Ticketmaster event/ticket link if a specific event was found, otherwise a real Ticketmaster search link for the city")


class DayOutPlan(BaseModel):
    city: str
    country: str
    date: str
    mood_or_interest: str
    weather_summary: str
    activities: list[PlaceRec] = Field(description="2-4 activities for the day matching the traveler's mood/interest, each with a real maps_link")
    restaurant: PlaceRec = Field(description="Recommended restaurant for the day, with a real maps_link")
    events: list[EventRec] = Field(default_factory=list, description="0-5 real local events (concerts, shows, etc.) happening that day, matching the mood/interest when possible. An empty list is the honest answer if none were found — never invented to fill it")
    map_pins: list[MapPin]
    reasoning_summary: str = Field(description="1-3 sentences on how this day was put together around the stated mood/interest")


class DestinationRecommendation(BaseModel):
    destination_city: str
    destination_country: str
    destination_lat: float
    destination_lon: float
    reasoning: str = Field(description="1-3 sentences on why this destination fits the traveler's interests, budget, and flexible timeframe")


class TripPlan(BaseModel):
    origin_city: str
    destination_city: str
    destination_country: str
    destination_lat: float
    destination_lon: float
    distance_km: float
    currency: str = Field(
        default="USD",
        description="ISO 4217 code all monetary fields in this plan are expressed in. The agent always reasons in USD — "
        "if a different currency is needed, server.py converts every monetary field (and this code) using a real "
        "live exchange rate after the agent finishes, never by the agent itself.",
    )
    total_estimated_cost_low: float
    total_estimated_cost_high: float
    budget: float
    within_budget: bool = Field(description="True if total_estimated_cost_low fits within budget")
    transportation: str = Field(
        default="flight",
        description="'drive' if estimate_driving_cost was used to fill the flight field, "
        "otherwise 'flight'. Lets the frontend label/link the field correctly instead of "
        "always assuming it's an airfare.",
    )
    flight: FlightEstimate
    hotel: HotelEstimate
    days: list[DayPlan]
    map_pins: list[MapPin]
    reasoning_summary: str = Field(description="2-4 sentences summarizing the overall plan and key tradeoffs made")
