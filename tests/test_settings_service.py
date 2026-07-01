from worktrace.services import settings_service
from worktrace import db


def test_settings_read_write(temp_db):
    settings_service.set_setting("poll_interval_seconds", "7")
    assert settings_service.get_int_setting("poll_interval_seconds", 3) == 7
    settings_service.set_setting("user_paused", "true")
    assert settings_service.get_bool_setting("user_paused") is True


def test_settings_cache_reuses_reads_and_updates_on_write(temp_db, monkeypatch):
    settings_service.clear_settings_cache()
    original = settings_service.get_connection
    calls = {"count": 0}

    def counted_connection():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(settings_service, "get_connection", counted_connection)

    # Section 八: seeded default is now "1" (was "3").
    assert settings_service.get_setting("poll_interval_seconds") == "1"
    assert settings_service.get_setting("poll_interval_seconds") == "1"
    assert calls["count"] == 1

    settings_service.set_setting("poll_interval_seconds", "8")
    assert settings_service.get_setting("poll_interval_seconds") == "8"
    assert calls["count"] == 2


def test_settings_cache_isolated_by_database_path(tmp_path):
    settings_service.clear_settings_cache()
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"

    db.initialize_database(first)
    settings_service.set_setting("poll_interval_seconds", "4")
    assert settings_service.get_setting("poll_interval_seconds") == "4"

    db.initialize_database(second)
    # Section 八: seeded default is now "1" (was "3").
    assert settings_service.get_setting("poll_interval_seconds") == "1"

    db.initialize_database(first)
    assert settings_service.get_setting("poll_interval_seconds") == "4"
