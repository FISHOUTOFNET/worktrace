"""Shared transport-safe helpers for WebView bridge mixins."""

from __future__ import annotations

import re
from typing import Any

_GENERIC_ERROR: dict[str, Any] = {"ok": False, "error": "操作失败"}
_RECENT_LIMIT = 20
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


__all__ = [
    "_DATE_SHAPE_RE",
    "_GENERIC_ERROR",
    "_RECENT_LIMIT",
]
