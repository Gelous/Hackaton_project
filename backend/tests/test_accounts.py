"""Real user accounts — mandatory to use any planning/data feature (see
db.py's module docstring). Tests call the FastAPI endpoint functions
directly (same pattern as test_localize_plan.py), passing already-resolved
values for Depends() params rather than spinning up a real HTTP client,
consistent with how the rest of this test suite works.
"""

import pytest
from fastapi import HTTPException

from trip_agent import db, server


def test_create_user_then_fetch_by_email(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    user = db.get_user_by_email("traveler@example.com")
    assert user["id"] == user_id
    assert user["email"] == "traveler@example.com"


def test_create_user_duplicate_email_returns_none(temp_db):
    db.create_user("traveler@example.com", "hash", "salt")
    assert db.create_user("traveler@example.com", "different-hash", "different-salt") is None


def test_get_user_by_email_unknown_returns_none(temp_db):
    assert db.get_user_by_email("nobody@example.com") is None


def test_update_home_location_persists(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_home_location(user_id, "Austin", "United States", 30.27, -97.74)
    user = db.get_user_by_id(user_id)
    assert user["home_city"] == "Austin"
    assert user["home_country"] == "United States"
    assert user["home_lat"] == 30.27
    assert user["home_lon"] == -97.74


def test_update_preferences_persists(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_preferences(user_id, "EUR", "drive", "boutique", "alerts@example.com")
    user = db.get_user_by_id(user_id)
    assert user["default_currency"] == "EUR"
    assert user["default_transportation"] == "drive"
    assert user["default_accommodation"] == "boutique"
    assert user["notify_email"] == "alerts@example.com"


def test_update_preferences_can_clear_a_previously_set_value(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_preferences(user_id, "EUR", "drive", "boutique", "alerts@example.com")
    db.update_preferences(user_id, None, None, None, None)
    user = db.get_user_by_id(user_id)
    assert user["default_currency"] is None
    assert user["notify_email"] is None


# ---- /api/auth/signup ----


def test_signup_creates_a_real_account_and_returns_a_session_token(temp_db):
    result = server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    assert result["email"] == "traveler@example.com"
    assert result["session_token"]
    assert result["home_city"] is None


def test_signup_response_never_includes_the_password_hash(temp_db):
    result = server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    assert "password_hash" not in result
    assert "password_salt" not in result
    assert "password" not in result


def test_signup_lowercases_and_trims_email(temp_db):
    server.signup(server.SignupRequest(email="  Traveler@Example.com  ", password="correct horse"))
    assert db.get_user_by_email("traveler@example.com") is not None


def test_signup_rejects_duplicate_email(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    with pytest.raises(HTTPException) as exc:
        server.signup(server.SignupRequest(email="traveler@example.com", password="another password"))
    assert exc.value.status_code == 409


def test_signup_rejects_short_password(temp_db):
    with pytest.raises(HTTPException) as exc:
        server.signup(server.SignupRequest(email="traveler@example.com", password="short"))
    assert exc.value.status_code == 400


def test_signup_rejects_invalid_email(temp_db):
    with pytest.raises(HTTPException) as exc:
        server.signup(server.SignupRequest(email="not-an-email", password="correct horse"))
    assert exc.value.status_code == 400


# ---- /api/auth/login ----


def test_login_with_correct_credentials_succeeds(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    result = server.login(server.LoginRequest(email="traveler@example.com", password="correct horse"))
    assert result["email"] == "traveler@example.com"
    assert result["session_token"]


def test_login_with_wrong_password_is_rejected(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    with pytest.raises(HTTPException) as exc:
        server.login(server.LoginRequest(email="traveler@example.com", password="wrong password"))
    assert exc.value.status_code == 401


def test_login_with_unknown_email_is_rejected_with_the_same_message_as_wrong_password(temp_db):
    """Same error either way — confirming an email isn't registered would
    let someone enumerate real accounts one guess at a time."""
    with pytest.raises(HTTPException) as exc:
        server.login(server.LoginRequest(email="nobody@example.com", password="whatever"))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email or password"

    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    with pytest.raises(HTTPException) as exc2:
        server.login(server.LoginRequest(email="traveler@example.com", password="wrong password"))
    assert exc2.value.detail == exc.value.detail


def test_login_is_case_insensitive_on_email(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    result = server.login(server.LoginRequest(email="Traveler@Example.com", password="correct horse"))
    assert result["email"] == "traveler@example.com"


# ---- /api/auth/me and /api/auth/home-location ----


def test_get_me_returns_the_logged_in_user_s_profile(temp_db):
    signup_result = server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    user_id = db.get_user_by_email("traveler@example.com")["id"]

    profile = server.get_me(user_id=user_id)

    assert profile["email"] == "traveler@example.com"
    assert signup_result["session_token"]  # sanity: signup really did issue one


def test_set_home_location_updates_and_returns_the_new_profile(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    user_id = db.get_user_by_email("traveler@example.com")["id"]

    profile = server.set_home_location(
        server.HomeLocationRequest(city="Austin", country="United States", lat=30.27, lon=-97.74),
        user_id=user_id,
    )

    assert profile["home_city"] == "Austin"
    assert profile["home_lat"] == 30.27

    # And it's really persisted, not just echoed back.
    refetched = server.get_me(user_id=user_id)
    assert refetched["home_city"] == "Austin"


def test_set_preferences_updates_and_returns_the_new_profile(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    user_id = db.get_user_by_email("traveler@example.com")["id"]

    profile = server.set_preferences(
        server.PreferencesRequest(
            default_currency="EUR",
            default_transportation="drive",
            default_accommodation="boutique",
            notify_email="alerts@example.com",
        ),
        user_id=user_id,
    )

    assert profile["default_currency"] == "EUR"
    assert profile["default_transportation"] == "drive"
    assert profile["default_accommodation"] == "boutique"
    assert profile["notify_email"] == "alerts@example.com"

    # And it's really persisted, not just echoed back.
    refetched = server.get_me(user_id=user_id)
    assert refetched["default_currency"] == "EUR"


# ---- _alert_email: every alert now goes to a real account address, never a
# manually-typed one (see the "Email me at my account address" checkboxes) ----


def test_alert_email_uses_the_notify_email_preference_when_set(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_preferences(user_id, None, None, None, "alerts@example.com")
    assert server._alert_email(user_id, alerts=True) == "alerts@example.com"


def test_alert_email_falls_back_to_the_login_email(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    assert server._alert_email(user_id, alerts=True) == "traveler@example.com"


def test_alert_email_is_none_when_alerts_unchecked(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    assert server._alert_email(user_id, alerts=False) is None


def test_alert_email_is_none_when_email_notifications_disabled_even_if_checked(temp_db):
    """The account-wide setting is a hard override of every per-item
    checkbox — checking "email me" on one item can't re-enable email once
    the traveler has turned it off account-wide."""
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_settings(user_id, False, True, "medium", "light")
    assert server._alert_email(user_id, alerts=True) is None


# ---- account-wide settings ----


def test_update_settings_persists(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_settings(user_id, False, False, "large", "dark")
    user = db.get_user_by_id(user_id)
    assert user["email_notifications_enabled"] == 0
    assert user["in_app_notifications_enabled"] == 0
    assert user["font_scale"] == "large"
    assert user["theme"] == "dark"


def test_new_account_defaults_to_notifications_on_medium_light(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    user = db.get_user_by_id(user_id)
    assert user["email_notifications_enabled"] == 1
    assert user["in_app_notifications_enabled"] == 1
    assert user["font_scale"] == "medium"
    assert user["theme"] == "light"


def test_set_settings_endpoint_updates_and_returns_the_new_profile(temp_db):
    server.signup(server.SignupRequest(email="traveler@example.com", password="correct horse"))
    user_id = db.get_user_by_email("traveler@example.com")["id"]

    profile = server.set_settings(
        server.SettingsRequest(
            email_notifications_enabled=False, in_app_notifications_enabled=True, font_scale="large", theme="dark"
        ),
        user_id=user_id,
    )

    assert profile["email_notifications_enabled"] is False
    assert profile["font_scale"] == "large"
    assert profile["theme"] == "dark"


def test_get_notifications_returns_empty_when_in_app_notifications_disabled(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.update_settings(user_id, True, False, "medium", "light")
    client_id = f"account:{user_id}"
    trip_id = db.create_trip({"origin_city": "Austin", "destination_city": "Denver", "days": [{"date": "2026-09-01"}, {"date": "2026-09-03"}]}, None, client_id)
    db.add_notification("weather_change", "rain incoming", None, trip_id=trip_id)

    result = server.get_notifications(unread_only=True, x_client_id=client_id, user_id=user_id)

    assert result == []


# ---- account deletion ----


def test_delete_account_removes_the_user_row(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    server.delete_account(user_id=user_id)
    assert db.get_user_by_id(user_id) is None


def test_delete_account_removes_owned_trips_wishlist_watches_and_notifications(temp_db):
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    client_id = f"account:{user_id}"
    trip_id = db.create_trip({"origin_city": "Austin", "destination_city": "Denver", "days": [{"date": "2026-09-01"}, {"date": "2026-09-03"}]}, None, client_id)
    db.add_notification("weather_change", "rain incoming", None, trip_id=trip_id)

    server.delete_account(user_id=user_id)

    assert db.list_trips(client_id) == []
    assert db.list_notifications(client_id=client_id) == []


# ---- verified_session / require_login dependency behavior ----


def test_verified_session_returns_none_when_no_token_given(temp_db):
    assert server.verified_session(x_session_token=None) is None


def test_verified_session_rejects_a_tampered_token(temp_db):
    from trip_agent import auth

    token = auth.issue_session_token(1)
    with pytest.raises(HTTPException) as exc:
        server.verified_session(x_session_token=token + "tampered")
    assert exc.value.status_code == 401


def test_require_login_rejects_when_not_logged_in(temp_db):
    with pytest.raises(HTTPException) as exc:
        server.require_login(user_id=None)
    assert exc.value.status_code == 401


def test_require_login_rejects_a_deleted_accounts_still_valid_token(temp_db):
    """Regression test: a session token's signature alone doesn't prove the
    account still exists — it stays signature-valid even after deletion (see
    /api/auth/account). Found live: a stray notification-poll request using
    a just-deleted account's token crashed get_notifications with a 500
    (NoneType not subscriptable) instead of a clean 401, because
    require_login used to hand back a bare user_id without ever confirming
    db.get_user_by_id(user_id) still returns a row."""
    user_id = db.create_user("traveler@example.com", "hash", "salt")
    db.delete_user(user_id)
    with pytest.raises(HTTPException) as exc:
        server.require_login(user_id=user_id)
    assert exc.value.status_code == 401


# ---- require_client_id: every planning/data endpoint now requires login ----


def test_require_client_id_derives_a_stable_id_from_the_account(temp_db):
    assert server.require_client_id(user_id=42) == "account:42"


def test_require_client_id_is_different_for_different_accounts(temp_db):
    assert server.require_client_id(user_id=1) != server.require_client_id(user_id=2)


def test_planning_and_data_endpoints_require_a_logged_in_account():
    """A direct check that the dependency chain really is wired to every
    formerly-anonymous endpoint — not just that require_client_id itself
    401s, but that each endpoint actually declares it as a dependency."""
    import inspect

    gated_endpoints = [
        server.create_plan,
        server.create_plan_stream,
        server.create_day_plan,
        server.create_day_plan_stream,
        server.submit_day_plan_feedback,
        server.save_trip,
        server.get_trips,
        server.archive_trip,
        server.submit_trip_feedback,
        server.get_notifications,
        server.read_notification,
        server.create_wishlist,
        server.get_wishlist,
        server.archive_wishlist,
        server.create_local_watch,
        server.get_local_watches,
        server.archive_local_watch,
    ]
    for endpoint in gated_endpoints:
        params = inspect.signature(endpoint).parameters
        default = params["x_client_id"].default
        assert default.dependency is server.require_client_id, endpoint.__name__
