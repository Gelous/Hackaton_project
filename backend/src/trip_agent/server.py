import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, ratelimit, scheduler
from .agent import plan_day, plan_day_stream, plan_trip, plan_trip_stream, recommend_destination
from .currency import SUPPORTED_CURRENCIES, CurrencyUnavailableError, convert
from .local_watch_monitor import evaluate_local_watch
from .monitor import check_for_updates
from .places_search import search_cities
from .tools.geocode import geocode_city
from .wishlist_monitor import evaluate_wishlist_item


def verified_client_id(x_client_id: str | None = Header(default=None)) -> str | None:
    """Replaces a bare Header(default=None) everywhere a client_id is used
    for scoping — verifies the HMAC signature auth.issue_client_id() attaches
    so a request can no longer just set the header to any value and read or
    modify a different visitor's trips/wishlist/notifications. None is still
    a valid return (no header sent at all, e.g. a first-ever visit before the
    frontend has called /api/client-id); an invalid/tampered id is rejected
    outright rather than silently treated as anonymous, since that would just
    reopen the same hole for a malformed-on-purpose header."""
    if x_client_id is None:
        return None
    verified = auth.verify_client_id(x_client_id)
    if verified is None:
        raise HTTPException(status_code=401, detail="Invalid client id — clear local storage and reload")
    return verified


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
    accommodation: str = "mid-range hotel"
    dietary_needs: str = "none"


class MonitorRequest(BaseModel):
    plan: dict


class SaveTripRequest(BaseModel):
    plan: dict
    email: str | None = None


class TripFeedbackRequest(BaseModel):
    rating: int
    feedback_text: str | None = None


class DayPlanRequest(BaseModel):
    city: str
    date: str
    mood_or_interest: str = "general sightseeing"
    dietary_needs: str = "none"


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
    email: str | None = None


class LocalWatchRequest(BaseModel):
    city: str
    mood_or_interest: str = "general sightseeing"
    email: str | None = None


@app.get("/api/cities")
def get_city_suggestions(q: str = ""):
    """Worldwide city autocomplete for the starting city / destination fields."""
    if len(q.strip()) < 2:
        return []
    return search_cities(q.strip())


@app.get("/api/currencies")
def get_currencies():
    return SUPPORTED_CURRENCIES


@app.post("/api/client-id")
def issue_client_id():
    """Called once by a fresh browser (no client_id in localStorage yet) to
    get a signed id it can then reuse on every later request — see auth.py.
    A plain POST, no body: there's nothing to authenticate against yet, this
    is the very first thing that establishes an identity at all."""
    return {"client_id": auth.issue_client_id()}


@app.post("/api/plan")
def create_plan(req: PlanRequest, request: Request, x_client_id: str | None = Depends(verified_client_id)):
    ratelimit.enforce(x_client_id or request.client.host)
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
    try:
        _localize_plan(plan_dict, req.budget, req.currency)
    except CurrencyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return plan_dict


@app.post("/api/plan/stream")
async def create_plan_stream(req: PlanRequest, request: Request, x_client_id: str | None = Depends(verified_client_id)):
    """Same planning flow as /api/plan, but streams newline-delimited JSON
    progress events (a real trace of which tool the agent is currently
    calling) while it works, ending with a {"type": "done", "plan": ...}
    line. Used by the frontend instead of the plain /api/plan endpoint so the
    UI can show live progress on the 20-40s plan generation."""
    ratelimit.enforce(x_client_id or request.client.host)
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
                    _localize_plan(event["plan"], req.budget, req.currency)
                yield json.dumps(event) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/day-plan")
def create_day_plan(req: DayPlanRequest, request: Request, x_client_id: str | None = Depends(verified_client_id)):
    """No fixed trip, no travel — a same-day plan for one city, driven by a
    mood/interest instead of a full preferences form. No budget/currency
    involved, so unlike /api/plan there's no localization step needed."""
    ratelimit.enforce(x_client_id or request.client.host)
    preferences = {**req.model_dump(), "feedback_history": db.get_day_plan_feedback_history(x_client_id)}
    try:
        plan = plan_day(preferences)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Day planning failed: {exc}") from exc
    return plan.model_dump()


@app.post("/api/day-plan/stream")
async def create_day_plan_stream(req: DayPlanRequest, request: Request, x_client_id: str | None = Depends(verified_client_id)):
    """Streaming counterpart to /api/day-plan, same progress-event pattern as
    /api/plan/stream."""
    ratelimit.enforce(x_client_id or request.client.host)
    preferences = {**req.model_dump(), "feedback_history": db.get_day_plan_feedback_history(x_client_id)}

    async def event_stream():
        try:
            async for event in plan_day_stream(preferences):
                yield json.dumps(event) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/day-plan/feedback")
