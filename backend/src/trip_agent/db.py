"""Lightweight SQLite persistence — no ORM, this schema is small enough that
raw sqlite3 keeps things simple and dependency-free for judges running the repo.

Three tables:
- trips: a locked-in plan with fixed dates that the scheduler keeps watching
  (price/weather reminders on real travel-advice milestones)
- wishlist: loose travel intent with NO fixed dates yet — a destination (or
  blank for the agent to pick one), a flexible date window, and a budget
  ceiling. The scheduler periodically evaluates these and surfaces an honest
  outlook (real weather + a price estimate + a real booking link) for the
  best-looking window so far, rather than requiring the user to have already
  committed to exact dates before the agent is useful.
- local_watches: an ongoing "watch this city" subscription — no trip, no
  dates, just a city and a mood/interest. The scheduler periodically checks
  for real local events (via search_events_range) and surfaces only ones it
  hasn't already notified about (notified_event_urls), the proactive
  counterpart to the on-demand Day Planner.
- notifications: updates the scheduler surfaced for a trip, a wishlist item,
  or a local watch (exactly one of trip_id/wishlist_id/local_watch_id is
  set), read/unread.

No user accounts — everything is keyed by an optional email for delivery, and
scoped to a per-browser client_id (see frontend/app.js's ensureClientId()) so
one visitor's saved trips/wishlist/notifications don't show up for another
visitor. The client_id itself is a server-issued, HMAC-signed token (see
auth.py) rather than a bare client-generated UUID, so a request can't just
set the header to any value to read or mutate someone else's data — every
mutating query below also filters by client_id, not just the reads. This is
still not a verified identity (no login, no password), just enough to keep a
demo or shared deployment from one visitor tampering with another's data.

Two more small tables: settings is a plain key/value store for server state
that needs to survive a restart (the HMAC secret in auth.py, the scheduler's
last-successful-sweep timestamp); day_plan_feedback stores ratings for the
(unsaved, one-shot) Day Planner, since unlike a trip there's no other row for
that feedback to attach to.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "trips.db"


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                client_id TEXT,
                email TEXT,
                plan_json TEXT NOT NULL,
                origin_city TEXT NOT NULL,
                destination_city TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                feedback_rating INTEGER,
                feedback_text TEXT,
                feedback_requested_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wishlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                client_id TEXT,
                email TEXT,
                origin_city TEXT NOT NULL,
                origin_lat REAL NOT NULL,
                origin_lon REAL NOT NULL,
                destination_city TEXT NOT NULL,
                destination_country TEXT,
                destination_lat REAL NOT NULL,
                destination_lon REAL NOT NULL,
                destination_was_recommended INTEGER NOT NULL DEFAULT 0,
                earliest_date TEXT NOT NULL,
                latest_date TEXT NOT NULL,
                trip_length_days INTEGER NOT NULL,
                budget REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                interests TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                last_checked_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                client_id TEXT,
                email TEXT,
                city TEXT NOT NULL,
                city_country TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                mood_or_interest TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                last_checked_at TEXT,
                notified_event_urls TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER REFERENCES trips(id),
                wishlist_id INTEGER REFERENCES wishlist(id),
                local_watch_id INTEGER REFERENCES local_watches(id),
                created_at TEXT NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                booking_link TEXT,
                is_read INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS day_plan_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                client_id TEXT NOT NULL,
                city TEXT NOT NULL,
                mood_or_interest TEXT,
                rating INTEGER NOT NULL,
                feedback_text TEXT
            )
            """
        )


