from __future__ import annotations

from pathlib import Path
import threading

import pytest

from worktrace.integrations.fd_work.window_executor import (
    FDWorkExecutorWindow,
    FDWorkWindowExecutor,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.collector_runtime,
    pytest.mark.contract,
    pytest.mark.serial,
]


def test_executor_runs_commands_strictly_fifo_with_one_active_command():
    executor = FDWorkWindowExecutor(queue_capacity=8, name="fd-work-test-fifo")
    first_active = threading.Event()
    release_first = threading.Event()
    order = []
    active = 0
    maximum_active = 0
    state_lock = threading.Lock()
    results = {}

    def command(name, *, block=False):
        def run(done):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
                order.append(name)
            if block:
                first_active.set()
                assert release_first.wait(timeout=1)
            with state_lock:
                active -= 1
            done(name)

        return run

    first = threading.Thread(
        target=lambda: results.setdefault(
            "first", executor.submit(command("first", block=True), lambda: True, 1)
        )
    )
    second = threading.Thread(
        target=lambda: results.setdefault(
            "second", executor.submit(command("second"), lambda: True, 1)
        )
    )
    third = threading.Thread(
        target=lambda: results.setdefault(
            "third", executor.submit(command("third"), lambda: True, 1)
        )
    )
    first.start()
    assert first_active.wait(timeout=1)
    second.start()
    assert executor.wait_for_pending_count(1, timeout=1)
    third.start()
    assert executor.wait_for_pending_count(2, timeout=1)
    release_first.set()
    for thread in (first, second, third):
        thread.join(timeout=1)
        assert not thread.is_alive()

    assert order == ["first", "second", "third"]
    assert maximum_active == 1
    assert [results[name].value for name in ("first", "second", "third")] == [
        "first",
        "second",
        "third",
    ]
    executor.shutdown(timeout=1)


def test_callback_timeout_discards_stale_callback_and_next_command_continues():
    executor = FDWorkWindowExecutor(name="fd-work-test-timeout")
    callbacks = []

    timed_out = executor.submit(
        lambda done: callbacks.append(done),
        lambda: True,
        0.01,
    )
    following = executor.submit(lambda done: done("next"), lambda: True, 1)
    callbacks[0]("late")

    assert timed_out.ok is False
    assert timed_out.error_kind == "callback_timeout"
    assert timed_out.callback_executed is False
    assert following.ok is True
    assert following.value == "next"
    executor.shutdown(timeout=1)


def test_invalid_guard_never_executes_mutation_and_shutdown_rejects_new_command():
    executor = FDWorkWindowExecutor(name="fd-work-test-guard")
    mutations = []

    rejected = executor.submit(
        lambda done: (mutations.append("ran"), done(None)),
        lambda: False,
        1,
    )
    executor.shutdown(timeout=1)
    after_shutdown = executor.submit(
        lambda done: (mutations.append("late"), done(None)),
        lambda: True,
        1,
    )

    assert mutations == []
    assert rejected.error_kind == "guard_rejected"
    assert after_shutdown.error_kind == "executor_rejected"
    assert executor.worker_alive is False


def test_executor_worker_cannot_wait_on_nested_submit():
    executor = FDWorkWindowExecutor(name="fd-work-test-reentrant")
    nested = []

    def outer(done):
        nested.append(executor.submit(lambda complete: complete(True), lambda: True, 1))
        done(True)

    result = executor.submit(outer, lambda: True, 1)

    assert result.ok is True
    assert nested[0].ok is False
    assert nested[0].error_kind == "executor_rejected"
    executor.shutdown(timeout=1)


def test_window_command_sources_do_not_create_timer_threads():
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "worktrace/integrations/fd_work/window_executor.py",
            "worktrace/integrations/fd_work/window_controller.py",
            "worktrace/webview_main.py",
        )
    )

    assert "threading.Timer" not in sources
    assert "_defer_fd_work_callback" not in sources


def test_executor_window_routes_mutation_url_and_javascript_to_same_worker():
    executor = FDWorkWindowExecutor(name="fd-work-test-window-proxy")
    threads = []

    class Window:
        def show(self):
            threads.append(threading.current_thread().name)

        def get_current_url(self):
            threads.append(threading.current_thread().name)
            return "https://work.fangdalaw.com/Works/WorkHourList?picker=day"

        def evaluate_js(self, _script, callback=None):
            threads.append(threading.current_thread().name)
            callback({"ok": True})

    guarded = FDWorkExecutorWindow(Window(), executor, lambda: True)

    assert guarded.invoke("show") is True
    assert guarded.get_current_url().startswith("https://work.fangdalaw.com/")
    evaluated = guarded.execute_window_js("1", timeout=1)

    assert evaluated.ok is True
    assert evaluated.value == {"ok": True}
    assert threads == ["fd-work-test-window-proxy"] * 3
    executor.shutdown(timeout=1)
