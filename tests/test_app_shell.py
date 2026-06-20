from worktrace.services import settings_service
from worktrace.ui.app import SC_MINIMIZE, SIZE_MINIMIZED, SIZE_RESTORED, WM_SIZE, WM_SYSCOMMAND, WorkTraceApp


class FakePage:
    def __init__(self):
        self.visible = False
        self.refreshed = 0
        self.raised = 0
        self.grid_removed = False
        self.grid_calls = []
        self.config = {}

    def grid(self, *_args, **_kwargs):
        self.visible = True
        self.grid_calls.append((_args, _kwargs))

    def grid_remove(self):
        self.visible = False
        self.grid_removed = True

    def tkraise(self):
        self.raised += 1

    def configure(self, **kwargs):
        self.config.update(kwargs)

    def refresh(self):
        self.refreshed += 1


class FakeLivePage(FakePage):
    def __init__(self):
        super().__init__()
        self.live_refreshed = 0

    def refresh_current_activity(self):
        self.live_refreshed += 1


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


def _visual_app_stub():
    app = _app_stub()
    app.tk = object()
    app.content = FakePage()
    app.content.visible = True
    app.sidebar = FakePage()
    app._visual_suspend_cover = FakePage()
    app._visual_suspend_reason = None
    app._visual_suspend_scope = "content"
    app._visual_suspend_hides_content = False
    app._visual_reveal_after_id = None
    app._restore_refresh_after_id = None
    app._deferred_resume_refresh = False
    app._refresh_after_resize = False
    app._is_resizing = False
    app._resize_after_id = None
    app._resume_refresh_after_id = None
    app._ui_suspend_until = 0.0
    app._last_configure_size = (1240, 780)
    app._seen_root_map = True
    app._native_minimize_pending = False
    app._native_window_hook_installed = False
    app._native_window_handle = None
    app._native_old_wndproc = None
    app._native_wndproc = None
    app._native_win32gui = None
    app._page_refresh_after_ids = {}
    app.winfo_width = lambda: 1242
    app.winfo_height = lambda: 782
    app.winfo_id = lambda: 100
    app.state = lambda: "normal"
    scheduled = []
    idle = []
    cancelled = []

    def after(delay, callback):
        scheduled.append((delay, callback))
        return f"after-{len(scheduled)}"

    def after_idle(callback):
        idle.append(callback)
        return f"idle-{len(idle)}"

    app.after = after
    app.after_idle = after_idle
    app.after_cancel = lambda after_id: cancelled.append(after_id)
    app.update_idletasks_calls = 0
    app.update_idletasks = lambda: setattr(app, "update_idletasks_calls", app.update_idletasks_calls + 1)
    app._scheduled = scheduled
    app._idle = idle
    app._cancelled = cancelled
    return app


def _run_reveal_pipeline(app):
    app._scheduled[-1][1]()
    while app._idle:
        app._idle.pop(0)()


def test_shell_show_page_raises_target_and_refreshes_once():
    app = _app_stub()

    WorkTraceApp.show_page(app, "timeline")

    assert app.active_page == "timeline"
    assert not app.pages["overview"].grid_removed
    assert app.pages["timeline"].raised == 1
    assert app.pages["timeline"].refreshed == 1


def test_shell_show_page_lazily_creates_and_reuses_target():
    app = object.__new__(WorkTraceApp)
    app.pages = {}
    app.nav_buttons = {"overview": FakeButton(), "timeline": FakeButton()}
    app.active_page = "overview"
    created = []

    def make_page():
        created.append("timeline")
        return FakePage()

    app._page_factories = {"timeline": make_page}

    WorkTraceApp.show_page(app, "timeline")
    first_page = app.pages["timeline"]
    WorkTraceApp.show_page(app, "timeline")

    assert created == ["timeline"]
    assert first_page.visible is True
    assert first_page.raised == 1
    assert first_page.refreshed == 1


def test_shell_current_activity_tick_updates_only_active_page():
    app = object.__new__(WorkTraceApp)
    overview = FakeLivePage()
    timeline = FakeLivePage()
    app.pages = {"overview": overview, "timeline": timeline}
    app.active_page = "overview"
    scheduled = []
    app.after = lambda delay, callback: scheduled.append((delay, callback))

    WorkTraceApp._refresh_current_activity_status(app)

    assert overview.live_refreshed == 1
    assert timeline.live_refreshed == 0
    assert scheduled[0][0] == 1000
    assert scheduled[0][1].__func__ is WorkTraceApp._refresh_current_activity_status