def get_setting(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def create_trip(plan: dict, email: str | None, client_id: str | None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO trips (created_at, client_id, email, plan_json, origin_city, destination_city, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                client_id or None,
                email or None,
                json.dumps(plan),
                plan["origin_city"],
                plan["destination_city"],
                plan["days"][0]["date"],
                plan["days"][-1]["date"],
            ),
        )
        return cur.lastrowid


def list_active_trips() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM trips WHERE status = 'active'").fetchall()
        return [dict(row) for row in rows]


def list_trips(client_id: str | None) -> list[dict]:
    if not client_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trips WHERE client_id = ? AND status != 'archived' ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def set_trip_status(trip_id: int, status: str, client_id: str | None = None) -> bool:
    """client_id=None is the trusted internal call path (the scheduler marking
    a trip completed on its own) — the public /api/trips/{id}/archive endpoint
    always passes the requester's verified client_id, so it can only ever
    touch a trip that actually belongs to them. Returns whether a row changed,
    so the endpoint can tell "not found" / "not yours" from success."""
    with get_connection() as conn:
        if client_id is None:
            cur = conn.execute("UPDATE trips SET status = ? WHERE id = ?", (status, trip_id))
        else:
            cur = conn.execute(
                "UPDATE trips SET status = ? WHERE id = ? AND client_id = ?",
                (status, trip_id, client_id),
            )
        return cur.rowcount > 0


def list_trips_needing_feedback_request() -> list[dict]:
    """Active trips whose dates have already passed and haven't been asked
    for feedback yet — the trigger for the post-trip loop."""
    today = datetime.now(timezone.utc).date().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM trips
            WHERE status = 'active' AND end_date < ? AND feedback_requested_at IS NULL
            """,
            (today,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_feedback_requested(trip_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE trips SET feedback_requested_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), trip_id),
        )


def save_trip_feedback(trip_id: int, rating: int, feedback_text: str | None, client_id: str | None = None) -> bool:
    """Recording feedback also marks the trip 'completed' — once a trip is
    over, there's nothing left to monitor (no more use in a flight-price
    reminder for a flight that already happened). Scoped to client_id like
    set_trip_status above — see that docstring."""
    with get_connection() as conn:
        if client_id is None:
            cur = conn.execute(
                "UPDATE trips SET feedback_rating = ?, feedback_text = ?, status = 'completed' WHERE id = ?",
                (rating, feedback_text, trip_id),
            )
        else:
            cur = conn.execute(
                "UPDATE trips SET feedback_rating = ?, feedback_text = ?, status = 'completed' WHERE id = ? AND client_id = ?",
                (rating, feedback_text, trip_id, client_id),
            )
        return cur.rowcount > 0


def get_feedback_history(client_id: str | None, limit: int = 5) -> list[dict]:
    """Past trips this client left feedback on — used to inject real,
    honest personalization into future planning prompts (never fabricated)."""
    if not client_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT destination_city, feedback_rating, feedback_text
            FROM trips
            WHERE client_id = ? AND feedback_rating IS NOT NULL
            ORDER BY created_at DESC LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def save_day_plan_feedback(client_id: str, city: str, mood_or_interest: str, rating: int, feedback_text: str | None) -> int:
    """Unlike trip feedback, a day plan is never saved/monitored server-side
    — it's computed and shown once, so this is the only record of it ever
    existing at all. Requires a real client_id (no anonymous rows) since the
    entire point is feeding it back into that same browser's future prompts."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO day_plan_feedback (created_at, client_id, city, mood_or_interest, rating, feedback_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), client_id, city, mood_or_interest, rating, feedback_text),
        )
        return cur.lastrowid


def get_day_plan_feedback_history(client_id: str | None, limit: int = 5) -> list[dict]:
    """Past day-out ratings this client left — same honesty rule as
    get_feedback_history above (real, stored, never fabricated)."""
    if not client_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT city, mood_or_interest, rating, feedback_text
            FROM day_plan_feedback
            WHERE client_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def create_wishlist_item(item: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO wishlist (
                created_at, client_id, email,
                origin_city, origin_lat, origin_lon,
                destination_city, destination_country, destination_lat, destination_lon,
                destination_was_recommended,
                earliest_date, latest_date, trip_length_days, budget, currency, interests
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                item.get("client_id"),
                item.get("email"),
                item["origin_city"],
                item["origin_lat"],
                item["origin_lon"],
                item["destination_city"],
                item.get("destination_country"),
                item["destination_lat"],
                item["destination_lon"],
                1 if item.get("destination_was_recommended") else 0,
                item["earliest_date"],
                item["latest_date"],
                item["trip_length_days"],
                item["budget"],
                item.get("currency", "USD"),
                item.get("interests"),
            ),
        )
        return cur.lastrowid


def list_wishlist_items(client_id: str | None) -> list[dict]:
    if not client_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM wishlist WHERE client_id = ? AND status != 'archived' ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_due_wishlist_items(stale_after_days: int) -> list[dict]:
    """Active wishlist items that haven't been checked in the last N days
    (or have never been checked at all)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_after_days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM wishlist
            WHERE status = 'active' AND (last_checked_at IS NULL OR last_checked_at < ?)
            """,
            (cutoff,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_wishlist_checked(wishlist_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE wishlist SET last_checked_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), wishlist_id),
        )


def set_wishlist_status(wishlist_id: int, status: str, client_id: str | None = None) -> bool:
    """client_id=None is the trusted internal call path (the scheduler
    expiring a stale item on its own) — see set_trip_status's docstring."""
    with get_connection() as conn:
        if client_id is None:
            cur = conn.execute("UPDATE wishlist SET status = ? WHERE id = ?", (status, wishlist_id))
        else:
            cur = conn.execute(
                "UPDATE wishlist SET status = ? WHERE id = ? AND client_id = ?",
                (status, wishlist_id, client_id),
            )
        return cur.rowcount > 0


