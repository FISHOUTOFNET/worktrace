from __future__ import annotations

from dataclasses import dataclass

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft, FDWorkEntryError
from worktrace.integrations.fd_work.integration_service import FDWorkIntegrationService


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


@dataclass
class _DraftBuilder:
    draft: FDWorkEntryDraft = FDWorkEntryDraft(
        "2026-08-03", "CASE LABEL", "CASE LABEL", "1.0", "Narrative"
    )

    def __post_init__(self):
        self.calls = []

    def build(self, report_date, projection_instance_key, expected_projection_revision):
        self.calls.append(
            (report_date, projection_instance_key, expected_projection_revision)
        )
        return self.draft


class _Coordinator:
    def __init__(self) -> None:
        self.prepare_calls = []
        self.startup_prepare_calls = []
        self.renderer_calls = []
        self.picker_calls = []
        self.open_calls = []
        self.disable_calls = 0
        self.enable_calls = 0
        self.shutdown_calls = 0
        self.picker_results = {}
        self.generation = 3
        self._status_callback = None
        self._picker_result_callback = None
        self.status = {
            "session_state": "ready",
            "page_phase": "work_shell",
            "operation": "none",
            "interaction_owner": "none",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": self.generation,
        }

    def bind_status_callback(self, callback):
        self._status_callback = callback

    def bind_picker_result_callback(self, callback):
        self._picker_result_callback = callback

    def get_status(self):
        return dict(self.status)

    def prepare_session(self, show_login_if_required=True):
        self.prepare_calls.append(show_login_if_required)
        return {"ok": True, "status": self.get_status()}

    def prepare_window_before_start(self, show_login_if_required=False):
        self.startup_prepare_calls.append(show_login_if_required)
        return {"ok": True, "status": self.get_status()}

    def on_renderer_initialized(self, renderer):
        self.renderer_calls.append(renderer)

    def open_case_picker(self, request_id):
        self.picker_calls.append(request_id)
        return dict(self.picker_results.get(request_id, {
            "ok": True,
            "request_id": request_id,
            "operation_nonce": "nonce",
            "status": "picker_ready",
        }))

    def open_entry(self, draft):
        self.open_calls.append(draft)
        return {"ok": True, "operation_status": "save_completed"}

    def enable(self):
        self.enable_calls += 1

    def disable(self):
        self.disable_calls += 1

    def shutdown(self):
        self.shutdown_calls += 1

    def publish_status(self, **changes):
        self.status.update(changes)
        if "navigation_generation" in changes:
            self.generation = changes["navigation_generation"]
        if self._status_callback:
            self._status_callback(dict(self.status))

    def publish_picker(self, result):
        assert self._picker_result_callback
        self._picker_result_callback(dict(result))


def _service(
    *, enabled=True, authorized=True, clock=None, token_factory=None, capacity=128
):
    state = {"enabled": enabled}
    coordinator = _Coordinator()
    builder = _DraftBuilder()
    delivered = []
    service = FDWorkIntegrationService(
        draft_builder=builder,
        interaction_coordinator=coordinator,
        enabled_reader=lambda: state["enabled"],
        enabled_writer=lambda value: state.__setitem__("enabled", value),
        clock=clock,
        token_factory=token_factory,
        selection_capacity=capacity,
        picker_result_callback=delivered.append,
    )
    if authorized:
        service.set_privacy_authorized(True)
    return service, coordinator, builder, state, delivered


def _publish_success(coordinator, request_id, label="CASE A", generation=None, nonce="nonce"):
    coordinator.publish_picker(
        {
            "ok": True,
            "request_id": request_id,
            "operation_nonce": nonce,
            "navigation_generation": coordinator.generation if generation is None else generation,
            "label": label,
        }
    )


def test_privacy_gate_defers_probe_picker_and_entry_without_touching_helper():
    service, coordinator, builder, _state, _delivered = _service(
        enabled=True, authorized=False
    )

    assert service.prepare_session()["error"] == "deferred_by_privacy"
    assert service.prepare_window_before_start()["error"] == "deferred_by_privacy"
    assert service.open_case_picker("drawer")["error"] == "deferred_by_privacy"
    with pytest.raises(FDWorkEntryError) as raised:
        service.open_entry("2026-08-03", "base:1", "revision")
    assert raised.value.code == "deferred_by_privacy"
    assert coordinator.prepare_calls == []
    assert coordinator.startup_prepare_calls == []
    assert coordinator.picker_calls == []
    assert builder.calls == []


