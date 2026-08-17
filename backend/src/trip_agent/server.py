from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, scheduler
from .agent import plan_trip
from .monitor import check_for_updates


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


class PlanRequest(BaseModel):
    origin_city: str
    destination: str = ""
    start_date: str
    end_date: str
    travelers: int = 1
    budget_usd: float
    interests: str = "general sightseeing"
    transportation: str = "flight"
    accommodation: str = "mid-range hotel"
    dietary_needs: str = "none"


class MonitorRequest(BaseModel):
    plan: dict


class SaveTripRequest(BaseModel):
    plan: dict
    email: str | None = None


@app.post("/api/plan")
def create_plan(req: PlanRequest):
    try:
        plan = plan_trip(req.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planning failed: {exc}") from exc
    return plan.model_dump()


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
def save_trip(req: SaveTripRequest):
    """Lock in a plan so the background scheduler keeps watching it — no
    further user action needed for it to be monitored going forward."""
    trip_id = db.create_trip(req.plan, req.email)
    return {"trip_id": trip_id}


@app.get("/api/notifications")
def get_notifications(unread_only: bool = True):
    return db.list_notifications(unread_only=unread_only)


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int):
    db.mark_notification_read(notification_id)
    return {"status": "ok"}


@app.post("/api/monitor/sweep-now")
def trigger_sweep_now():
    """Demo/dev helper: run the same sweep the scheduler runs automatically,
    without waiting for the next scheduled interval."""
    return scheduler.run_monitoring_sweep()


FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