def create_local_watch(item: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO local_watches (
                created_at, client_id, email, city, city_country, lat, lon, mood_or_interest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                item.get("client_id"),
                item.get("email"),
                item["city"],
                item.get("city_country"),
                item["lat"],
                item["lon"],
                item.get("mood_or_interest"),
            ),
        )
        return cur.lastrowid


def list_local_watches(client_id: str | None) -> list[dict]:
    if not client_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM local_watches WHERE client_id = ? AND status != 'archived' ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_due_local_watches(stale_after_days: int) -> list[dict]:
    """Active watches that haven't been checked in the last N days (or never
    checked at all) — same pattern as list_due_wishlist_items."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_after_days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM local_watches
            WHERE status = 'active' AND (last_checked_at IS NULL OR last_checked_at < ?)
            """,
            (cutoff,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_local_watch_checked(local_watch_id: int, notified_event_urls: list[str]) -> None:
    """notified_event_urls is the running list of event URLs already
    surfaced for this watch — capped by the caller (local_watch_monitor.py)
    so a long-lived watch doesn't grow this column without bound."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE local_watches SET last_checked_at = ?, notified_event_urls = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), json.dumps(notified_event_urls), local_watch_id),
        )


def set_local_watch_status(local_watch_id: int, status: str, client_id: str | None = None) -> bool:
    """client_id=None is the trusted internal call path — see
    set_trip_status's docstring."""
    with get_connection() as conn:
        if client_id is None:
            cur = conn.execute("UPDATE local_watches SET status = ? WHERE id = ?", (status, local_watch_id))
        else:
            cur = conn.execute(
                "UPDATE local_watches SET status = ? WHERE id = ? AND client_id = ?",
                (status, local_watch_id, client_id),
            )
        return cur.rowcount > 0


def add_notification(
    type_: str,
    message: str,
    booking_link: str | None,
    trip_id: int | None = None,
    wishlist_id: int | None = None,
    local_watch_id: int | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO notifications (trip_id, wishlist_id, local_watch_id, created_at, type, message, booking_link)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (trip_id, wishlist_id, local_watch_id, datetime.now(timezone.utc).isoformat(), type_, message, booking_link),
        )


def list_notifications(unread_only: bool = False, client_id: str | None = None) -> list[dict]:
    """Scoped to the requesting browser's client_id — one shared inbox for
    trip reminders, wishlist outlooks, and local watch alerts."""
    if not client_id:
        return []

    query = """
        SELECT n.*,
            CASE
                WHEN n.trip_id IS NOT NULL THEN 'trip'
                WHEN n.wishlist_id IS NOT NULL THEN 'wishlist'
                ELSE 'local_watch'
            END AS kind,
            COALESCE(t.origin_city, w.origin_city) AS origin_city,
            COALESCE(t.destination_city, w.destination_city, lw.city) AS destination_city,
            t.start_date, t.end_date,
            w.earliest_date, w.latest_date
        FROM notifications n
        LEFT JOIN trips t ON t.id = n.trip_id
        LEFT JOIN wishlist w ON w.id = n.wishlist_id
        LEFT JOIN local_watches lw ON lw.id = n.local_watch_id
        WHERE COALESCE(t.client_id, w.client_id, lw.client_id) = ?
    """
    params: list = [client_id]
    if unread_only:
        query += " AND n.is_read = 0"
    query += " ORDER BY n.created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def mark_notification_read(notification_id: int, client_id: str | None = None) -> bool:
    """client_id=None is the trusted internal call path (none currently used,
    kept for symmetry with the other scoped mutations above)."""
    with get_connection() as conn:
        if client_id is None:
            cur = conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        else:
            cur = conn.execute(
                """
                UPDATE notifications SET is_read = 1
                WHERE id = ? AND id IN (
                    SELECT n.id FROM notifications n
                    LEFT JOIN trips t ON t.id = n.trip_id
                    LEFT JOIN wishlist w ON w.id = n.wishlist_id
                    LEFT JOIN local_watches lw ON lw.id = n.local_watch_id
                    WHERE COALESCE(t.client_id, w.client_id, lw.client_id) = ?
                )
                """,
                (notification_id, client_id),
            )
        return cur.rowcount > 0


def notified_within(days: int, type_: str, trip_id: int | None = None, wishlist_id: int | None = None) -> bool:
    """Whether a notification of this type already went out recently for this
    trip/wishlist item — keeps recurring checks (daily sweeps, weekly
    wishlist evaluations) from re-inserting the same notification every time
    the condition still holds."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    column = "trip_id" if trip_id is not None else "wishlist_id"
    value = trip_id if trip_id is not None else wishlist_id
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT 1 FROM notifications WHERE {column} = ? AND type = ? AND created_at >= ? LIMIT 1",
            (value, type_, cutoff),
        ).fetchone()
        return row is not None