def test_disabled_capability_has_explicit_session_and_owner_state():
    service, coordinator, _builder, _state, _delivered = _service(enabled=False)

    result = service.prepare_session(True)

    assert result["error"] == "fd_work_disabled"
    assert result["capability_status"]["session_state"] == "disabled"
    assert result["capability_status"]["interaction_owner"] == "none"
    assert "status" not in result
    assert coordinator.prepare_calls == []


def test_authorized_startup_probe_renderer_and_explicit_auth_delegate_once():
    service, coordinator, _builder, _state, _delivered = _service()

    assert service.prepare_window_before_start(False)["ok"] is True
    assert service.prepare_session(True)["ok"] is True
    service.on_renderer_initialized("edgechromium")

    assert coordinator.startup_prepare_calls == [False]
    assert coordinator.prepare_calls == [True]
    assert coordinator.renderer_calls == ["edgechromium"]


def test_picker_operation_status_is_not_overwritten_by_capability_status():
    service, coordinator, _builder, _state, _delivered = _service()
    coordinator.picker_results["drawer-auth"] = {
        "ok": True,
        "request_id": "drawer-auth",
        "operation_nonce": "nonce",
        "status": "authentication_required",
    }

    result = service.open_case_picker("drawer-auth")

    assert result["operation_status"] == "authentication_required"
    assert result["capability_status"]["session_state"] == "ready"
    assert "status" not in result


def test_busy_second_picker_does_not_replace_or_clear_first_active_request():
    service, coordinator, _builder, _state, delivered = _service(
        token_factory=lambda: "first-token"
    )
    assert service.open_case_picker("drawer-first")["ok"] is True
    coordinator.picker_results["drawer-second"] = {
        "ok": False,
        "error": "fd_work_busy",
    }

    second = service.open_case_picker("drawer-second")
    _publish_success(coordinator, "drawer-first")

    assert second["error"] == "fd_work_busy"
    assert delivered == [{
        "ok": True,
        "request_id": "drawer-first",
        "selected_label": "CASE A",
        "selection_token": "first-token",
    }]


@pytest.mark.parametrize(
    ("internal_error", "public_error"),
    [
        ("javascript_exception", "fd_work_page_unavailable"),
        ("non_mapping_result", "fd_work_page_unavailable"),
        ("page_contract_changed", "fd_work_page_unavailable"),
        ("callback_timeout", "fd_work_operation_timeout"),
        ("executor_rejected", "fd_work_window_unavailable"),
        ("fd_work_busy", "fd_work_busy"),
        ("case_selection_required", "case_selection_required"),
        ("case_selection_mismatch", "case_selection_mismatch"),
    ],
)
def test_picker_maps_internal_failures_to_small_stable_public_errors(
    internal_error, public_error
):
    service, coordinator, _builder, _state, _delivered = _service()
    coordinator.picker_results["drawer"] = {
        "ok": False,
        "error": internal_error,
    }

    result = service.open_case_picker("drawer")

    assert result["error"] == public_error
    assert result["capability_status"]["session_state"] == "ready"


def test_async_picker_failure_delivery_never_exposes_internal_error_kind():
    service, coordinator, _builder, _state, delivered = _service()
    assert service.open_case_picker("drawer")["ok"] is True

    coordinator.publish_picker({
        "ok": False,
        "request_id": "drawer",
        "operation_nonce": "nonce",
        "error": "javascript_exception",
    })

    assert delivered == [{
        "ok": False,
        "request_id": "drawer",
        "error": "fd_work_page_unavailable",
    }]


def test_picker_success_delivers_canonical_one_time_selection_token():
    service, coordinator, _builder, _state, delivered = _service(
        token_factory=lambda: "selection-token"
    )

    opened = service.open_case_picker("drawer-7")
    _publish_success(coordinator, "drawer-7", "\u3000CASE A\u00a0")

    assert opened["ok"] is True
    assert coordinator.picker_calls == ["drawer-7"]
    assert delivered == [{
        "ok": True,
        "request_id": "drawer-7",
        "selected_label": "CASE A",
        "selection_token": "selection-token",
    }]
    assert service.validate_case_selection("selection-token", "CASE A") == "CASE A"
    with pytest.raises(FDWorkEntryError) as consumed:
        service.validate_case_selection("selection-token", "CASE A")
    assert consumed.value.code == "case_selection_expired"


