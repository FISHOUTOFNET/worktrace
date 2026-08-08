"""FD Work internal-to-public error boundary."""

from __future__ import annotations


_PAGE_ERRORS = frozenset(
    {
        "adapter_injection_failed",
        "adapter_missing",
        "adapter_version_mismatch",
        "case_aria_controls_missing",
        "case_input_missing",
        "case_input_not_interactive",
        "case_input_not_rendered",
        "case_popup_not_created",
        "case_popup_not_interactive",
        "case_query_not_applied",
        "case_results_stale",
        "date_change_failed",
        "date_control_missing",
        "date_verification_failed",
        "dom_contract_changed",
        "duration_verification_failed",
        "entry_verification_failed",
        "javascript_exception",
        "narrative_verification_failed",
        "navigation_changed",
        "non_mapping_result",
        "page_contract_changed",
    }
)
_TIMEOUT_ERRORS = frozenset(
    {
        "callback_timeout",
        "case_results_timeout",
        "case_search_timeout",
        "page_operation_timeout",
        "session_start_timeout",
        "work_shell_timeout",
    }
)
_WINDOW_ERRORS = frozenset(
    {
        "executor_rejected",
        "guard_rejected",
        "renderer_unavailable",
        "session_starting",
        "window_closed",
        "window_unavailable",
    }
)


def public_fd_work_error(error: object) -> str:
    """Return the stable public code for a potentially internal failure kind."""

    code = str(error or "")
    if code in _PAGE_ERRORS:
        return "fd_work_page_unavailable"
    if code in _TIMEOUT_ERRORS:
        return "fd_work_operation_timeout"
    if code in _WINDOW_ERRORS:
        return "fd_work_window_unavailable"
    return code or "fd_work_page_unavailable"


__all__ = ["public_fd_work_error"]
