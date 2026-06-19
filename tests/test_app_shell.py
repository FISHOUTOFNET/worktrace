from worktrace.services import settings_service
from worktrace.ui.app import WorkTraceApp


class FakePage:
    def __init__(self):
        self.visible = False
        self.refreshed = 0
        self.raised = 0
        self.grid_removed = False

    def grid(self, *_args, **_kwargs):
        self.visible = True

    def grid_remove(self):
        self.visible = False
        self.grid_removed = True

    def tkraise(self):
        self.raised += 1

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
    app.collector_started = True
    app.start_collector_callback = lambda: None
    app._sync_sidebar_status = lambda: None
    return app


def test_shell_show_page_raises_target_and_refreshes_once():
    app = _app_stub()

    WorkTraceApp.show_page(app, "timeline")

    assert app.active_page == "timeline"
    assert not app.pages["overview"].grid_removed
    assert app.pages["timeline"].raised == 1
    assert app.pages["timeline"].refreshed == 1


def test_shell_toggle_pause_updates_setting(temp_db):
    app = _app_stub()
    app.timeline = FakePage()
    settings_service.set_setting("collector_status", "running")

    WorkTraceApp.toggle_pause(app)

    assert settings_service.get_bool_setting("user_paused") is True


def test_shell_open_timeline_sets_uncategorized_filter():
    app = _app_stub()
    app.timeline = type("TimelineStub", (), {"date_var": FakeVar(), "only_uncategorized": FakeVar(False)})()

    WorkTraceApp.open_timeline(app, True)

    assert app.timeline.only_uncategorized.get() is True
    assert app.active_page == "timeline"


def test_shell_open_timeline_passes_session_context():
    app = _app_stub()
    calls = []

    class TimelineStub:
        def open_context(self, target_date, only_uncategorized=False, selected_session_id=None):
            calls.append((target_date, only_uncategorized, selected_session_id))

    app.timeline = TimelineStub()

    WorkTraceApp.open_timeline(app, False, session_id="1-2", target_date="2026-06-18")

    assert calls == [("2026-06-18", False, "1-2")]
    assert app.active_page == "timeline"
