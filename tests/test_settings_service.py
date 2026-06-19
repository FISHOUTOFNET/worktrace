from worktrace.services import settings_service


def test_settings_read_write(temp_db):
    settings_service.set_setting("poll_interval_seconds", "7")
    assert settings_service.get_int_setting("poll_interval_seconds", 3) == 7
    settings_service.set_setting("user_paused", "true")
    assert settings_service.get_bool_setting("user_paused") is True
    settings_service.set_list_setting("exclude_keywords", ["银行", "密码"])
    assert settings_service.get_list_setting("exclude_keywords") == ["银行", "密码"]
