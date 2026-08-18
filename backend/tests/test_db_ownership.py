"""The ownership-scoped db mutations that back /api/trips/{id}/archive,
/api/trips/{id}/feedback, /api/notifications/{id}/read, and
/api/wishlist/{id}/archive.

Before this fix, these four endpoints didn't check client_id at all — any
visitor could archive, mark-read, or leave feedback on any trip/notification/
wishlist item by guessing an id, regardless of who it belonged to. These
tests are the regression guard for that.
"""


def _fake_plan(destination="Denver"):
    return {
        "origin_city": "Austin",
        "destination_city": destination,
        "days": [{"date": "2026-09-01"}, {"date": "2026-09-03"}],
    }


def test_set_trip_status_is_scoped_to_the_owning_client(temp_db):
    trip_id = temp_db.create_trip(_fake_plan(), email=None, client_id="alice")

    assert temp_db.set_trip_status(trip_id, "archived", client_id="bob") is False
    assert temp_db.list_trips("alice")[0]["status"] == "active"

    assert temp_db.set_trip_status(trip_id, "archived", client_id="alice") is True
    assert temp_db.list_trips("alice") == []  # archived trips are excluded from the list


def test_set_trip_status_with_no_client_id_is_the_trusted_internal_path(temp_db):
    # This is the scheduler's own call path (marking a trip completed on its
    # own) — it must still work unscoped.
    trip_id = temp_db.create_trip(_fake_plan(), email=None, client_id="alice")
    assert temp_db.set_trip_status(trip_id, "completed") is True


def test_save_trip_feedback_is_scoped_to_the_owning_client(temp_db):
    trip_id = temp_db.create_trip(_fake_plan(), email=None, client_id="alice")

    assert temp_db.save_trip_feedback(trip_id, 5, "loved it", client_id="bob") is False
    assert temp_db.save_trip_feedback(trip_id, 5, "loved it", client_id="alice") is True


def test_set_wishlist_status_is_scoped_to_the_owning_client(temp_db):
    item_id = temp_db.create_wishlist_item(
        {
            "client_id": "alice",
            "origin_city": "Austin",
            "origin_lat": 1.0,
            "origin_lon": 2.0,
            "destination_city": "Denver",
            "destination_lat": 3.0,
            "destination_lon": 4.0,
            "earliest_date": "2026-09-01",
            "latest_date": "2026-10-01",
            "trip_length_days": 5,
            "budget": 1000,
        }
    )

    assert temp_db.set_wishlist_status(item_id, "archived", client_id="bob") is False
    assert temp_db.set_wishlist_status(item_id, "archived", client_id="alice") is True


def test_mark_notification_read_is_scoped_to_the_owning_client(temp_db):
    trip_id = temp_db.create_trip(_fake_plan(), email=None, client_id="alice")
    temp_db.add_notification("weather_change", "rain incoming", None, trip_id=trip_id)
    notif_id = temp_db.list_notifications(client_id="alice")[0]["id"]

    assert temp_db.mark_notification_read(notif_id, client_id="bob") is False
    assert temp_db.list_notifications(unread_only=True, client_id="alice") != []

    assert temp_db.mark_notification_read(notif_id, client_id="alice") is True
    assert temp_db.list_notifications(unread_only=True, client_id="alice") == []


def _fake_local_watch(client_id="alice"):
    return {
        "client_id": client_id,
        "city": "Denver",
        "city_country": "United States",
        "lat": 39.7,
        "lon": -104.9,
        "mood_or_interest": "live music",
    }


def test_set_local_watch_status_is_scoped_to_the_owning_client(temp_db):
    watch_id = temp_db.create_local_watch(_fake_local_watch())

    assert temp_db.set_local_watch_status(watch_id, "archived", client_id="bob") is False
    assert temp_db.list_local_watches("alice")[0]["status"] == "active"

    assert temp_db.set_local_watch_status(watch_id, "archived", client_id="alice") is True
    assert temp_db.list_local_watches("alice") == []


def test_local_watch_notification_is_scoped_to_the_owning_client(temp_db):
    # A local_watch notification has no trip_id/wishlist_id — only
    # local_watch_id — so this exercises the third arm of the ownership JOIN.
    watch_id = temp_db.create_local_watch(_fake_local_watch())
    temp_db.add_notification("local_watch_new_events", "new show announced", "https://tm.com/x", local_watch_id=watch_id)
    notif_id = temp_db.list_notifications(client_id="alice")[0]["id"]

    assert temp_db.mark_notification_read(notif_id, client_id="bob") is False
    assert temp_db.mark_notification_read(notif_id, client_id="alice") is True


def test_day_plan_feedback_round_trips_and_is_scoped_by_client(temp_db):
    temp_db.save_day_plan_feedback("alice", "Denver", "live music", 5, "loved RiNo")
    temp_db.save_day_plan_feedback("alice", "Austin", "chill", 2, None)

    history = temp_db.get_day_plan_feedback_history("alice")
    assert len(history) == 2
    assert history[0]["city"] == "Austin"  # most recent first

    assert temp_db.get_day_plan_feedback_history("bob") == []