def test_selection_claim_is_exclusive_and_complete_consumes_token():
    service, coordinator, _builder, _state, _delivered = _service(
        token_factory=lambda: "selection-token"
    )
    service.open_case_picker("drawer-claim")
    _publish_success(coordinator, "drawer-claim", "CASE A")

    claim = service.claim_case_selection("selection-token", "CASE A")
    assert claim.label == "CASE A"
    with pytest.raises(FDWorkEntryError) as concurrent:
        service.claim_case_selection("selection-token", "CASE A")
    assert concurrent.value.code == "fd_work_busy"

    service.complete_case_selection_claim(claim)
    with pytest.raises(FDWorkEntryError) as consumed:
        service.claim_case_selection("selection-token", "CASE A")
    assert consumed.value.code == "case_selection_expired"


def test_selection_claim_release_makes_unpersisted_selection_available_again():
    service, coordinator, _builder, _state, _delivered = _service(
        token_factory=lambda: "selection-token"
    )
    service.open_case_picker("drawer-release")
    _publish_success(coordinator, "drawer-release", "CASE A")

    first = service.claim_case_selection("selection-token", "CASE A")
    service.release_case_selection_claim(first)
    second = service.claim_case_selection("selection-token", "CASE A")

    assert second.label == "CASE A"
    assert second.claim_id != first.claim_id


def test_free_text_label_mismatch_and_wrong_generation_fail_closed():
    tokens = iter(["token-a", "token-b"])
    service, coordinator, _builder, _state, _delivered = _service(
        token_factory=lambda: next(tokens)
    )
    service.open_case_picker("drawer-a")
    _publish_success(coordinator, "drawer-a", "CASE A")
    with pytest.raises(FDWorkEntryError) as mismatch:
        service.validate_case_selection("token-a", "typed text")
    assert mismatch.value.code == "case_selection_mismatch"

    service.open_case_picker("drawer-b")
    _publish_success(coordinator, "drawer-b", "CASE B")
    coordinator.publish_status(navigation_generation=4)
    with pytest.raises(FDWorkEntryError) as stale:
        service.validate_case_selection("token-b", "CASE B")
    assert stale.value.code == "case_selection_expired"


def test_picker_cancel_is_forwarded_only_to_matching_drawer_request():
    service, coordinator, _builder, _state, delivered = _service()
    service.open_case_picker("drawer-current")

    coordinator.publish_picker({
        "ok": False,
        "request_id": "drawer-old",
        "operation_nonce": "nonce",
        "error": "picker_canceled",
    })
    coordinator.publish_picker({
        "ok": False,
        "request_id": "drawer-current",
        "operation_nonce": "nonce",
        "error": "picker_canceled",
    })

    assert delivered == [{
        "ok": False,
        "request_id": "drawer-current",
        "error": "picker_canceled",
    }]


def test_selection_expiry_capacity_and_discard_are_memory_only():
    now = [10.0]
    tokens = iter(["token-1", "token-2", "token-3"])
    service, coordinator, _builder, _state, _delivered = _service(
        clock=lambda: now[0], token_factory=lambda: next(tokens), capacity=2
    )
    for index in range(1, 4):
        request_id = f"drawer-{index}"
        service.open_case_picker(request_id)
        _publish_success(coordinator, request_id, f"CASE {index}")

    with pytest.raises(FDWorkEntryError):
        service.validate_case_selection("token-1", "CASE 1")
    service.discard_case_selection("token-2")
    with pytest.raises(FDWorkEntryError):
        service.validate_case_selection("token-2", "CASE 2")
    now[0] += 301
    with pytest.raises(FDWorkEntryError):
        service.validate_case_selection("token-3", "CASE 3")


def test_entry_uses_pure_builder_then_interaction_coordinator():
    service, coordinator, builder, _state, _delivered = _service()

    result = service.open_entry("2026-08-03", "base:1", "revision")

    assert result["ok"] is True
    assert result["operation_status"] == "save_completed"
    assert result["capability_status"]["session_state"] == "ready"
    assert "status" not in result
    assert builder.calls == [("2026-08-03", "base:1", "revision")]
    assert coordinator.open_calls == [builder.draft]


def test_disable_clears_tokens_and_shutdown_is_permanent():
    service, coordinator, _builder, state, _delivered = _service(
        token_factory=lambda: "token"
    )
    service.open_case_picker("drawer")
    _publish_success(coordinator, "drawer")

    status = service.set_enabled(False)

    assert state["enabled"] is False
    assert coordinator.disable_calls >= 1
    assert status["session_state"] == "disabled"
    with pytest.raises(FDWorkEntryError):
        service.validate_case_selection("token", "CASE A")
    service.shutdown()
    service.shutdown()
    assert coordinator.shutdown_calls == 1
    assert service.get_settings_status()["session_state"] == "shutdown"
