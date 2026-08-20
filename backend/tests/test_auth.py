"""auth.py: real account passwords and HMAC-signed login sessions (see
auth.py's module docstring — this used to also cover a signed anonymous
client_id, removed once login became mandatory and it lost every caller)."""

from trip_agent import auth


def test_secret_persists_across_calls(temp_db, monkeypatch):
    # Simulate a fresh process (no cached secret in memory) reusing the same
    # underlying db — this is what actually happens on a server restart, and
    # is why the secret has to be persisted rather than regenerated per run.
    token = auth.issue_session_token(7)
    monkeypatch.setattr(auth, "_cached_secret", None)
    assert auth.verify_session_token(token) == 7


# ---- Account passwords ----


def test_correct_password_verifies(temp_db):
    password_hash, salt = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", password_hash, salt) is True


def test_wrong_password_is_rejected(temp_db):
    password_hash, salt = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("wrong password", password_hash, salt) is False


def test_password_is_never_stored_in_plain_text(temp_db):
    password_hash, salt = auth.hash_password("correct horse battery staple")
    assert "correct horse battery staple" not in password_hash
    assert "correct horse battery staple" not in salt


def test_same_password_gets_a_different_hash_each_time(temp_db):
    # A random per-user salt means two users with the identical password
    # never end up with the identical stored hash — this is what stops a
    # leaked DB from being searched against a rainbow table of common
    # passwords across every account at once.
    hash_a, salt_a = auth.hash_password("hunter2")
    hash_b, salt_b = auth.hash_password("hunter2")
    assert hash_a != hash_b
    assert salt_a != salt_b


# ---- Account sessions ----


def test_issued_session_token_verifies_to_the_right_user_id(temp_db):
    token = auth.issue_session_token(42)
    assert auth.verify_session_token(token) == 42


def test_tampered_session_token_is_rejected(temp_db):
    token = auth.issue_session_token(42)
    raw, _, signature = token.partition(".")
    flipped_char = "0" if signature[-1] != "0" else "1"
    tampered = f"{raw}.{signature[:-1]}{flipped_char}"
    assert auth.verify_session_token(tampered) is None


def test_forged_session_token_is_rejected(temp_db):
    assert auth.verify_session_token("attacker-just-made-this-up") is None
    assert auth.verify_session_token("") is None


def test_a_valid_signature_for_a_different_user_id_does_not_transfer(temp_db):
    token_a = auth.issue_session_token(1)
    token_b = auth.issue_session_token(2)
    raw_a, _, _ = token_a.partition(".")
    _, _, signature_b = token_b.partition(".")
    assert auth.verify_session_token(f"{raw_a}.{signature_b}") is None
