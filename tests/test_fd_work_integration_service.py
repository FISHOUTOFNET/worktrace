from __future__ import annotations

from dataclasses import dataclass

import pytest

from worktrace.integrations.fd_work.contracts import (
    FDWorkEntryDraft,
    FDWorkEntryError,
)
from worktrace.integrations.fd_work.integration_service import (
    FDWorkIntegrationService,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


@dataclass
class _DraftBuilder:
    draft: FDWorkEntryDraft = FDWorkEntryDraft(
        "2026-08-01",
        "CASE LABEL",
        "1.0",
        "Narrative",
    )

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def build(self, report_date, projection_instance_key, expected_projection_revision):
        self.calls.append(
            (report_date, projection_instance_key, expected_projection_revision)
        )
        return self.draft


class _Controller:
    def __init__(self) -> None:
        self.prepare_calls: list[bool] = []
        self.startup_prepare_calls: list[bool] = []
        self.renderer_calls: list[str] = []
        self.search_calls: list[str] = []
        self.open_calls: list[FDWorkEntryDraft] = []
        self.disable_calls = 0
        self.shutdown_calls = 0
        self.generation = 3
        self._status_callback = None
        self.status = {
            "session_state": "idle",
            "operation": "none",
            "ready": False,
            "login_required": False,
            "error_code": None,
            "navigation_generation": self.generation,
        }

    def bind_status_callback(self, callback):
        self._status_callback = callback

    def get_status(self):
        return dict(self.status)

    def prepare_session(self, show_login_if_required=True):
        self.prepare_calls.append(show_login_if_required)
        return {"ok": True, "status": self.get_status()}

    def prepare_window_before_start(self, show_login_if_required=True):
        self.startup_prepare_calls.append(show_login_if_required)
        return {"ok": True, "status": self.get_status()}

    def on_renderer_initialized(self, renderer):
        self.renderer_calls.append(renderer)

    def search_cases(self, query):
        self.search_calls.append(query)
        return {
            "ok": True,
            "labels": [" CASE A ", "CASE B"],
            "navigation_generation": self.generation,
        }

    def open_entry(self, draft):
        self.open_calls.append(draft)
        return {"ok": True, "status": "opening"}

    def disable(self):
        self.disable_calls += 1
        self.generation += 1

    def shutdown(self):
        self.shutdown_calls += 1

    def publish_generation(self, generation):
        self.generation = generation
        self.status["navigation_generation"] = generation
        if self._status_callback:
            self._status_callback(dict(self.status))


def _service(*, enabled=True, authorized=True, clock=None, token_factory=None, capacity=128):
    state = {"enabled": enabled}
    controller = _Controller()
    builder = _DraftBuilder()
    service = FDWorkIntegrationService(
        draft_builder=builder,
        window_controller=controller,
        enabled_reader=lambda: state["enabled"],
        enabled_writer=lambda value: state.__setitem__("enabled", value),
        clock=clock,
        token_factory=token_factory,
        selection_capacity=capacity,
    )
    if authorized:
        service.set_privacy_authorized(True)
    return service, controller, builder, state


def test_privacy_gate_defers_all_window_and_entry_operations():
    service, controller, builder, state = _service(enabled=True, authorized=False)

    assert service.prepare_session()["error"] == "deferred_by_privacy"
    assert service.prepare_window_before_start()["error"] == "deferred_by_privacy"
    assert service.search_cases("A", "request")["error"] == "deferred_by_privacy"
    with pytest.raises(FDWorkEntryError) as raised:
        service.open_entry("2026-08-01", "base:1", "revision-1")
    assert raised.value.code == "deferred_by_privacy"
    assert controller.prepare_calls == []
    assert controller.startup_prepare_calls == []
    assert controller.search_calls == []
    assert builder.calls == []

    status = service.set_enabled(True)
    assert state["enabled"] is True
    assert status["session_state"] == "deferred_by_privacy"
    assert controller.prepare_calls == []


def test_authorized_empty_and_one_character_queries_reach_controller():
    service, controller, _builder, _state = _service(enabled=True)
    service.set_privacy_authorized(True)
    controller.search_cases = lambda query: {
        "ok": True,
        "labels": ["RECENT"] if query == "" else [query],
        "navigation_generation": controller.generation,
    }

    assert service.search_cases("", "recent")["ok"] is True
    assert service.search_cases("A", "one")["ok"] is True


def test_disabled_capability_has_structured_status_and_never_prepares_window():
    service, controller, _builder, _state = _service(enabled=False)

    result = service.prepare_session(show_login_if_required=True)

    assert result == {
        "ok": False,
        "error": "fd_work_disabled",
        "status": {
            "supported": True,
            "enabled": False,
            "session_state": "disabled",
            "operation": "none",
            "ready": False,
            "login_required": False,
            "error_code": None,
            "navigation_generation": controller.generation,
        },
    }
    assert controller.prepare_calls == []
    assert service.prepare_window_before_start()["error"] == "fd_work_disabled"
    assert controller.startup_prepare_calls == []


def test_enabled_startup_prepare_and_renderer_init_use_injected_controller():
    service, controller, _builder, _state = _service()

    assert service.prepare_window_before_start(True)["ok"] is True
    service.on_renderer_initialized("edgechromium")

    assert controller.startup_prepare_calls == [True]
    assert controller.renderer_calls == ["edgechromium"]


def test_enabled_prepare_and_open_use_one_injected_controller_and_pure_builder():
    service, controller, builder, _state = _service()

    assert service.prepare_session(show_login_if_required=True)["ok"] is True
    result = service.open_entry("2026-08-01", "base:1", "revision-1")

    assert controller.prepare_calls == [True]
    assert builder.calls == [("2026-08-01", "base:1", "revision-1")]
    assert controller.open_calls == [builder.draft]
    assert result["ok"] is True


def test_search_returns_opaque_selection_tokens_bound_to_label_and_generation():
    tokens = iter(["opaque-token-a", "opaque-token-b"])
    service, controller, _builder, _state = _service(
        token_factory=lambda: next(tokens)
    )

    result = service.search_cases("ca", "request-7")

    assert result["ok"] is True
    assert result["request_id"] == "request-7"
    assert result["options"] == [
        {"label": "CASE A", "selection_token": "opaque-token-a"},
        {"label": "CASE B", "selection_token": "opaque-token-b"},
    ]
    assert controller.search_calls == ["ca"]
    assert "CASE" not in result["options"][0]["selection_token"]
    assert service.validate_case_selection("opaque-token-a", "CASE A") == "CASE A"

    with pytest.raises(FDWorkEntryError) as mismatch:
        service.validate_case_selection("opaque-token-a", "CASE B")
    assert mismatch.value.code == "case_selection_mismatch"

    controller.publish_generation(4)
    with pytest.raises(FDWorkEntryError) as expired:
        service.validate_case_selection("opaque-token-a", "CASE A")
    assert expired.value.code == "case_selection_expired"


def test_selection_registry_expires_discards_and_enforces_capacity():
    now = [10.0]
    token_values = iter(["token-1", "token-2", "token-3", "token-4"])
    service, controller, _builder, _state = _service(
        clock=lambda: now[0],
        token_factory=lambda: next(token_values),
        capacity=2,
    )
    controller.search_cases = lambda query: {
        "ok": True,
        "labels": [query],
        "navigation_generation": controller.generation,
    }

    service.search_cases("AA", "1")
    service.search_cases("BB", "2")
    service.search_cases("CC", "3")

    with pytest.raises(FDWorkEntryError) as evicted:
        service.validate_case_selection("token-1", "AA")
    assert evicted.value.code == "case_selection_expired"
    with pytest.raises(FDWorkEntryError) as superseded:
        service.validate_case_selection("token-2", "BB")
    assert superseded.value.code == "case_selection_expired"
    assert service.validate_case_selection("token-3", "CC") == "CC"

    service.discard_case_selection("token-3")
    with pytest.raises(FDWorkEntryError) as discarded:
        service.validate_case_selection("token-3", "CC")
    assert discarded.value.code == "case_selection_expired"

    service.search_cases("DD", "4")
    now[0] += 301
    with pytest.raises(FDWorkEntryError) as timed_out:
        service.validate_case_selection("token-4", "DD")
    assert timed_out.value.code == "case_selection_expired"


def test_disable_clears_registry_and_shutdown_is_permanent():
    tokens = iter(["opaque-token-a", "opaque-token-b"])
    service, controller, _builder, state = _service(
        token_factory=lambda: next(tokens)
    )
    service.search_cases("ca", "request")

    status = service.set_enabled(False)

    assert state["enabled"] is False
    assert controller.disable_calls == 1
    assert status["session_state"] == "disabled"
    with pytest.raises(FDWorkEntryError) as cleared:
        service.validate_case_selection("opaque-token-a", "CASE A")
    assert cleared.value.code == "case_selection_expired"

    service.shutdown()
    service.shutdown()
    assert controller.shutdown_calls == 1
    assert service.get_settings_status()["session_state"] == "shutdown"