def submit_day_plan_feedback(req: DayPlanFeedbackRequest, x_client_id: str | None = Depends(verified_client_id)):
    """The Day Planner's counterpart to /api/trips/{id}/feedback — but since a
    day plan is never persisted or monitored (it's shown once, immediately),
    there's no trip_id to attach this to; it's just a standalone rating tied
    to the client_id, fed into agent.py's DAY_SYSTEM_PROMPT for that
    traveler's future day plans."""
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    if not x_client_id:
        raise HTTPException(status_code=401, detail="A client id is required to save feedback")
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


@app.post("/api/trips")
def save_trip(req: SaveTripRequest, x_client_id: str | None = Depends(verified_client_id)):
    """Lock in a plan so the background scheduler keeps watching it — no
    further user action needed for it to be monitored going forward."""
    trip_id = db.create_trip(req.plan, req.email, x_client_id)
    return {"trip_id": trip_id}


@app.get("/api/trips")
def get_trips(x_client_id: str | None = Depends(verified_client_id)):
    trips = db.list_trips(x_client_id)
    for trip in trips:
        trip["plan"] = json.loads(trip.pop("plan_json"))
    return trips


@app.post("/api/trips/{trip_id}/archive")
def archive_trip(trip_id: int, x_client_id: str | None = Depends(verified_client_id)):
    if not x_client_id or not db.set_trip_status(trip_id, "archived", x_client_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    return {"status": "ok"}


@app.post("/api/trips/{trip_id}/feedback")
def submit_trip_feedback(trip_id: int, req: TripFeedbackRequest, x_client_id: str | None = Depends(verified_client_id)):
    """The other half of the post-trip loop: real feedback, stored and later
    woven into planning prompts (see agent.py) — not fabricated
    personalization."""
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    if not x_client_id or not db.save_trip_feedback(trip_id, req.rating, req.feedback_text, x_client_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    return {"status": "ok"}


@app.get("/api/notifications")
def get_notifications(unread_only: bool = True, x_client_id: str | None = Depends(verified_client_id)):
    """Scoped to the requesting browser via the X-Client-Id header — see
    db.list_notifications for why (no accounts, just per-browser scoping)."""
    return db.list_notifications(unread_only=unread_only, client_id=x_client_id)


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, x_client_id: str | None = Depends(verified_client_id)):
    if not x_client_id or not db.mark_notification_read(notification_id, x_client_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok"}


@app.post("/api/wishlist")
def create_wishlist(req: WishlistRequest, request: Request, x_client_id: str | None = Depends(verified_client_id)):
    """Save loose travel intent — a destination (or blank, for the agent to
    pick one once) plus a flexible date window and budget ceiling, instead of
    requiring exact dates before the agent can be useful. Gives an immediate
    outlook back so the traveler isn't waiting up to a week for the first
    scheduled check."""
    ratelimit.enforce(x_client_id or request.client.host)
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
            "email": req.email,
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
def get_wishlist(x_client_id: str | None = Depends(verified_client_id)):
    return db.list_wishlist_items(x_client_id)


@app.post("/api/wishlist/{wishlist_id}/archive")
def archive_wishlist(wishlist_id: int, x_client_id: str | None = Depends(verified_client_id)):
    if not x_client_id or not db.set_wishlist_status(wishlist_id, "archived", x_client_id):
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return {"status": "ok"}


@app.post("/api/local-watch")
def create_local_watch(req: LocalWatchRequest, request: Request, x_client_id: str | None = Depends(verified_client_id)):
    """The proactive counterpart to the on-demand Day Planner: save a city +
    mood/interest once, and the scheduler keeps checking for real new local
    events going forward — no fixed trip, no dates. Unlike the wishlist
    feature, this never calls the agent at all (there's no destination to
    pick, just a fixed city), so ongoing cost is a single real API call per
    sweep, not a Bedrock call. Still rate-limited, since creation still hits
    the shared Ticketmaster daily quota."""
    ratelimit.enforce(x_client_id or request.client.host)
    geo = geocode_city(req.city)
    if geo["status"] != "success":
        raise HTTPException(status_code=400, detail=f"Couldn't find '{req.city}'")
    place = geo["content"][0]["json"]

    watch_id = db.create_local_watch(
        {
            "client_id": x_client_id,
            "email": req.email,
            "city": place["name"],
            "city_country": place["country"],
            "lat": place["latitude"],
            "lon": place["longitude"],
            "mood_or_interest": req.mood_or_interest,
        }
    )

    # Immediate check, like the wishlist's immediate outlook, so the
    # traveler isn't waiting up to a day for the first result.
    outlook = None
    try:
        result = evaluate_local_watch(
            {"city": place["name"], "mood_or_interest": req.mood_or_interest, "notified_event_urls": "[]"}
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
def get_local_watches(x_client_id: str | None = Depends(verified_client_id)):
    return db.list_local_watches(x_client_id)


@app.post("/api/local-watch/{watch_id}/archive")
def archive_local_watch(watch_id: int, x_client_id: str | None = Depends(verified_client_id)):
    if not x_client_id or not db.set_local_watch_status(watch_id, "archived", x_client_id):
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
