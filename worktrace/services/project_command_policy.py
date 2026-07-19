"""Stable domain errors for canonical project lifecycle commands."""
from __future__ import annotations


class ProjectLifecycleError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = str(code)


__all__ = ["ProjectLifecycleError"]
