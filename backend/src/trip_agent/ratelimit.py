"""In-memory rate limit for the endpoints that trigger a real Bedrock call.

The frontend's auto-replan-on-edit only debounces client-side (900ms) — a
scripted client, a stuck retry loop, or just someone hammering the form can
still fire unlimited real model-inference calls with no server-side ceiling.
This is a simple sliding-window limiter, in-memory since this is a
single-process app (same tradeoff already made for currency.py's rate cache):
it resets on restart and isn't shared across multiple worker processes, which
is fine for a hackathon deployment but wouldn't be for a scaled one.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 6

_request_log: dict[str, deque] = defaultdict(deque)


def enforce(key: str) -> None:
    """Raises 429 if `key` (a client_id, or an IP address as a fallback for
    requests with no client_id) has made too many planning requests in the
    current window."""
    now = time.monotonic()
    log = _request_log[key]
    while log and now - log[0] > WINDOW_SECONDS:
        log.popleft()
    if len(log) >= MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail="Too many planning requests in a short time — wait a moment and try again.",
        )
    log.append(now)
