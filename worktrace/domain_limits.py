"""Shared durable-domain limits used by every ingress boundary."""

NOTE_MAX_LENGTH = 2000
ADJUSTED_DURATION_MAX_SECONDS = 24 * 60 * 60

__all__ = ["ADJUSTED_DURATION_MAX_SECONDS", "NOTE_MAX_LENGTH"]
