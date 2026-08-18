"""Server-issued, signed per-browser identity.

There are no user accounts in this app — see db.py's module docstring — but
the original implementation let the browser invent its own client_id
(crypto.randomUUID()) and send it as a plain header, which the server trusted
outright. That meant anyone could set X-Client-Id to any value and read or
modify a different visitor's trips, wishlist, or notifications; it wasn't
scoping, it was an honor system.

This replaces that with a server-issued token the client can't forge: the
server generates the id and signs it with a secret only the server has
(HMAC-SHA256), and every request that includes a client_id has that signature
verified before the id is trusted for anything. A client can still choose to
not send one (day-plan and city search don't need one), but it can no longer
claim to be someone else's browser.
"""

import hashlib
import hmac
import secrets
import uuid

from . import db

_SETTING_KEY = "client_id_secret"
_cached_secret: str | None = None


def _get_secret() -> str:
    """Persisted in the same SQLite db as everything else (see db.py's
    settings table) so it survives a restart — a secret that changed on every
    restart would invalidate every visitor's stored client_id constantly."""
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret
    secret = db.get_setting(_SETTING_KEY)
    if secret is None:
        secret = secrets.token_hex(32)
        db.set_setting(_SETTING_KEY, secret)
    _cached_secret = secret
    return secret


def _sign(raw_id: str) -> str:
    return hmac.new(_get_secret().encode(), raw_id.encode(), hashlib.sha256).hexdigest()


def issue_client_id() -> str:
    """A fresh id in the form '<uuid>.<signature>'. The uuid half is what
    actually gets stored as client_id in the database; the signature half
    only exists so the server can trust it came from here."""
    raw_id = uuid.uuid4().hex
    return f"{raw_id}.{_sign(raw_id)}"


def verify_client_id(token: str) -> str | None:
    """Returns the raw id if the signature checks out, else None. Uses a
    constant-time comparison so this can't be used as a timing oracle to
    forge a valid signature byte-by-byte."""
    raw_id, _, signature = token.partition(".")
    if not raw_id or not signature:
        return None
    if not hmac.compare_digest(signature, _sign(raw_id)):
        return None
    return raw_id
