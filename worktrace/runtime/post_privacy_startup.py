"""Single coordinator for collector and plugin startup after privacy consent."""

from __future__ import annotations

import threading
from typing import Any, Callable, Protocol

from ..services import privacy_gate_service


class PostPrivacyParticipant(Protocol):
    def set_privacy_authorized(self, authorized: bool) -> None: ...

    def prepare_after_privacy(self, *, pre_start: bool) -> None: ...


class PostPrivacyStartupCoordinator:
    def __init__(
        self,
        app_control,
        participants: tuple[PostPrivacyParticipant, ...],
        *,
        privacy_authorized_reader: Callable[[], bool] = (
            privacy_gate_service.is_sensitive_runtime_allowed
        ),
    ) -> None:
        self._app_control = app_control
        self._participants = participants
        self._lock = threading.RLock()
        self._privacy_authorized_reader = privacy_authorized_reader
        self._started = False
        self._result: dict[str, Any] | None = None

    def start_if_authorized(self, *, pre_start: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._started and self._result is not None:
                return dict(self._result)
            result = dict(self._app_control.start_collection_after_privacy_gate())
            authorized = self._privacy_authorized()
            if not authorized:
                self._set_participants_authorized(False)
                self._result = result
                return result
            self._set_participants_authorized(True)
            self._prepare_participants(pre_start=pre_start)
            self._started = True
            self._result = result
            return dict(result)

    def accept_privacy_notice_and_start(self) -> dict[str, Any]:
        with self._lock:
            if self._started and self._result is not None:
                return dict(self._result)
            result = dict(self._app_control.accept_privacy_notice_and_start())
            if result.get("accepted") is not True:
                self._set_participants_authorized(False)
                return result
            self._set_participants_authorized(True)
            self._prepare_participants(pre_start=False)
            self._started = True
            self._result = dict(result)
            return result

    def _privacy_authorized(self) -> bool:
        try:
            return self._privacy_authorized_reader() is True
        except Exception:
            return False

    def _set_participants_authorized(self, authorized: bool) -> None:
        for participant in self._participants:
            try:
                participant.set_privacy_authorized(authorized)
            except Exception:
                continue

    def _prepare_participants(self, *, pre_start: bool) -> None:
        for participant in self._participants:
            try:
                participant.prepare_after_privacy(pre_start=pre_start)
            except Exception:
                continue

    def get_collection_status(self):
        return self._app_control.get_collection_status()

    def is_collection_active(self) -> bool:
        """Expose the base runtime collection-state projection through the coordinator."""
        return bool(self._app_control.is_collection_active())

    def toggle_collection(self):
        return self._app_control.toggle_collection()

    def set_clipboard_capture_policy(self, enabled):
        return self._app_control.set_clipboard_capture_policy(enabled)

    def request_shutdown(self) -> None:
        self._app_control.request_shutdown()


__all__ = ["PostPrivacyParticipant", "PostPrivacyStartupCoordinator"]
