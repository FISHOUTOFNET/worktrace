"""Closed-operation Windows probe helper executed in a disposable subprocess."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_ALLOWED_OPERATIONS = {"com_path", "open_files"}
_COM_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_COM_PATH_EXPRESSION = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\(\))?"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\(\))?)*$"
)


def _payload(argv: list[str]) -> tuple[str, dict[str, Any]]:
    if len(argv) != 2 or argv[0] not in _ALLOWED_OPERATIONS:
        raise ValueError("invalid_probe_operation")
    raw = json.loads(argv[1])
    if not isinstance(raw, dict):
        raise ValueError("invalid_probe_payload")
    return argv[0], raw


def _open_files(payload: dict[str, Any]) -> list[str]:
    pid = int(payload.get("pid") or 0)
    if pid <= 0:
        raise ValueError("invalid_probe_pid")
    import psutil

    return [str(item.path) for item in psutil.Process(pid).open_files()]


def _com_path(payload: dict[str, Any]) -> str | None:
    prog_id = str(payload.get("prog_id") or "").strip()
    expression = str(payload.get("expression") or "").strip()
    if not _COM_IDENTIFIER.fullmatch(prog_id):
        raise ValueError("invalid_probe_prog_id")
    if not _COM_PATH_EXPRESSION.fullmatch(expression) or "__" in expression:
        raise ValueError("invalid_probe_expression")

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        value: Any = win32com.client.GetActiveObject(prog_id)
        for raw_step in expression.split("."):
            if raw_step.endswith("()"):
                value = getattr(value, raw_step[:-2])()
            else:
                value = getattr(value, raw_step)
            if value is None:
                return None
        text = str(value or "").strip().strip("\"'“”‘’")
        return text or None
    finally:
        pythoncom.CoUninitialize()


def execute(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "open_files":
        return _open_files(payload)
    if operation == "com_path":
        return _com_path(payload)
    raise ValueError("invalid_probe_operation")


def main(argv: list[str] | None = None) -> int:
    try:
        operation, payload = _payload(list(sys.argv[1:] if argv is None else argv))
        result = execute(operation, payload)
        print(json.dumps({"ok": True, "value": result}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__},
                ensure_ascii=True,
            ),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["execute", "main"]
