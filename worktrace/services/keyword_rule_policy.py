"""Canonical keyword-rule identity and write errors."""
from __future__ import annotations


class ProjectRuleWriteError(ValueError):
    """Stable domain error emitted by canonical rule commands."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = str(code)


def normalize_keyword_pattern(value: object) -> str:
    """Return the sole durable identity for one keyword pattern."""

    return str(value or "").strip().casefold()


__all__ = ["ProjectRuleWriteError", "normalize_keyword_pattern"]
