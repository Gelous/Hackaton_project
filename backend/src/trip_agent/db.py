"""Lightweight SQLite persistence — no ORM, this schema is small enough that
raw sqlite3 keeps things simple and dependency-free for judges running the repo.

Two tables:
- trips: a locked-in plan the background scheduler should keep watching
- notifications: updates the scheduler surfaced, read/unread per notification

No user accounts — trips are keyed by an optional email for delivery, and the
notification inbox is global. A real product would scope this per signed-in
user; out of scope for this build.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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
                email TEXT,
                plan_json TEXT NOT NULL,
                origin_city TEXT NOT NULL,
                destination_city TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL REFERENCES trips(id),
                created_at TEXT NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                booking_link TEXT,
                is_read INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def create_trip(plan: dict, email: str | None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO trips (created_at, email, plan_json, origin_city, destination_city, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
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


def add_notification(trip_id: int, type_: str, message: str, booking_link: str | None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO notifications (trip_id, created_at, type, message, booking_link)
            VALUES (?, ?, ?, ?, ?)
            """,
            (trip_id, datetime.now(timezone.utc).isoformat(), type_, message, booking_link),
        )


def list_notifications(unread_only: bool = False) -> list[dict]:
    query = """
        SELECT n.*, t.origin_city, t.destination_city, t.start_date, t.end_date
        FROM notifications n
        JOIN trips t ON t.id = n.trip_id
    """
    if unread_only:
        query += " WHERE n.is_read = 0"
    query += " ORDER BY n.created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]


def mark_notification_read(notification_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
