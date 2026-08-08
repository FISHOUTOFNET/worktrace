"""Exclusive interaction ownership for FD Work picker, auth, and fill/save."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Callable, Mapping, Protocol

from .case_identity import normalize_case_label
from .contracts import FDWorkEntryDraft
from .page_adapter import FDWorkPageAdapter


class _WindowController(Protocol):
    def bind_status_callback(self, callback: Callable[[Mapping[str, Any]], None]) -> None: ...
    def bind_close_callback(self, callback: Callable[[int], None]) -> None: ...
    def schedule_callback(self, callback: Callable[[], None]) -> bool: ...
    def get_status(self) -> Mapping[str, Any]: ...
    def prepare_session(self, show_login_if_required: bool = True) -> Mapping[str, Any]: ...
    def prepare_window_before_start(self, show_login_if_required: bool = False) -> Mapping[str, Any]: ...
    def on_renderer_initialized(self, renderer: str) -> None: ...
    def foreground(
        self,
        owner: str,
        operation_generation: int,
        guard: Callable[[], bool],
    ) -> Mapping[str, Any]: ...
    def hide_and_restore_main(
        self,
        navigation_generation: int,
        operation_generation: int,
        guard: Callable[[], bool],
    ) -> None: ...
    def disable(self) -> None: ...
    def shutdown(self) -> None: ...


_OWNER_VALUES = frozenset({"none", "user_auth", "user_picker", "automation_fill"})


class FDWorkInteractionCoordinator:
    """Serialize all user-owned and automation-owned helper interactions."""

    def __init__(
        self,
        *,
        window_controller: _WindowController,
        page_adapter: FDWorkPageAdapter | None = None,
        nonce_factory: Callable[[], str] | None = None,
        picker_result_callback: Callable[[dict[str, Any]], None] | None = None,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
        picker_timeout_seconds: float = 30.0,
        fill_timeout_seconds: float = 15.0,
    ) -> None:
        self._controller = window_controller
        self._page_adapter = page_adapter or FDWorkPageAdapter()
        self._nonce_factory = nonce_factory or (lambda: secrets.token_urlsafe(24))
        self._picker_result_callback = picker_result_callback or (lambda _result: None)
        self._status_callback = status_callback or (lambda _status: None)
        self._picker_timeout_seconds = max(1.0, float(picker_timeout_seconds))
        self._fill_timeout_seconds = max(1.0, float(fill_timeout_seconds))
        self._lock = threading.RLock()
        self._controller_status = dict(window_controller.get_status())
        self._interaction_owner = "none"
        self._operation_generation = 0
        self._operation_nonce: str | None = None
        self._operation_navigation_generation: int | None = None
        self._operation_deadline_ms: int | None = None
        self._active_request_id: str | None = None
        self._pending_picker_request_id: str | None = None
        self._pending_entry_draft: FDWorkEntryDraft | None = None
        self._current_window: Any | None = None
        self._pending_picker_command: tuple[str, str, str, int, int] | None = None
        self._shutdown = False
        self._disabled = False
        window_controller.bind_status_callback(self._accept_controller_status)
        window_controller.bind_close_callback(self._on_helper_closed)

    def bind_status_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._status_callback = callback

    def bind_picker_result_callback(
        self,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        with self._lock:
            self._picker_result_callback = callback

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def prepare_session(self, show_login_if_required: bool = True) -> dict[str, Any]:
        explicit = bool(show_login_if_required)
        if not explicit:
            return dict(self._controller.prepare_session(show_login_if_required=False))
        with self._lock:
            if self._shutdown or self._disabled:
                return {"ok": False, "error": "fd_work_disabled"}
            if self._controller_status.get("ready") is True:
                return {"ok": True, "status": self._status_locked()}
            if self._interaction_owner == "none":
                self._reserve_operation_locked("user_auth", None)
                public_status = self._status_locked()
            elif self._interaction_owner == "user_auth":
                public_status = self._status_locked()
            else:
                return {"ok": False, "error": "fd_work_busy"}
        self._emit_status(public_status)
        try:
            result = dict(self._controller.prepare_session(show_login_if_required=True))
        except Exception:
            result = {"ok": False, "error": "session_start_failed"}
        if result.get("ok") is not True:
            with self._lock:
                if self._interaction_owner == "user_auth":
                    self._clear_operation_locked()
                    public_status = self._status_locked(
                        error_code=str(result.get("error") or "session_start_failed")
                    )
                else:
                    public_status = self._status_locked()
            self._emit_status(public_status)
        return result

    def prepare_window_before_start(
        self,
        show_login_if_required: bool = False,
    ) -> dict[str, Any]:
        if show_login_if_required:
            return self.prepare_session(show_login_if_required=True)
        return dict(
            self._controller.prepare_window_before_start(
                show_login_if_required=False
            )
        )

    def on_renderer_initialized(self, renderer: str) -> None:
        self._controller.on_renderer_initialized(renderer)

    def open_case_picker(self, request_id: str) -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return {"ok": False, "error": "invalid_input"}
        with self._lock:
            if self._shutdown or self._disabled:
                return {"ok": False, "error": "fd_work_disabled"}
            if self._interaction_owner != "none":
                return {"ok": False, "error": "fd_work_busy"}
            status = dict(self._controller_status)
            if status.get("ready") is not True:
                self._pending_picker_request_id = request_id
                self._reserve_operation_locked("user_auth", request_id)
                operation_nonce = self._operation_nonce
                public_status = self._status_locked()
                activate = False
            else:
                self._reserve_operation_locked("user_picker", request_id)
                operation_nonce = self._operation_nonce
                public_status = self._status_locked()
                activate = True
        self._emit_status(public_status)
        if not activate:
            prepared = dict(self._controller.prepare_session(show_login_if_required=True))
            if prepared.get("ok") is not True:
                self._cancel_current_picker(
                    "authentication_failed",
                    restore_main=False,
                )
                return prepared
            return {
                "ok": True,
                "request_id": request_id,
                "operation_nonce": operation_nonce,
                "operation_status": "authentication_required",
            }
        return self._activate_picker()

    def submit_case_picker_confirmation(
        self,
        operation_nonce: str,
        selected_label: str,
        selection_revision: int,
    ) -> dict[str, Any]:
        canonical = normalize_case_label(selected_label)
        if (
            type(operation_nonce) is not str
            or type(selected_label) is not str
            or not canonical
            or type(selection_revision) is not int
            or selection_revision <= 0
        ):
            return {"ok": False, "error": "invalid_picker_callback"}
        with self._lock:
            if not self._picker_is_current_locked(operation_nonce):
                return {"ok": False, "error": "picker_superseded"}
            command = (
                "confirm",
                operation_nonce,
                canonical,
                selection_revision,
                self._operation_generation,
            )
            if self._pending_picker_command is not None:
                if self._pending_picker_command == command:
                    return {"ok": True, "accepted": True}
                return {"ok": False, "error": "picker_superseded"}
            self._pending_picker_command = command
        scheduled = self._controller.schedule_callback(
            lambda: self._complete_submitted_picker_command(command)
        )
        if not scheduled:
            with self._lock:
                if self._pending_picker_command == command:
                    self._pending_picker_command = None
            return {"ok": False, "error": "executor_rejected"}
        return {"ok": True, "accepted": True}

    def submit_case_picker_cancellation(
        self,
        operation_nonce: str,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._picker_is_current_locked(operation_nonce):
                return {"ok": False, "error": "picker_superseded"}
            command = (
                "cancel",
                operation_nonce,
                "",
                0,
                self._operation_generation,
            )
            if self._pending_picker_command is not None:
                if self._pending_picker_command == command:
                    return {"ok": True, "accepted": True}
                return {"ok": False, "error": "picker_superseded"}
            self._pending_picker_command = command
        scheduled = self._controller.schedule_callback(
            lambda: self._complete_submitted_picker_command(command)
        )
        if not scheduled:
            with self._lock:
                if self._pending_picker_command == command:
                    self._pending_picker_command = None
            return {"ok": False, "error": "executor_rejected"}
        return {"ok": True, "accepted": True}

    def open_entry(self, draft: FDWorkEntryDraft) -> dict[str, Any]:
        if not isinstance(draft, FDWorkEntryDraft):
            return {"ok": False, "error": "invalid_input"}
        with self._lock:
            if self._shutdown or self._disabled:
                return {"ok": False, "error": "fd_work_disabled"}
            if self._interaction_owner != "none":
                return {"ok": False, "error": "fd_work_busy"}
            if self._controller_status.get("ready") is not True:
                self._reserve_operation_locked("user_auth", None)
                self._pending_entry_draft = draft
                public_status = self._status_locked()
                activate = False
            else:
                self._reserve_operation_locked("automation_fill", None)
                public_status = self._status_locked()
                activate = True
            operation_nonce = str(self._operation_nonce)
            operation_generation = self._operation_generation
        self._emit_status(public_status)
        if not activate:
            try:
                prepared = dict(
                    self._controller.prepare_session(show_login_if_required=True)
                )
            except Exception:
                prepared = {"ok": False, "error": "session_start_failed"}
            if prepared.get("ok") is not True:
                with self._lock:
                    if self._operation_is_current_locked(
                        "user_auth", operation_nonce, operation_generation
                    ):
                        self._clear_operation_locked()
                        public_status = self._status_locked(
                            error_code=str(
                                prepared.get("error") or "session_start_failed"
                            )
                        )
                    else:
                        public_status = self._status_locked()
                self._emit_status(public_status)
                return prepared
            return {"ok": True, "operation_status": "session_starting"}
        return self._execute_entry(draft, operation_nonce, operation_generation)

    def _execute_entry(
        self,
        draft: FDWorkEntryDraft,
        operation_nonce: str,
        operation_generation: int,
    ) -> dict[str, Any]:
        try:
            context = dict(
                self._controller.foreground(
                    "automation_fill",
                    operation_generation,
                    lambda: self._operation_is_current(
                        "automation_fill", operation_nonce, operation_generation
                    ),
                )
            )
        except Exception:
            context = {"ok": False, "error": "window_unavailable"}
        if context.get("ok") is not True:
            return self._finish_fill_failure(
                str(context.get("error") or "window_unavailable"),
                operation_nonce,
                operation_generation,
            )
        window = context.get("window")
        navigation_generation = context.get("navigation_generation")
        if window is None or type(navigation_generation) is not int:
            return self._finish_fill_failure(
                "window_unavailable", operation_nonce, operation_generation
            )
        with self._lock:
            if not self._operation_is_current_locked(
                "automation_fill", operation_nonce, operation_generation
            ) or self._navigation_generation_locked() != navigation_generation:
                current = False
            else:
                current = True
        if not current:
            return self._finish_fill_failure(
                "lookup_superseded", operation_nonce, operation_generation
            )
        with self._lock:
            self._current_window = window
            self._operation_navigation_generation = navigation_generation
            contract = self._operation_contract_locked(self._fill_timeout_seconds)
        try:
            page_ready = dict(
                self._page_adapter.await_stable_work_page(window, contract)
            )
            if page_ready.get("ok") is not True:
                return self._finish_fill_failure(
                    str(page_ready.get("error") or "work_page_not_ready"),
                    operation_nonce,
                    operation_generation,
                )
            editor = dict(self._page_adapter.ensure_entry_editor(window, contract))
            if editor.get("ok") is not True:
                return self._finish_fill_failure(
                    str(editor.get("error") or "entry_editor_not_rendered"),
                    operation_nonce,
                    operation_generation,
                )
            stable = dict(
                self._page_adapter.await_stable_entry_editor(window, contract)
            )
            if stable.get("ok") is not True:
                return self._finish_fill_failure(
                    str(stable.get("error") or "entry_editor_not_rendered"),
                    operation_nonce,
                    operation_generation,
                )
            if not self._operation_is_current(
                "automation_fill", operation_nonce, operation_generation
            ):
                return {"ok": False, "error": "lookup_superseded"}
            filled = dict(self._page_adapter.fill_entry(window, draft, contract=contract))
        except Exception:
            filled = {"ok": False, "error": "javascript_exception"}
        if filled.get("ok") is not True:
            return self._finish_fill_failure(
                str(filled.get("error") or "dom_contract_changed"),
                operation_nonce,
                operation_generation,
            )
        if filled.get("stage") != "save_completed":
            return self._finish_fill_failure(
                "save_completion_failed",
                operation_nonce,
                operation_generation,
            )
        with self._lock:
            if not self._operation_is_current_locked(
                "automation_fill", operation_nonce, operation_generation
            ):
                return {"ok": False, "error": "lookup_superseded"}
            navigation_generation = self._operation_navigation_generation
        if navigation_generation is not None:
            try:
                self._controller.hide_and_restore_main(
                    navigation_generation,
                    operation_generation,
                    lambda: self._operation_is_current(
                        "automation_fill", operation_nonce, operation_generation
                    ),
                )
            except Exception:
                pass
        with self._lock:
            if not self._operation_is_current_locked(
                "automation_fill", operation_nonce, operation_generation
            ):
                return {"ok": False, "error": "lookup_superseded"}
            self._clear_operation_locked()
            public_status = self._status_locked(
                operation_status="save_completed",
                operation_result_owner="automation_fill",
            )
        self._emit_status(public_status)
        return {"ok": True, "operation_status": "save_completed"}

    def disable(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._disabled = True
            picker_result = self._picker_cancellation_locked("picker_superseded")
            self._clear_operation_locked()
            public_status = self._status_locked()
        if picker_result:
            self._emit_picker_result(picker_result)
        self._controller.disable()
        self._emit_status(public_status)

    def enable(self) -> None:
        with self._lock:
            if not self._shutdown:
                self._disabled = False

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            picker_result = self._picker_cancellation_locked("picker_superseded")
            self._clear_operation_locked()
            public_status = self._status_locked()
        if picker_result:
            self._emit_picker_result(picker_result)
        self._controller.shutdown()
        self._emit_status(public_status)

    def _complete_submitted_picker_command(
        self,
        command: tuple[str, str, str, int, int],
    ) -> None:
        kind, nonce, selected_label, selection_revision, operation_generation = command
        with self._lock:
            if (
                self._pending_picker_command != command
                or not self._operation_is_current_locked(
                    "user_picker",
                    nonce,
                    operation_generation,
                )
            ):
                return
            self._pending_picker_command = None
        if kind == "cancel":
            self._cancel_current_picker("picker_canceled", restore_main=True)
            return
        with self._lock:
            window = self._current_window
            request_id = self._active_request_id
            navigation_generation = self._operation_navigation_generation
            contract = self._operation_contract_locked(self._picker_timeout_seconds)
        if window is None or request_id is None or navigation_generation is None:
            self._finish_submitted_picker_failure(
                nonce,
                operation_generation,
                "picker_superseded",
            )
            return
        try:
            left = dict(self._page_adapter.leave_case_picker(window, contract))
        except Exception:
            left = {"ok": False, "error": "javascript_exception"}
        if left.get("ok") is not True:
            self._finish_submitted_picker_failure(
                nonce,
                operation_generation,
                str(left.get("error") or "dom_contract_changed"),
            )
            return
        self._controller.hide_and_restore_main(
            navigation_generation,
            operation_generation,
            lambda: self._operation_is_current(
                "user_picker",
                nonce,
                operation_generation,
            ),
        )
        picker_result = {
            "ok": True,
            "request_id": request_id,
            "operation_nonce": nonce,
            "navigation_generation": navigation_generation,
            "selection_revision": selection_revision,
            "label": selected_label,
        }
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker",
                nonce,
                operation_generation,
            ):
                return
            self._clear_operation_locked()
            public_status = self._status_locked()
        self._emit_picker_result(picker_result)
        self._emit_status(public_status)

    def _finish_submitted_picker_failure(
        self,
        nonce: str,
        operation_generation: int,
        error: str,
    ) -> None:
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker",
                nonce,
                operation_generation,
            ):
                return
            request_id = self._active_request_id
            navigation_generation = self._operation_navigation_generation
        if navigation_generation is not None:
            self._controller.hide_and_restore_main(
                navigation_generation,
                operation_generation,
                lambda: self._operation_is_current(
                    "user_picker",
                    nonce,
                    operation_generation,
                ),
            )
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker",
                nonce,
                operation_generation,
            ):
                return
            self._clear_operation_locked()
            public_status = self._status_locked(error_code=error)
        if request_id is not None:
            self._emit_picker_result(
                {
                    "ok": False,
                    "request_id": request_id,
                    "operation_nonce": nonce,
                    "error": error,
                }
            )
        self._emit_status(public_status)

    def _activate_picker(self) -> dict[str, Any]:
        with self._lock:
            if self._interaction_owner != "user_picker" or not self._operation_nonce:
                return {"ok": False, "error": "picker_superseded"}
            nonce = self._operation_nonce
            request_id = self._active_request_id
            operation_generation = self._operation_generation
        context = dict(
            self._controller.foreground(
                "user_picker",
                operation_generation,
                lambda: self._operation_is_current(
                    "user_picker", nonce, operation_generation
                ),
            )
        )
        if context.get("ok") is not True:
            self._cancel_current_picker(
                str(context.get("error") or "window_unavailable"),
                restore_main=False,
            )
            return context
        window = context.get("window")
        navigation_generation = context.get("navigation_generation")
        if window is None or type(navigation_generation) is not int:
            self._cancel_current_picker("window_unavailable", restore_main=False)
            return {"ok": False, "error": "window_unavailable"}
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker", nonce, operation_generation
            ) or self._navigation_generation_locked() != navigation_generation:
                current = False
            else:
                current = True
        if not current:
            self._cancel_current_picker("picker_superseded", restore_main=False)
            return {"ok": False, "error": "picker_superseded"}
        with self._lock:
            self._current_window = window
            self._operation_navigation_generation = navigation_generation
            contract = self._operation_contract_locked(self._picker_timeout_seconds)
        try:
            page_ready = dict(
                self._page_adapter.await_stable_work_page(window, contract)
            )
            if page_ready.get("ok") is not True:
                self._cancel_current_picker(
                    str(page_ready.get("error") or "work_page_not_ready"),
                    restore_main=True,
                )
                return page_ready
            editor = dict(self._page_adapter.ensure_entry_editor(window, contract))
            if editor.get("ok") is not True:
                self._cancel_current_picker(
                    str(editor.get("error") or "entry_editor_not_rendered"),
                    restore_main=True,
                )
                return editor
            stable = dict(
                self._page_adapter.await_stable_entry_editor(window, contract)
            )
            if stable.get("ok") is not True:
                self._cancel_current_picker(
                    str(stable.get("error") or "entry_editor_not_rendered"),
                    restore_main=True,
                )
                return stable
            if not self._operation_is_current(
                "user_picker", nonce, operation_generation
            ):
                return {"ok": False, "error": "picker_superseded"}
            entered = dict(self._page_adapter.enter_case_picker(window, contract))
        except Exception:
            entered = {"ok": False, "error": "javascript_exception"}
        if entered.get("ok") is not True:
            self._cancel_current_picker(
                str(entered.get("error") or "dom_contract_changed"),
                restore_main=True,
            )
            return entered
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker", nonce, operation_generation
            ):
                return {"ok": False, "error": "picker_superseded"}
        return {
            "ok": True,
            "request_id": request_id,
            "operation_nonce": nonce,
            "operation_status": "picker_ready",
        }

    def _accept_controller_status(self, status: Mapping[str, Any]) -> None:
        activate_picker = False
        resume_entry: tuple[FDWorkEntryDraft, str, int] | None = None
        complete_auth: tuple[int, int, str] | None = None
        picker_result = None
        terminal_operation_status = None
        terminal_error = None
        with self._lock:
            previous_generation = self._navigation_generation_locked()
            self._controller_status = dict(status)
            current_generation = self._navigation_generation_locked()
            if (
                self._interaction_owner == "user_picker"
                and self._operation_navigation_generation is not None
                and current_generation != self._operation_navigation_generation
            ):
                picker_result = self._picker_cancellation_locked("picker_superseded")
                self._clear_operation_locked()
            elif (
                self._interaction_owner == "user_auth"
                and self._pending_picker_request_id
                and status.get("ready") is True
            ):
                request_id = self._pending_picker_request_id
                self._pending_picker_request_id = None
                self._reserve_operation_locked("user_picker", request_id)
                activate_picker = True
            elif (
                self._interaction_owner == "user_auth"
                and self._pending_entry_draft is not None
                and status.get("ready") is True
            ):
                draft = self._pending_entry_draft
                self._pending_entry_draft = None
                self._reserve_operation_locked("automation_fill", None)
                resume_entry = (
                    draft,
                    str(self._operation_nonce),
                    self._operation_generation,
                )
            elif (
                self._interaction_owner == "user_auth"
                and status.get("ready") is True
                and self._operation_nonce
            ):
                complete_auth = (
                    current_generation,
                    self._operation_generation,
                    self._operation_nonce,
                )
            elif (
                previous_generation != current_generation
                and self._interaction_owner == "automation_fill"
            ):
                closing_window = (
                    status.get("session_state") == "idle"
                    and status.get("page_phase") == "none"
                    and status.get("ready") is False
                )
                if not closing_window:
                    self._clear_operation_locked()
                    terminal_operation_status = "operation_canceled"
                    terminal_error = "lookup_superseded"
            public_status = self._status_locked(
                error_code=terminal_error,
                operation_status=terminal_operation_status,
                operation_result_owner=(
                    "automation_fill" if terminal_operation_status else None
                ),
            )
        if picker_result:
            self._emit_picker_result(picker_result)
        if complete_auth is not None:
            navigation_generation, operation_generation, nonce = complete_auth
            self._controller.hide_and_restore_main(
                navigation_generation,
                operation_generation,
                lambda: self._operation_is_current(
                    "user_auth", nonce, operation_generation
                ),
            )
            with self._lock:
                if self._operation_is_current_locked(
                    "user_auth", nonce, operation_generation
                ):
                    self._clear_operation_locked()
                public_status = self._status_locked()
        self._emit_status(public_status)
        if activate_picker:
            self._activate_picker()
        if resume_entry is not None:
            draft, nonce, operation_generation = resume_entry
            scheduled = self._controller.schedule_callback(
                lambda: self._execute_entry(draft, nonce, operation_generation)
            )
            if not scheduled:
                self._finish_fill_failure(
                    "executor_rejected", nonce, operation_generation
                )

    def _on_helper_closed(self, navigation_generation: int) -> None:
        del navigation_generation
        with self._lock:
            had_operation = self._interaction_owner != "none"
            terminal_owner = self._interaction_owner
            if (
                terminal_owner == "user_auth"
                and self._pending_entry_draft is not None
            ):
                terminal_owner = "automation_fill"
            picker_result = self._picker_cancellation_locked("window_closed")
            self._clear_operation_locked()
            public_status = self._status_locked(
                error_code="window_closed" if had_operation else None,
                operation_status="operation_canceled" if had_operation else None,
                operation_result_owner=terminal_owner if had_operation else None,
            )
        if picker_result:
            self._emit_picker_result(picker_result)
        self._emit_status(public_status)

    def _cancel_current_picker(self, error: str, *, restore_main: bool) -> None:
        with self._lock:
            if self._interaction_owner not in {"user_picker", "user_auth"}:
                return
            picker_result = self._picker_cancellation_locked(error)
            window = self._current_window
            navigation_generation = self._operation_navigation_generation
            operation_generation = self._operation_generation
            nonce = self._operation_nonce
            owner = self._interaction_owner
            contract = self._operation_contract_locked(self._picker_timeout_seconds)
        if window is not None and owner == "user_picker":
            try:
                self._page_adapter.leave_case_picker(window, contract)
            except Exception:
                pass
        if (
            restore_main
            and navigation_generation is not None
            and nonce is not None
        ):
            self._controller.hide_and_restore_main(
                navigation_generation,
                operation_generation,
                lambda: self._picker_is_current(nonce),
            )
        with self._lock:
            self._clear_operation_locked()
            public_status = self._status_locked()
        if picker_result:
            self._emit_picker_result(picker_result)
        self._emit_status(public_status)

    def _finish_fill_failure(
        self,
        error: str,
        operation_nonce: str,
        operation_generation: int,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._operation_is_current_locked(
                "automation_fill", operation_nonce, operation_generation
            ):
                return {"ok": False, "error": error}
            self._clear_operation_locked()
            operation_status = (
                "operation_canceled"
                if error in {"window_closed", "lookup_superseded", "navigation_changed"}
                else "failed"
            )
            public_status = self._status_locked(
                error_code=error,
                operation_status=operation_status,
                operation_result_owner="automation_fill",
            )
        self._emit_status(public_status)
        return {"ok": False, "error": error}

    def _reserve_operation_locked(self, owner: str, request_id: str | None) -> None:
        if owner not in _OWNER_VALUES or owner == "none":
            raise ValueError("invalid_interaction_owner")
        self._operation_generation += 1
        self._interaction_owner = owner
        self._operation_nonce = str(self._nonce_factory())
        self._operation_navigation_generation = None
        self._operation_deadline_ms = None
        self._active_request_id = request_id
        self._current_window = None
        self._pending_picker_command = None
        self._pending_entry_draft = None

    def _clear_operation_locked(self) -> None:
        self._operation_generation += 1
        self._interaction_owner = "none"
        self._operation_nonce = None
        self._operation_navigation_generation = None
        self._operation_deadline_ms = None
        self._active_request_id = None
        self._pending_picker_request_id = None
        self._pending_entry_draft = None
        self._current_window = None
        self._pending_picker_command = None

    def _operation_contract_locked(self, timeout_seconds: float) -> dict[str, Any]:
        if self._operation_deadline_ms is None:
            self._operation_deadline_ms = int(
                time.time() * 1000 + max(0.01, float(timeout_seconds)) * 1000
            )
        return {
            "operation_nonce": str(self._operation_nonce or ""),
            "operation_generation": self._operation_generation,
            "navigation_generation": int(self._operation_navigation_generation or 0),
            "timeout_seconds": float(timeout_seconds),
            "operation_deadline_ms": self._operation_deadline_ms,
        }

    def _picker_is_current(self, nonce: str) -> bool:
        with self._lock:
            return self._picker_is_current_locked(nonce)

    def _picker_is_current_locked(self, nonce: str) -> bool:
        return bool(
            not self._shutdown
            and not self._disabled
            and self._interaction_owner == "user_picker"
            and self._operation_nonce == nonce
        )

    def _operation_is_current(self, owner: str, nonce: str, generation: int) -> bool:
        with self._lock:
            return self._operation_is_current_locked(owner, nonce, generation)

    def _operation_is_current_locked(
        self,
        owner: str,
        nonce: str,
        generation: int,
    ) -> bool:
        return bool(
            not self._shutdown
            and not self._disabled
            and self._interaction_owner == owner
            and self._operation_nonce == nonce
            and self._operation_generation == generation
        )

    def _picker_cancellation_locked(self, error: str) -> dict[str, Any] | None:
        request_id = self._active_request_id or self._pending_picker_request_id
        nonce = self._operation_nonce
        if not request_id or self._interaction_owner not in {"user_auth", "user_picker"}:
            return None
        return {
            "ok": False,
            "request_id": request_id,
            "operation_nonce": str(nonce or ""),
            "error": error,
        }

    def _navigation_generation_locked(self) -> int:
        value = self._controller_status.get("navigation_generation")
        return int(value) if type(value) is int else 0

    def _status_locked(
        self,
        *,
        error_code: str | None = None,
        operation_status: str | None = None,
        operation_result_owner: str | None = None,
    ) -> dict[str, Any]:
        status = dict(self._controller_status)
        status["interaction_owner"] = self._interaction_owner
        status["operation"] = self._interaction_owner
        status["operation_generation"] = self._operation_generation
        status["operation_nonce"] = self._operation_nonce
        if operation_status:
            status["operation_status"] = operation_status
            if operation_result_owner in _OWNER_VALUES - {"none"}:
                status["operation_result_owner"] = operation_result_owner
        elif self._interaction_owner != "none":
            status["operation_status"] = "pending"
        if error_code:
            status["error_code"] = error_code
        return status

    def _emit_status(self, status: Mapping[str, Any]) -> None:
        try:
            self._status_callback(dict(status))
        except Exception:
            pass

    def _emit_picker_result(self, picker_result: Mapping[str, Any]) -> None:
        try:
            self._picker_result_callback(dict(picker_result))
        except Exception:
            pass


__all__ = ["FDWorkInteractionCoordinator"]
