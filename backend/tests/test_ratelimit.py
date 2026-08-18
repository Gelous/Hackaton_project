"""ratelimit.py: the sliding-window limiter guarding the Bedrock-calling
endpoints against a scripted client (or a runaway auto-replan loop) racking
up unlimited real model-inference calls.

_request_log is module-level state that persists across tests in the same
process, so each test uses its own unique key to stay isolated.
"""

import uuid

import pytest
from fastapi import HTTPException

from trip_agent import ratelimit


def unique_key() -> str:
    return f"test-{uuid.uuid4().hex}"


def test_allows_up_to_the_limit():
    key = unique_key()
    for _ in range(ratelimit.MAX_REQUESTS_PER_WINDOW):
        ratelimit.enforce(key)  # should not raise


def test_blocks_once_over_the_limit():
    key = unique_key()
    for _ in range(ratelimit.MAX_REQUESTS_PER_WINDOW):
        ratelimit.enforce(key)
    with pytest.raises(HTTPException) as exc_info:
        ratelimit.enforce(key)
    assert exc_info.value.status_code == 429


def test_keys_are_isolated_from_each_other():
    key_a = unique_key()
    key_b = unique_key()
    for _ in range(ratelimit.MAX_REQUESTS_PER_WINDOW):
        ratelimit.enforce(key_a)
    # key_a is now exhausted, but a different key should be unaffected.
    ratelimit.enforce(key_b)  # should not raise


def test_old_requests_fall_out_of_the_window(monkeypatch):
    key = unique_key()
    fake_now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: fake_now[0])

    for _ in range(ratelimit.MAX_REQUESTS_PER_WINDOW):
        ratelimit.enforce(key)

    # Still inside the window — should still be blocked.
    with pytest.raises(HTTPException):
        ratelimit.enforce(key)

    # Advance past the window — the old entries should have aged out.
    fake_now[0] += ratelimit.WINDOW_SECONDS + 1
    ratelimit.enforce(key)  # should not raise
