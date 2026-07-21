"""Explicit current-only binding contract for immutable report operation replay.

The replay contract is current-only and members-only. Legacy ``"revision"``
bindings are rejected at every ingress (repository read boundary, runtime
engine payload validation, secure backup staging validation) because they
rely on retired replay semantics that allowed durable replay to dispatch by
``projection_revision`` match alone.
"""

from __future__ import annotations

from enum import StrEnum


class ReplayBinding(StrEnum):
    MEMBERS = "members"


__all__ = ["ReplayBinding"]
