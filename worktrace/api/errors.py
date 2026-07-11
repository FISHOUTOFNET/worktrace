"""API-level exception types.

The service layer currently raises ``ValueError`` or SQLite errors. These
API-specific exception classes are defined so the API boundary can grow its own
error vocabulary without changing existing service behaviour. Facades do not
wrap existing service exceptions yet; they are reserved for future use.
"""

from __future__ import annotations

import sqlite3


INVALID_INPUT = "invalid_input"
STALE_SELECTION = "stale_selection"
REVISION_CONFLICT = "revision_conflict"
DATABASE_BUSY = "database_busy"
PROJECT_NOT_SELECTABLE = "project_not_selectable"
OPERATION_NOT_ALLOWED = "operation_not_allowed"
OPERATION_FAILED = "operation_failed"


class ApiError(Exception):
    """Base class for API-layer errors."""


class NotFoundError(ApiError):
    """Raised when a requested resource does not exist."""


class ValidationError(ApiError):
    """Raised when input validation fails at the API boundary."""


class StateError(ApiError):
    """Raised when an operation is not valid for the current runtime state."""


def error_code_from_exception(exc: BaseException) -> str:
    if isinstance(exc, sqlite3.Error):
        code = getattr(exc, "sqlite_errorname", "")
        text = str(exc).lower()
        if code in {"SQLITE_BUSY", "SQLITE_LOCKED"} or "database is locked" in text or "database is busy" in text:
            return DATABASE_BUSY
        return OPERATION_FAILED
    if isinstance(exc, ValueError):
        value = str(exc)
        if value in {STALE_SELECTION, REVISION_CONFLICT, PROJECT_NOT_SELECTABLE}:
            return value
        if value in {
            "not_project_activity",
            "not_mergeable",
            "copy_session_not_mergeable",
            "in_progress",
            "not_merge_session",
        }:
            return OPERATION_NOT_ALLOWED
        if value == "session_identity_conflict":
            return STALE_SELECTION
        return INVALID_INPUT
    return OPERATION_FAILED


def public_message_for_code(code: str) -> str:
    return {
        INVALID_INPUT: "输入无效",
        STALE_SELECTION: "活动时段已更新，请重新确认。",
        REVISION_CONFLICT: "该时段已更新，请确认后重试。",
        DATABASE_BUSY: "数据库正忙，请稍后重试。",
        PROJECT_NOT_SELECTABLE: "请选择有效的项目。",
        OPERATION_NOT_ALLOWED: "当前活动时段不支持该操作。",
        OPERATION_FAILED: "操作失败，请刷新后重试。",
    }.get(code, "操作失败，请刷新后重试。")


__all__ = [
    "ApiError",
    "DATABASE_BUSY",
    "INVALID_INPUT",
    "NotFoundError",
    "OPERATION_FAILED",
    "OPERATION_NOT_ALLOWED",
    "PROJECT_NOT_SELECTABLE",
    "REVISION_CONFLICT",
    "STALE_SELECTION",
    "StateError",
    "ValidationError",
    "error_code_from_exception",
    "public_message_for_code",
]
