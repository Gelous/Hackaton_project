"""Shared fixtures. The main one — temp_db — points db.py at a throwaway
SQLite file per test instead of the real dev database, so running the suite
never touches (or depends on) backend/data/trips.db.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from trip_agent import auth, db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_trips.db")
    # auth.py caches its HMAC secret in a module-level variable once read —
    # without resetting it here, a secret cached from an earlier test (a
    # different temp db) would leak in and sign/verify against the wrong
    # database's stored secret.
    monkeypatch.setattr(auth, "_cached_secret", None)
    db.init_db()
    return db
