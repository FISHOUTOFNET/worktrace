from __future__ import annotations

from types import SimpleNamespace

from worktrace.desktop.windows_webview_power import WindowsWebView2PowerController


class FakeCoreWebView2:
    def __init__(self, *, suspended: bool = False) -> None:
        self.IsSuspended = suspended
        self.calls: list[str] = []
        self.fail_suspend = False
        self.fail_resume = False

    def TrySuspendAsync(self):
        self.calls.append("suspend")
        if self.fail_suspend:
            raise RuntimeError("suspend failed")
        return object()

    def Resume(self) -> None:
        self.calls.append("resume")
        if self.fail_resume:
            raise RuntimeError("resume failed")
        self.IsSuspended = False


class FakeWebViewControl:
    def __init__(self, core: FakeCoreWebView2 | None = None) -> None:
        self.CoreWebView2 = core
        self.Visible = True
        self.invoke_calls = 0
        self.fail_invoke = False

    def Invoke(self, callback) -> None:
        self.invoke_calls += 1
        if self.fail_invoke:
            raise RuntimeError("invoke failed")
        callback()


def _controller(control: FakeWebViewControl) -> WindowsWebView2PowerController:
    window = SimpleNamespace(native=SimpleNamespace(webview=control))
    return WindowsWebView2PowerController(
        window,
        action_factory=lambda callback: callback,
    )


def test_hidden_mode_marshals_to_ui_thread_before_requesting_suspend() -> None:
    core = FakeCoreWebView2()
    control = FakeWebViewControl(core)

    _controller(control).enter_hidden_mode()

    assert control.invoke_calls == 1
    assert control.Visible is False
    assert core.calls == ["suspend"]


def test_prepare_for_show_resumes_suspended_renderer_then_restores_visibility() -> None:
    core = FakeCoreWebView2(suspended=True)
    control = FakeWebViewControl(core)
    control.Visible = False

    _controller(control).prepare_for_show()

    assert control.invoke_calls == 1
    assert core.calls == ["resume"]
    assert control.Visible is True


def test_prepare_for_show_skips_resume_when_renderer_is_not_suspended() -> None:
    core = FakeCoreWebView2(suspended=False)
    control = FakeWebViewControl(core)
    control.Visible = False

    _controller(control).prepare_for_show()

    assert core.calls == []
    assert control.Visible is True


def test_suspend_failure_is_fail_open_after_native_visibility_is_lowered() -> None:
    core = FakeCoreWebView2()
    core.fail_suspend = True
    control = FakeWebViewControl(core)

    _controller(control).enter_hidden_mode()

    assert core.calls == ["suspend"]
    assert control.Visible is False


def test_resume_failure_still_restores_native_webview_visibility() -> None:
    core = FakeCoreWebView2(suspended=True)
    core.fail_resume = True
    control = FakeWebViewControl(core)
    control.Visible = False

    _controller(control).prepare_for_show()

    assert core.calls == ["resume"]
    assert control.Visible is True


def test_missing_native_webview_and_ui_marshal_failure_are_noops() -> None:
    missing = WindowsWebView2PowerController(
        SimpleNamespace(native=None),
        action_factory=lambda callback: callback,
    )
    missing.enter_hidden_mode()
    missing.prepare_for_show()

    control = FakeWebViewControl(FakeCoreWebView2())
    control.fail_invoke = True
    controller = _controller(control)
    controller.enter_hidden_mode()
    controller.prepare_for_show()

    assert control.invoke_calls == 2
