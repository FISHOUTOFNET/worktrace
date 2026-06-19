from worktrace.services import settings_service
from worktrace.ui.app import WorkTraceApp


class FakePage:
    def __init__(self):
        self.visible = False
        self.refreshed = 0

    def grid(self, *_args, **_kwargs):
        self.visible = True

    def grid_remove(self):
        self.visible = False

    def refresh(self):
        self.refreshed += 1


class FakeButton:
    def __init__(self):
        self.config = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


def _app_stub():
    app = object.__new__(WorkTraceApp)
    app.pages = {"overview": FakePage(), "timeline": FakePage()}
    app.nav_buttons = {"overview": FakeButton(), "timeline": FakeButton()}
    app.active_page = "overview"
    return app


def test_shell_show_page_hides_previous_and_refreshes_target():
    app = _app_stub()

    WorkTraceApp.show_page(app, "timeline")

    assert app.active_page == "timeline"
    assert not app.pages["overview"].visible
    assert app.pages["timeline"].visible
    assert app.pages["timeline"].refreshed == 1


def test_shell_toggle_pause_updates_setting(temp_db):
    app = _app_stub()
    app._refresh_sidebar_status = lambda: None
    app.timeline = FakePage()

    WorkTraceApp.toggle_pause(app)

    assert settings_service.get_bool_setting("user_paused") is True


def test_shell_open_timeline_sets_uncategorized_filter():
    app = _app_stub()
    app.timeline = type("TimelineStub", (), {"date_var": FakeVar(), "only_uncategorized": FakeVar(False)})()

    WorkTraceApp.open_timeline(app, True)

    assert app.timeline.only_uncategorized.get() is True
    assert app.active_page == "timeline"
