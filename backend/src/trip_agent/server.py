import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, ratelimit, scheduler
from .agent import plan_day, plan_day_stream, plan_trip, plan_trip_stream, recommend_destination
from .currency import SUPPORTED_CURRENCIES, CurrencyUnavailableError, convert
from .local_watch_monitor import evaluate_local_watch
from .monitor import check_for_updates
from .places_search import reverse_geocode, search_cities
from .tools.geocode import geocode_city
from .travel_estimates import add_day_travel_estimates, add_travel_estimates
from .wishlist_monitor import evaluate_wishlist_item


def verified_session(x_session_token: str | None = Header(default=None)) -> int | None:
    """Verifies the HMAC signature auth.issue_session_token() attaches, so a
    request can't just set the header to any value and act as a different
    account. None means "not logged in" (no header sent); an invalid/tampered
    token is rejected outright rather than silently treated as logged-out,
    since that would reopen the same hole for a malformed-on-purpose header."""
    if x_session_token is None:
        return None
    user_id = auth.verify_session_token(x_session_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid session — please log in again")
    return user_id


def require_login(user_id: int | None = Depends(verified_session)) -> int:
    """For endpoints that need a real logged-in user — an account is now
    mandatory to plan, save, or monitor anything (see db.py's module
    docstring), so this backs every one of those endpoints, not just
    /api/auth/*. Turns the "not logged in" case into a clean 401 instead of
    every such endpoint re-checking None itself.

    Also confirms the account still exists: a session token's signature
    alone doesn't prove that — it stays signature-valid even after the
    account behind it was deleted (see /api/auth/account), e.g. a stray
    background request using a token a just-completed deletion hasn't
    cleared client-side yet. Every endpoint below assumes db.get_user_by_id
    returns a real row, so this is the one place that guarantees it rather
    than each of them separately guarding against None."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Log in to use this")
    if db.get_user_by_id(user_id) is None:
        raise HTTPException(status_code=401, detail="Account no longer exists — please log in again")
    return user_id


def require_client_id(user_id: int = Depends(require_login)) -> str:
    """Every trip/wishlist/watch/notification is scoped by a client_id
    string, same as before accounts existed — but now that string is derived
    deterministically from the authenticated account instead of a self-issued
    anonymous browser token, so a visitor's data is tied to a real login they
    control (real data privacy) rather than whatever id happened to be in
    localStorage. Reuses every existing client_id-scoped db.py function
    unchanged."""
    return f"account:{user_id}"


def _localize_plan(plan_dict: dict, original_budget: float, currency: str) -> dict:
    """The agent always returns a plan priced in USD (see agent.py's system
    prompt) — this converts every monetary field to the traveler's requested
    currency using a real live rate, as a deterministic step the LLM never
    touches. `budget` is set from the traveler's exact original input rather
    than re-converting the echoed USD value, so it can't drift from rounding."""
    if currency != "USD":
        plan_dict["flight"]["estimated_price_low"] = convert(plan_dict["flight"]["estimated_price_low"], "USD", currency)
        plan_dict["flight"]["estimated_price_high"] = convert(plan_dict["flight"]["estimated_price_high"], "USD", currency)
        plan_dict["hotel"]["estimated_price_low"] = convert(plan_dict["hotel"]["estimated_price_low"], "USD", currency)
        plan_dict["hotel"]["estimated_price_high"] = convert(plan_dict["hotel"]["estimated_price_high"], "USD", currency)
        plan_dict["total_estimated_cost_low"] = convert(plan_dict["total_estimated_cost_low"], "USD", currency)
        plan_dict["total_estimated_cost_high"] = convert(plan_dict["total_estimated_cost_high"], "USD", currency)
        plan_dict["currency"] = currency
    plan_dict["budget"] = original_budget
    return plan_dict


def _convert_budget_to_usd(budget: float, currency: str) -> float:
    """Thin wrapper so every call site gets a clean 503 instead of an
    unhandled 500 if both currency.py's real sources (Frankfurter and its
    ECB fallback) are down — this runs before the agent is ever called, so
    there's no partial/expensive work to worry about losing."""
    try:
        return convert(budget, currency, "USD")
    except CurrencyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.start_scheduler()
    yield
    scheduler.stop_scheduler()


app = FastAPI(title="Trip Planner Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_for_frontend_assets(request, call_next):
    """The frontend is actively changing during development, and browsers
    will happily cache index.html/app.js/style.css with no explicit
    Cache-Control header — the exact issue that caused an old (pre-redesign)
    theme to keep reappearing during testing. This forces a revalidation on
    every load instead of relying on manually bumping a ?v= query string."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


class PlanRequest(BaseModel):
    origin_city: str
    destination: str = ""
    start_date: str
    end_date: str
    travelers: int = 1
    budget: float
    currency: str = "USD"
    interests: str = "general sightseeing"
    transportation: str = "flight"
    preferred_departure_time: str = ""
    accommodation: str = "mid-range hotel"
    dietary_needs: str = "none"


class MonitorRequest(BaseModel):
    plan: dict


class ChooseHotelRequest(BaseModel):
    plan: dict
    hotel_name: str
    hotel_lat: float
    hotel_lon: float


class SaveTripRequest(BaseModel):
    plan: dict
    alerts: bool = True


class TripFeedbackRequest(BaseModel):
    rating: int
    feedback_text: str | None = None


class DayPlanRequest(BaseModel):
    city: str
    date: str
    mood_or_interest: str = "general sightseeing"
    event_type: str = ""
    max_events: int = Field(default=5, ge=1, le=5)
    dietary_needs: str = "none"
    # Set only when the traveler used real device/account location (see
    # /api/reverse-geocode) rather than typing a city — lets the agent anchor
    # every nearby search to that exact point instead of a city center (see
    # agent.py's DAY_SYSTEM_PROMPT step 1).
    lat: float | None = None
    lon: float | None = None
    country: str | None = None
    country_code: str | None = None


class DayPlanFeedbackRequest(BaseModel):
    city: str
    mood_or_interest: str
    rating: int
    feedback_text: str | None = None


class WishlistRequest(BaseModel):
    origin_city: str
    destination: str = ""
    earliest_date: str
    latest_date: str
    trip_length_days: int = 5
    budget: float
    currency: str = "USD"
    interests: str = "general sightseeing"
    alerts: bool = True


class LocalWatchRequest(BaseModel):
    city: str
    mood_or_interest: str = "general sightseeing"
    event_type: str = ""
    alerts: bool = True


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class HomeLocationRequest(BaseModel):
    city: str
    country: str
    lat: float
    lon: float


class PreferencesRequest(BaseModel):
    default_currency: str | None = None
    default_transportation: str | None = None
    default_accommodation: str | None = None
    notify_email: str | None = None


class SettingsRequest(BaseModel):
    email_notifications_enabled: bool = True
    in_app_notifications_enabled: bool = True
    font_scale: str = Field(default="medium", pattern="^(small|medium|large)$")
    theme: str = Field(default="light", pattern="^(light|dark)$")


@app.get("/api/cities")
def get_city_suggestions(q: str = ""):
    """Worldwide city autocomplete for the starting city / destination fields."""
    if len(q.strip()) < 2:
        return []
    return search_cities(q.strip())


@app.get("/api/currencies")
def get_currencies():
    return SUPPORTED_CURRENCIES


@app.get("/api/reverse-geocode")
def reverse_geocode_endpoint(lat: float, lon: float):
    """Powers "use my current location": the browser's Geolocation API gives
    real coordinates, this turns them into a real city name (see
    places_search.reverse_geocode) — never a guessed one. 404 (not 502) on
    failure, since "these coordinates don't resolve to a named city" is a
    normal, expected outcome (open ocean, no data coverage there, etc.), not
    a server error."""
    result = reverse_geocode(lat, lon)
    if result is None:
        raise HTTPException(status_code=404, detail="Couldn't determine a city for that location")
    return result


def _user_profile(user: dict) -> dict:
    """The subset of a user row that's safe to send to the client — never
    the password hash/salt, even though they're already one-way hashes."""
    return {
        "email": user["email"],
        "home_city": user["home_city"],
        "home_country": user["home_country"],
        "home_lat": user["home_lat"],
        "home_lon": user["home_lon"],
        "default_currency": user["default_currency"],
        "default_transportation": user["default_transportation"],
        "default_accommodation": user["default_accommodation"],
        "notify_email": user["notify_email"],
        "email_notifications_enabled": bool(user["email_notifications_enabled"]),
        "in_app_notifications_enabled": bool(user["in_app_notifications_enabled"]),
        "font_scale": user["font_scale"],
        "theme": user["theme"],
    }


def _alert_email(user_id: int, alerts: bool) -> str | None:
    """The account's own address (preferring the saved notify_email default,
    falling back to the login email) — every alert now goes to a real,
    verified account address, never a manually-typed one a traveler could
    mistype, since login is mandatory anyway (see db.py's module docstring).
    None when the traveler unchecked "email me" for this item, or when the
    account's email_notifications_enabled setting is off — that setting is a
    hard override of every per-item checkbox at once, not just a default."""
    if not alerts:
        return None
    user = db.get_user_by_id(user_id)
    if not user["email_notifications_enabled"]:
        return None
    return user["notify_email"] or user["email"]


@app.post("/api/auth/signup")
def signup(req: SignupRequest):
    email = req.email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    password_hash, salt = auth.hash_password(req.password)
    user_id = db.create_user(email, password_hash, salt)
    if user_id is None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    session_token = auth.issue_session_token(user_id)
    user = db.get_user_by_id(user_id)
    return {"session_token": session_token, **_user_profile(user)}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    email = req.email.strip().lower()
    user = db.get_user_by_email(email)
    # Same "invalid email or password" message either way (checked below) —
    # confirming an email doesn't have an account would let someone enumerate
    # registered addresses one guess at a time.
    if user is None or not auth.verify_password(req.password, user["password_hash"], user["password_salt"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    session_token = auth.issue_session_token(user["id"])
    return {"session_token": session_token, **_user_profile(user)}


@app.get("/api/auth/me")
def get_me(user_id: int = Depends(require_login)):
    # require_login already confirms this account still exists (see its
    # docstring) — no None-check needed here.
    return _user_profile(db.get_user_by_id(user_id))


@app.post("/api/auth/home-location")
def set_home_location(req: HomeLocationRequest, user_id: int = Depends(require_login)):
    """Called after "use my current location" resolves real coordinates to a
    real city (or the traveler just types one in) — saved to the account so
    Trip Planner/Day Out can pre-fill it automatically on future visits,
    across devices, without asking for location permission every time."""
    db.update_home_location(user_id, req.city, req.country, req.lat, req.lon)
    return _user_profile(db.get_user_by_id(user_id))


@app.post("/api/auth/preferences")
def set_preferences(req: PreferencesRequest, user_id: int = Depends(require_login)):
    """Saved defaults for currency/transportation/accommodation/alert email —
    the account's Profile page (see the frontend's hamburger menu) writes
    here. Purely a convenience prefill for the matching form fields, same
    "always still editable, never a lock-in" rule as home city."""
    db.update_preferences(
        user_id, req.default_currency, req.default_transportation, req.default_accommodation, req.notify_email
    )
    return _user_profile(db.get_user_by_id(user_id))


@app.post("/api/auth/settings")
def set_settings(req: SettingsRequest, user_id: int = Depends(require_login)):
    """Account-wide controls (see the frontend's Settings section):
    email_notifications_enabled is a hard override of every per-item "email
    me" checkbox (see _alert_email); in_app_notifications_enabled hides the
    notification inbox without deleting anything underneath it;
    font_scale/theme are pure display preferences the frontend applies as
    CSS custom properties/data attributes."""
    db.update_settings(user_id, req.email_notifications_enabled, req.in_app_notifications_enabled, req.font_scale, req.theme)
    return _user_profile(db.get_user_by_id(user_id))


@app.delete("/api/auth/account")
def delete_account(user_id: int = Depends(require_login)):
    """Real, permanent deletion — every trip/wishlist/watch/notification/
    day-plan-feedback row this account owns, then the account itself (see
    db.py's delete_account_data/delete_user). No undo: the frontend's
    confirmation step is what stands between a click and this actually
    running, so it should never be reachable without a deliberate confirm."""
    db.delete_account_data(f"account:{user_id}")
    db.delete_user(user_id)
    return {"status": "ok"}


@app.post("/api/plan")
def create_plan(req: PlanRequest, x_client_id: str = Depends(require_client_id)):
    ratelimit.enforce(x_client_id)
    # The agent always reasons in USD (see agent.py) — convert the traveler's
    # budget to USD before it ever sees the request, then convert the
    # response back to their currency. The agent itself never does currency
    # math, only this deterministic Python step does, using a real live rate.
    budget_usd = _convert_budget_to_usd(req.budget, req.currency)
    preferences = {
        **req.model_dump(),
        "budget_usd": budget_usd,
        "feedback_history": db.get_feedback_history(x_client_id),
    }
    try:
        plan = plan_trip(preferences)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planning failed: {exc}") from exc
    plan_dict = plan.model_dump()
    add_travel_estimates(plan_dict)
    try:
        _localize_plan(plan_dict, req.budget, req.currency)
    except CurrencyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return plan_dict


@app.post("/api/plan/stream")
async def create_plan_stream(req: PlanRequest, x_client_id: str = Depends(require_client_id)):
    """Same planning flow as /api/plan, but streams newline-delimited JSON
    progress events (a real trace of which tool the agent is currently
    calling) while it works, ending with a {"type": "done", "plan": ...}
    line. Used by the frontend instead of the plain /api/plan endpoint so the
    UI can show live progress on the 20-40s plan generation."""
    ratelimit.enforce(x_client_id)
    budget_usd = _convert_budget_to_usd(req.budget, req.currency)
    preferences = {
        **req.model_dump(),
        "budget_usd": budget_usd,
        "feedback_history": db.get_feedback_history(x_client_id),
    }

    async def event_stream():
        try:
            async for event in plan_trip_stream(preferences):
                if event.get("type") == "done":
                    add_travel_estimates(event["plan"])
                    _localize_plan(event["plan"], req.budget, req.currency)
                yield json.dumps(event) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/day-plan")
def create_day_plan(req: DayPlanRequest, x_client_id: str = Depends(require_client_id)):
    """No fixed trip, no travel — a same-day plan for one city, driven by a
    mood/interest instead of a full preferences form. No budget/currency
    involved, so unlike /api/plan there's no localization step needed."""
    ratelimit.enforce(x_client_id)
    preferences = {**req.model_dump(), "feedback_history": db.get_day_plan_feedback_history(x_client_id)}
    try:
        plan = plan_day(preferences)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Day planning failed: {exc}") from exc
    plan_dict = plan.model_dump()
    add_day_travel_estimates(plan_dict, req.lat, req.lon)
    return plan_dict


@app.post("/api/day-plan/stream")
async def create_day_plan_stream(req: DayPlanRequest, x_client_id: str = Depends(require_client_id)):
    """Streaming counterpart to /api/day-plan, same progress-event pattern as
    /api/plan/stream."""
    ratelimit.enforce(x_client_id)
    preferences = {**req.model_dump(), "feedback_history": db.get_day_plan_feedback_history(x_client_id)}

    async def event_stream():
        try:
            async for event in plan_day_stream(preferences):
                if event.get("type") == "done":
                    add_day_travel_estimates(event["plan"], req.lat, req.lon)
                yield json.dumps(event) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/day-plan/feedback")
def submit_day_plan_feedback(req: DayPlanFeedbackRequest, x_client_id: str = Depends(require_client_id)):
    """The Day Planner's counterpart to /api/trips/{id}/feedback — but since a
    day plan is never persisted or monitored (it's shown once, immediately),
    there's no trip_id to attach this to; it's just a standalone rating tied
    to the client_id, fed into agent.py's DAY_SYSTEM_PROMPT for that
    traveler's future day plans."""
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    db.save_day_plan_feedback(x_client_id, req.city, req.mood_or_interest, req.rating, req.feedback_text)
    return {"status": "ok"}


@app.post("/api/monitor")
def monitor_plan(req: MonitorRequest):
    """On-demand check against whatever plan is currently on screen — works
    even if the trip was never saved. For actual background automation with
    no user action, see /api/trips + the scheduler in scheduler.py."""
    try:
        updates = check_for_updates(req.plan)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Monitoring failed: {exc}") from exc
    return updates


@app.post("/api/plan/choose-hotel")
def choose_hotel(req: ChooseHotelRequest):
    """Re-anchors travel-time estimates (and the hotel map pin/booking link)
    to a specific real hotel the traveler picked from HotelEstimate's
    named_options — pure deterministic recompute (see travel_estimates.py),
    no agent/Bedrock call, so it's instant and free every time the traveler
    changes their mind. The nightly price estimate itself is untouched: it
    was never a confirmed rate for any one hotel, choosing one doesn't
    change that."""
    plan = dict(req.plan)
    add_travel_estimates(plan, hotel_lat=req.hotel_lat, hotel_lon=req.hotel_lon)

    plan["map_pins"] = [p for p in plan.get("map_pins", []) if p.get("category") != "hotel"]
    plan["map_pins"].append({"label": req.hotel_name, "category": "hotel", "lat": req.hotel_lat, "lon": req.hotel_lon})

    hotel = dict(plan.get("hotel") or {})
    old_params = parse_qs(urlparse(hotel.get("booking_link", "")).query)
    checkin = old_params.get("checkin", [""])[0]
    checkout = old_params.get("checkout", [""])[0]
    group_adults = old_params.get("group_adults", ["1"])[0]
    hotel["suggested_neighborhood"] = req.hotel_name
    hotel["booking_link"] = (
        "https://www.booking.com/searchresults.html?ss="
        + quote(req.hotel_name)
        + f"&checkin={checkin}&checkout={checkout}&group_adults={group_adults}"
    )
    hotel["note"] = (
        f"You chose {req.hotel_name} — the price range shown is still a general tier estimate, "
        "not this hotel's confirmed rate. Open the link for its real current price."
    )
    plan["hotel"] = hotel

    return plan


@app.post("/api/trips")
def save_trip(req: SaveTripRequest, x_client_id: str = Depends(require_client_id), user_id: int = Depends(require_login)):
    """Lock in a plan so the background scheduler keeps watching it — no
    further user action needed for it to be monitored going forward."""
    trip_id = db.create_trip(req.plan, _alert_email(user_id, req.alerts), x_client_id)
    return {"trip_id": trip_id}


@app.get("/api/trips")
def get_trips(x_client_id: str = Depends(require_client_id)):
    trips = db.list_trips(x_client_id)
    for trip in trips:
        trip["plan"] = json.loads(trip.pop("plan_json"))
    return trips


@app.post("/api/trips/{trip_id}/archive")
def archive_trip(trip_id: int, x_client_id: str = Depends(require_client_id)):
    if not db.set_trip_status(trip_id, "archived", x_client_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    return {"status": "ok"}


@app.post("/api/trips/{trip_id}/feedback")
def submit_trip_feedback(trip_id: int, req: TripFeedbackRequest, x_client_id: str = Depends(require_client_id)):
    """The other half of the post-trip loop: real feedback, stored and later
    woven into planning prompts (see agent.py) — not fabricated
    personalization."""
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    if not db.save_trip_feedback(trip_id, req.rating, req.feedback_text, x_client_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    return {"status": "ok"}


@app.get("/api/notifications")
def get_notifications(
    unread_only: bool = True, x_client_id: str = Depends(require_client_id), user_id: int = Depends(require_login)
):
    """Scoped to the requesting account via the X-Session-Token header — see
    db.list_notifications and require_client_id above. Returns an empty
    inbox (rather than an error) when in_app_notifications_enabled is off —
    the underlying rows aren't touched, so turning it back on surfaces
    history again instead of having silently lost it."""
    user = db.get_user_by_id(user_id)
    if not user["in_app_notifications_enabled"]:
        return []
    return db.list_notifications(unread_only=unread_only, client_id=x_client_id)


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, x_client_id: str = Depends(require_client_id)):
    if not db.mark_notification_read(notification_id, x_client_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok"}


@app.post("/api/wishlist")
def create_wishlist(req: WishlistRequest, x_client_id: str = Depends(require_client_id), user_id: int = Depends(require_login)):
    """Save loose travel intent — a destination (or blank, for the agent to
    pick one once) plus a flexible date window and budget ceiling, instead of
    requiring exact dates before the agent can be useful. Gives an immediate
    outlook back so the traveler isn't waiting up to a week for the first
    scheduled check."""
    ratelimit.enforce(x_client_id)
    origin_geo = geocode_city(req.origin_city)
    if origin_geo["status"] != "success":
        raise HTTPException(status_code=400, detail=f"Couldn't find '{req.origin_city}'")
    origin = origin_geo["content"][0]["json"]

    budget_usd = _convert_budget_to_usd(req.budget, req.currency)

    reasoning = None
    destination_was_recommended = bool(not req.destination.strip())
    if not destination_was_recommended:
        dest_geo = geocode_city(req.destination)
        if dest_geo["status"] != "success":
            raise HTTPException(status_code=400, detail=f"Couldn't find '{req.destination}'")
        dest = dest_geo["content"][0]["json"]
        destination_city, destination_country = dest["name"], dest["country"]
        destination_lat, destination_lon = dest["latitude"], dest["longitude"]
    else:
        try:
            rec = recommend_destination(
                {
                    "origin_city": req.origin_city,
                    "earliest_date": req.earliest_date,
                    "latest_date": req.latest_date,
                    "trip_length_days": req.trip_length_days,
                    "budget_usd": budget_usd,
                    "interests": req.interests,
                    "feedback_history": db.get_feedback_history(x_client_id),
                }
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Destination recommendation failed: {exc}") from exc
        destination_city, destination_country = rec.destination_city, rec.destination_country
        destination_lat, destination_lon = rec.destination_lat, rec.destination_lon
        reasoning = rec.reasoning

    wishlist_id = db.create_wishlist_item(
        {
            "client_id": x_client_id,
            "email": _alert_email(user_id, req.alerts),
            "origin_city": origin["name"],
            "origin_lat": origin["latitude"],
            "origin_lon": origin["longitude"],
            "destination_city": destination_city,
            "destination_country": destination_country,
            "destination_lat": destination_lat,
            "destination_lon": destination_lon,
            "destination_was_recommended": destination_was_recommended,
            "earliest_date": req.earliest_date,
            "latest_date": req.latest_date,
            "trip_length_days": req.trip_length_days,
            "budget": req.budget,
            "currency": req.currency,
            "interests": req.interests,
        }
    )

    outlook = None
    try:
        item_row = {
            "origin_city": origin["name"],
            "origin_lat": origin["latitude"],
            "origin_lon": origin["longitude"],
            "destination_city": destination_city,
            "destination_lat": destination_lat,
            "destination_lon": destination_lon,
            "earliest_date": req.earliest_date,
            "latest_date": req.latest_date,
            "trip_length_days": req.trip_length_days,
            "currency": req.currency,
        }
        result = evaluate_wishlist_item(item_row)
        db.mark_wishlist_checked(wishlist_id)
        if result["status"] == "ok":
            db.add_notification("wishlist_outlook", result["message"], result["booking_link"], wishlist_id=wishlist_id)
            outlook = result
    except Exception:
        pass  # non-fatal — the scheduled sweep will pick this item up regardless

    return {
        "wishlist_id": wishlist_id,
        "destination_city": destination_city,
        "destination_country": destination_country,
        "destination_was_recommended": destination_was_recommended,
        "reasoning": reasoning,
        "outlook": outlook,
        "currency": req.currency,
    }


@app.get("/api/wishlist")
def get_wishlist(x_client_id: str = Depends(require_client_id)):
    return db.list_wishlist_items(x_client_id)


@app.post("/api/wishlist/{wishlist_id}/archive")
def archive_wishlist(wishlist_id: int, x_client_id: str = Depends(require_client_id)):
    if not db.set_wishlist_status(wishlist_id, "archived", x_client_id):
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return {"status": "ok"}


@app.post("/api/local-watch")
def create_local_watch(req: LocalWatchRequest, x_client_id: str = Depends(require_client_id), user_id: int = Depends(require_login)):
    """The proactive counterpart to the on-demand Day Planner: save a city +
    mood/interest once, and the scheduler keeps checking for real new local
    events going forward — no fixed trip, no dates. Unlike the wishlist
    feature, this never calls the agent at all (there's no destination to
    pick, just a fixed city), so ongoing cost is a single real API call per
    sweep, not a Bedrock call. Still rate-limited, since creation still hits
    the shared Ticketmaster daily quota."""
    ratelimit.enforce(x_client_id)
    geo = geocode_city(req.city)
    if geo["status"] != "success":
        raise HTTPException(status_code=400, detail=f"Couldn't find '{req.city}'")
    place = geo["content"][0]["json"]

    watch_id = db.create_local_watch(
        {
            "client_id": x_client_id,
            "email": _alert_email(user_id, req.alerts),
            "city": place["name"],
            "city_country": place["country"],
            "country_code": place["country_code"],
            "lat": place["latitude"],
            "lon": place["longitude"],
            "mood_or_interest": req.mood_or_interest,
            "event_type": req.event_type,
        }
    )

    # Immediate check, like the wishlist's immediate outlook, so the
    # traveler isn't waiting up to a day for the first result.
    outlook = None
    try:
        result = evaluate_local_watch(
            {
                "city": place["name"],
                "mood_or_interest": req.mood_or_interest,
                "event_type": req.event_type,
                "country_code": place["country_code"],
                "lat": place["latitude"],
                "lon": place["longitude"],
                "notified_event_urls": "[]",
            }
        )
        db.mark_local_watch_checked(watch_id, result["checked_event_urls"])
        if result["status"] == "ok":
            db.add_notification("local_watch_new_events", result["message"], result["booking_link"], local_watch_id=watch_id)
            outlook = result
    except Exception:
        pass  # non-fatal — the scheduled sweep will pick this item up regardless

    return {
        "local_watch_id": watch_id,
        "city": place["name"],
        "city_country": place["country"],
        "outlook": outlook,
    }


@app.get("/api/local-watch")
def get_local_watches(x_client_id: str = Depends(require_client_id)):
    return db.list_local_watches(x_client_id)


@app.post("/api/local-watch/{watch_id}/archive")
def archive_local_watch(watch_id: int, x_client_id: str = Depends(require_client_id)):
    if not db.set_local_watch_status(watch_id, "archived", x_client_id):
        raise HTTPException(status_code=404, detail="Watch not found")
    return {"status": "ok"}


@app.post("/api/monitor/sweep-now")
def trigger_sweep_now():
    """Demo/dev helper: run the same sweep the scheduler runs automatically,
    without waiting for the next scheduled interval."""
    return scheduler.run_monitoring_sweep()


FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
