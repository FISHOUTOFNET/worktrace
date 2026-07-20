"""Explicit current-only binding contract for immutable report operation replay."""

from __future__ import annotations

from enum import StrEnum


class ReplayBinding(StrEnum):
    REVISION = "revision"
    MEMBERS = "members"


__all__ = ["ReplayBinding"]
