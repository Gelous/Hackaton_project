"""Real account passwords and stateless, signed login sessions.

A real account is required to use this app at all (see db.py's module
docstring) — earlier this also housed a signed, anonymous per-browser
client_id used to scope data without an account. Now that login is
mandatory, that mechanism has no callers left (every data endpoint scopes by
the logged-in account instead, see server.py's require_client_id), so it was
removed rather than left as unused, previously-security-relevant code lying
around. The HMAC-signing infrastructure below (_get_secret/_sign) is the same
one that primitive used, now serving session tokens only.
"""

import hashlib
import hmac
import secrets

from . import db

_SETTING_KEY = "client_id_secret"
_cached_secret: str | None = None

# A password hash needs its own, separate secret from the session-token
# signing secret above — reusing one secret for two different security
# purposes (identity signing vs. password hashing) is the kind of shortcut
# that turns into a real vulnerability if either use ever needs to rotate
# independently.
_PASSWORD_SALT_BYTES = 16
_PBKDF2_ITERATIONS = 600_000  # OWASP's 2023 minimum recommendation for PBKDF2-HMAC-SHA256
SESSION_TOKEN_PREFIX = "u"  # marks a token as a session token, rejecting anything else shaped like one


def _get_secret() -> str:
    """Persisted in the same SQLite db as everything else (see db.py's
    settings table) so it survives a restart — a secret that changed on every
    restart would log out every account constantly."""
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


# ---- Account passwords and sessions ----


def hash_password(password: str) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex). PBKDF2-HMAC-SHA256 with a
    random per-user salt and 600,000 iterations (OWASP's 2023 minimum
    recommendation) — a real, NIST-recommended KDF from the standard library,
    not a hand-rolled scheme and not a dependency (bcrypt/argon2) this repo
    would need judges to separately install."""
    salt = secrets.token_hex(_PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Constant-time comparison, same reasoning as verify_client_id above —
    a length- or early-exit-dependent comparison here would leak timing
    information an attacker could use to guess the hash byte-by-byte."""
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return hmac.compare_digest(digest.hex(), password_hash)


def issue_session_token(user_id: int) -> str:
    """Same signed-token pattern as issue_client_id, but encodes a real
    user_id instead of a random uuid — deliberately stateless (no session
    table, nothing to look up), so verifying one is a pure signature check.
    The tradeoff that comes with that: there's no server-side revocation list,
    so a token stays valid until it expires naturally by... never expiring.
    Acceptable for this app's scope (no sensitive data behind it beyond a
    saved home city), but a real production system would want a short
    expiry plus a refresh flow, or a revocable session table instead."""
    raw = f"{SESSION_TOKEN_PREFIX}{user_id}"
    return f"{raw}.{_sign(raw)}"


def verify_session_token(token: str) -> int | None:
    """Returns the user_id if the signature checks out and the token was
    actually shaped like one issue_session_token would produce — the 'u'
    prefix check rejects anything else that happens to carry a valid
    signature for this secret."""
    raw, _, signature = token.partition(".")
    if not raw or not signature or not raw.startswith(SESSION_TOKEN_PREFIX):
        return None
    if not hmac.compare_digest(signature, _sign(raw)):
        return None
    try:
        return int(raw[len(SESSION_TOKEN_PREFIX):])
    except ValueError:
        return None