def test_shell_current_activity_tick_skips_during_resize():
    app = object.__new__(WorkTraceApp)
    overview = FakeLivePage()
    app.pages = {"overview": overview}
    app.active_page = "overview"
    app._is_resizing = True
    scheduled = []
    app.after = lambda delay, callback: scheduled.append((delay, callback))

    WorkTraceApp._refresh_current_activity_status(app)

    assert overview.live_refreshed == 0
    assert scheduled[0][0] == 1000


def test_shell_resize_uses_cover_and_catches_up_once():
    app = _visual_app_stub()

    WorkTraceApp._on_configure(app)

    assert app._is_resizing is True
    assert app.content.visible is False
    assert app._visual_suspend_cover.visible is True
    assert app._scheduled[0][0] == 250

    app._refresh_after_resize = True
    app._scheduled[0][1]()

    assert app.pages["overview"].refreshed == 1
    assert app._visual_suspend_cover.visible is True
    assert app._scheduled[-1][0] == 80

    _run_reveal_pipeline(app)

    assert app.content.visible is True
    assert app._visual_suspend_cover.visible is False
    assert app._visual_suspend_reason is None
    assert app.update_idletasks_calls >= 3


def test_shell_restore_keeps_content_mounted_and_defers_refresh_until_after_reveal():
    app = _visual_app_stub()

    WorkTraceApp._on_unmap(app)
    WorkTraceApp._on_map(app)

    assert app.content.visible is True
    assert app.content.grid_removed is False
    assert app._visual_suspend_cover.visible is True
    assert app._visual_suspend_cover.raised == 2
    assert app._visual_suspend_cover.grid_calls[-1][1]["columnspan"] == 2
    assert app.pages["overview"].refreshed == 0
    assert app._scheduled[-1][0] == 120

    app._scheduled[-1][1]()

    assert app.pages["overview"].refreshed == 0
    assert app._visual_suspend_cover.visible is True
    assert app._scheduled[-1][0] == 220

    _run_reveal_pipeline(app)

    assert app.content.visible is True
    assert app._visual_suspend_cover.visible is False
    assert app.pages["overview"].refreshed == 0
    assert app._scheduled[-1][0] == 650

    app._scheduled[-1][1]()

    assert app.pages["overview"].refreshed == 1


def test_shell_visual_suspend_coalesces_scheduled_and_live_refreshes():
    app = _visual_app_stub()
    overview = FakeLivePage()
    app.pages = {"overview": overview}
    app._visual_suspend_reason = "resize"

    WorkTraceApp._schedule_page_refresh(app, "overview")
    WorkTraceApp._refresh_current_activity_status(app)

    assert overview.refreshed == 0
    assert overview.live_refreshed == 0
    assert app._refresh_after_resize is True
    assert app._scheduled[0][0] == 1000


def test_shell_native_minimize_prepares_full_cover_without_unmapping_content():
    app = _visual_app_stub()

    WorkTraceApp._handle_native_window_message(app, WM_SYSCOMMAND, SC_MINIMIZE, 0)

    assert app._native_minimize_pending is True
    assert app._refresh_after_resize is True
    assert app.content.visible is True
    assert app.content.grid_removed is False
    assert app._visual_suspend_cover.visible is True
    assert app._visual_suspend_cover.grid_calls[-1][1]["columnspan"] == 2
    assert app.update_idletasks_calls == 1


def test_shell_native_size_minimized_marks_pending_without_forced_paint():
    app = _visual_app_stub()

    WorkTraceApp._handle_native_window_message(app, WM_SIZE, SIZE_MINIMIZED, 0)

    assert app._native_minimize_pending is True
    assert app._visual_suspend_reason == "hidden"
    assert app.content.visible is True
    assert app.content.grid_removed is False
    assert app.update_idletasks_calls == 0


def test_shell_native_restore_starts_resume_pipeline():
    app = _visual_app_stub()
    WorkTraceApp._handle_native_window_message(app, WM_SYSCOMMAND, SC_MINIMIZE, 0)

    WorkTraceApp._handle_native_window_message(app, WM_SIZE, SIZE_RESTORED, 0)

    assert app._native_minimize_pending is False
    assert app._visual_suspend_reason == "resume"
    assert app.content.grid_removed is False
    assert app._scheduled[-1][0] == 120


def test_shell_native_hook_install_failure_falls_back_silently():
    app = _visual_app_stub()
    app.winfo_id = lambda: (_ for _ in ()).throw(RuntimeError("no hwnd"))

    WorkTraceApp._install_native_window_hook(app)

    assert app._native_window_hook_installed is False
    assert app._native_window_handle is None


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
