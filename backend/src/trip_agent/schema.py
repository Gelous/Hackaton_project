from pydantic import BaseModel, Field


class FlightEstimate(BaseModel):
    estimated_price_low_usd: float
    estimated_price_high_usd: float = Field(description="Round-trip price range for all travelers combined")
    booking_link: str = Field(description="Real Google Flights link, pre-filled with the route and dates, showing real airlines and current prices to book")
    note: str = Field(description="One sentence on what to expect (e.g. nonstop likelihood, best time to book)")


class HotelEstimate(BaseModel):
    estimated_price_low_usd: float
    estimated_price_high_usd: float = Field(description="Nightly price range for the requested accommodation tier")
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


class TripPlan(BaseModel):
    origin_city: str
    destination_city: str
    destination_country: str
    destination_lat: float
    destination_lon: float
    distance_km: float
    total_estimated_cost_low_usd: float
    total_estimated_cost_high_usd: float
    budget_usd: float
    within_budget: bool = Field(description="True if total_estimated_cost_low_usd fits within budget_usd")
    flight: FlightEstimate
    hotel: HotelEstimate
    days: list[DayPlan]
    map_pins: list[MapPin]
    reasoning_summary: str = Field(description="2-4 sentences summarizing the overall plan and key tradeoffs made")
