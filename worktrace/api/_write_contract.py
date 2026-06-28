"""Shared write-path contract helpers for Project Rules API facades.

These helpers centralize the input validation, stable fail payload, and
narrow success payload patterns used by both ``rule_api`` (keyword / folder
rule facades) and ``project_api`` (project lifecycle facades). They are
intentionally tiny and dependency-free so the contract stays identical
across every Project Rules write path, and so a future facade does not
re-invent (and subtly break) the same validation / error-mapping logic.

Design notes
------------

- ``type(x) is int`` rejects ``bool`` (since ``type(True) is bool``, not
  ``int``), ``float``, ``str``, ``None``, and container types in one check.
  This is the "true positive int" validation.
- ``type(x) is bool`` is the only check that accepts ``True`` / ``False``
  and rejects everything else (``0`` / ``1`` / ``"true"`` / ``None``).
- ``type(x) is str`` rejects ``bool`` / ``int`` / ``float`` / ``None`` /
  container types so a non-string never reaches the service.
- The fail payload is always ``{"ok": False, "error": code}``; the success
  payload is always ``{"ok": True, ...}``. Codes are stable strings the
  WebView bridge maps to Chinese text.

This module is the M2 single source of truth for the Project Rules write
contract. It must NOT import services / db / collector / security / runtime
/ config; it is pure stdlib so it can be imported from any API facade
without creating a layering cycle.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Stable error codes.
# ---------------------------------------------------------------------------
# Centralizing the code literals here makes a typo surface as ``NameError``
# at import time instead of silently producing an unmapped bridge error.

ERROR_INVALID_INPUT = "invalid_input"
ERROR_NOT_FOUND = "not_found"
ERROR_PROJECT_NOT_FOUND = "project_not_found"
ERROR_DUPLICATE_RULE = "duplicate_rule"
ERROR_DUPLICATE_PROJECT = "duplicate_project"
ERROR_SYSTEM_PROJECT = "system_project"
ERROR_OPERATION_FAILED = "operation_failed"
# Phase 5H: rule impact preview / safe single-rule backfill stable codes.
ERROR_RULE_DISABLED = "rule_disabled"
ERROR_PROJECT_NOT_AVAILABLE = "project_not_available"
ERROR_TOO_MANY_MATCHES = "too_many_matches"


# ---------------------------------------------------------------------------
# Input validators.
# ---------------------------------------------------------------------------


def valid_int(value: Any) -> bool:
    """Return True if ``value`` is a real positive ``int`` (bool rejected).

    ``type(value) is int`` rejects ``bool`` (since ``type(True) is bool``,
    not ``int``), ``float``, ``str``, ``None``, and container types in one
    check. ``value > 0`` rejects zero / negative ids.
    """
    return type(value) is int and value > 0


def valid_bool(value: Any) -> bool:
    """Return True if ``value`` is a real ``bool`` (``True`` / ``False`` only).

    ``type(value) is bool`` rejects ``0`` / ``1`` / numeric strings / ``None``
    / container types. The Project Rules write path never accepts truthy
    non-bools as enabled / recursive flags.
    """
    return type(value) is bool


def valid_str(value: Any) -> bool:
    """Return True if ``value`` is a real ``str``.

    ``type(value) is str`` rejects ``bool`` / ``int`` / ``float`` / ``None``
    / container types so a non-string never reaches the service.
    """
    return type(value) is str


def valid_nonempty_str(value: Any) -> str | None:
    """Return the trimmed string if ``value`` is a real non-empty ``str``
    after trim, otherwise ``None``.

    Returning the trimmed string lets the caller avoid a second ``.strip()``
    call and avoids the "trim twice" pattern that previously appeared in
    each facade. ``None`` is the single sentinel for "reject as
    ``invalid_input``"; callers do not need to distinguish "not a str"
    from "empty after trim".
    """
    if type(value) is not str:
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


# ---------------------------------------------------------------------------
# Stable payload builders.
# ---------------------------------------------------------------------------


def fail_payload(code: str) -> dict[str, Any]:
    """Return the stable Project Rules write fail payload.

    Shape is always ``{"ok": False, "error": code}``. The bridge maps
    ``code`` to a Chinese message; it never sees a traceback, SQL, or raw
    field here.
    """
    return {"ok": False, "error": code}


def ok_payload(**fields: Any) -> dict[str, Any]:
    """Return the stable Project Rules write success payload with the given
    fields merged under the ``ok: True`` envelope.

    Shape is always ``{"ok": True, ...fields}``. Callers pass the
    facade-specific narrowed payload (``rule=...`` / ``project=...`` /
    ``rule_type=...`` etc.) as keyword arguments so the success shape stays
    identical to the pre-helper shape.
    """
    payload: dict[str, Any] = {"ok": True}
    payload.update(fields)
    return payload


__all__ = [
    "ERROR_DUPLICATE_PROJECT",
    "ERROR_DUPLICATE_RULE",
    "ERROR_INVALID_INPUT",
    "ERROR_NOT_FOUND",
    "ERROR_OPERATION_FAILED",
    "ERROR_PROJECT_NOT_AVAILABLE",
    "ERROR_PROJECT_NOT_FOUND",
    "ERROR_RULE_DISABLED",
    "ERROR_SYSTEM_PROJECT",
    "ERROR_TOO_MANY_MATCHES",
    "fail_payload",
    "ok_payload",
    "valid_bool",
    "valid_int",
    "valid_nonempty_str",
    "valid_str",
]
