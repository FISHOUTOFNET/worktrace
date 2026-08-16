from __future__ import annotations

import inspect

from worktrace import webview_main


def test_webview_host_does_not_patch_static_dom_presentation() -> None:
    source = inspect.getsource(webview_main)

    for forbidden in (
        "_navigation_brand_script",
        "_apply_navigation_brand",
        "document.querySelector",
        "document.getElementById",
        ".textContent =",
        ".createElement(",
        ".remove()",
        "trace-navigation-brand",
    ):
        assert forbidden not in source


def test_shell_loaded_event_is_bound_directly_to_shell_owner() -> None:
    closing_handlers = []
    loaded_handlers = []

    class Event:
        def __init__(self, handlers):
            self.handlers = handlers

        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

    class Events:
        def __init__(self):
            self.closing = Event(closing_handlers)
            self.loaded = Event(loaded_handlers)

    class Window:
        events = Events()

    class Shell:
        def handle_window_closing(self):
            return False

        def handle_window_loaded(self):
            return None

    shell = Shell()
    webview_main._bind_shell_events(Window(), shell)

    assert closing_handlers == [shell.handle_window_closing]
    assert loaded_handlers == [shell.handle_window_loaded]
