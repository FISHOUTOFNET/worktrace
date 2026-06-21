from worktrace.services import settings_service
from worktrace.ui.settings_view import SettingsView


class FakeEntry:
    def __init__(self, value=""):
        self.value = value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, value):
        self.value = str(value)

    def get(self):
        return self.value


class FakeVar:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _settings_view_stub():
    view = object.__new__(SettingsView)
    view.entries = {"export_path": FakeEntry("C:\\Exports")}
    view.clipboard_capture_var = FakeVar(False)
    return view


def test_clipboard_capture_checkbox_saves_immediately(temp_db):
    view = _settings_view_stub()
    view.clipboard_capture_var.set(True)

    SettingsView.save_clipboard_capture(view)

    assert settings_service.get_bool_setting("clipboard_capture_enabled") is True


def test_settings_refresh_keeps_saved_clipboard_capture_state(temp_db):
    view = _settings_view_stub()
    settings_service.set_setting("clipboard_capture_enabled", "true")

    SettingsView.refresh(view)

    assert view.clipboard_capture_var.get() is True


def test_save_settings_does_not_overwrite_clipboard_capture(temp_db, monkeypatch):
    view = _settings_view_stub()
    view.clipboard_capture_var.set(False)
    settings_service.set_setting("clipboard_capture_enabled", "true")
    monkeypatch.setattr("worktrace.ui.settings_view.messagebox.showinfo", lambda *_args, **_kwargs: None)

    SettingsView.save(view)

    assert settings_service.get_setting("export_path") == "C:\\Exports"
    assert settings_service.get_bool_setting("clipboard_capture_enabled") is True
