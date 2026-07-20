from __future__ import annotations

from dataclasses import dataclass

from worktrace.api.app_api import ApplicationControlService
from worktrace.api.application_services import ApplicationServices
from worktrace.runtime.contracts import RuntimeStartResult
from worktrace.webview_ui.bridge import WebViewBridge


@dataclass
class TestRuntime:
    """Explicit runtime fake for bridge tests; never installed globally."""

    start_result: RuntimeStartResult | None = None
    pause_result: dict[str, object] | None = None
    clipboard_accepted: bool = True
    phase: str = "running"

    def start_authorized_collection(self) -> RuntimeStartResult:
        return self.start_result or RuntimeStartResult(
            ok=True,
            collector_ready=True,
            workers={},
            already_running=False,
            degraded=False,
            error_code=None,
        )

    def pause_collection_now(self) -> dict[str, object]:
        return self.pause_result or {"ok": True, "pause_pending": False}

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        return bool(self.clipboard_accepted)

    def request_shutdown(self) -> None:
        return None

    def worker_registry_snapshot(self) -> dict[str, object]:
        return {}

    def worker_health_snapshot(self) -> dict[str, object]:
        return {"workers": {}, "degraded_workers": []}


@dataclass
class TestMaintenance:
    """Explicit maintenance-state fake used by composed bridge tests."""

    blocked_reason: str | None = None


def build_test_application_services(
    runtime: TestRuntime | None = None,
    maintenance: TestMaintenance | None = None,
) -> ApplicationServices:
    runtime_capability = runtime if runtime is not None else TestRuntime()
    maintenance_capability = maintenance if maintenance is not None else TestMaintenance()
    return ApplicationServices(
        app_control=ApplicationControlService(
            runtime_capability,
            maintenance_capability,
        ),
        runtime_view=runtime_capability,
    )


def build_test_bridge(
    runtime: TestRuntime | None = None,
    maintenance: TestMaintenance | None = None,
) -> WebViewBridge:
    return WebViewBridge(build_test_application_services(runtime, maintenance))


__all__ = [
    "TestMaintenance",
    "TestRuntime",
    "build_test_application_services",
    "build_test_bridge",
]
