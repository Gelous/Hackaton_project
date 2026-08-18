"""auth.py: the HMAC-signed client_id that replaced a bare client-generated
UUID (see auth.py's module docstring for the vulnerability this closes)."""

from trip_agent import auth


def test_issued_id_verifies(temp_db):
    token = auth.issue_client_id()
    assert auth.verify_client_id(token) is not None


def test_verify_returns_the_raw_id(temp_db):
    token = auth.issue_client_id()
    raw_id, _, _ = token.partition(".")
    assert auth.verify_client_id(token) == raw_id


def test_tampered_signature_is_rejected(temp_db):
    token = auth.issue_client_id()
    raw_id, _, signature = token.partition(".")
    flipped_char = "0" if signature[-1] != "0" else "1"
    tampered = f"{raw_id}.{signature[:-1]}{flipped_char}"
    assert auth.verify_client_id(tampered) is None


def test_forged_id_with_no_valid_signature_is_rejected(temp_db):
    assert auth.verify_client_id("attacker-just-made-this-up") is None
    assert auth.verify_client_id("some.forged.signature") is None
    assert auth.verify_client_id("") is None


def test_a_valid_signature_for_a_different_raw_id_does_not_transfer(temp_db):
    token_a = auth.issue_client_id()
    token_b = auth.issue_client_id()
    raw_a, _, _ = token_a.partition(".")
    _, _, signature_b = token_b.partition(".")
    assert auth.verify_client_id(f"{raw_a}.{signature_b}") is None


def test_secret_persists_across_calls(temp_db, monkeypatch):
    # Simulate a fresh process (no cached secret in memory) reusing the same
    # underlying db — this is what actually happens on a server restart, and
    # is why the secret has to be persisted rather than regenerated per run.
    token = auth.issue_client_id()
    monkeypatch.setattr(auth, "_cached_secret", None)
    assert auth.verify_client_id(token) is not None
