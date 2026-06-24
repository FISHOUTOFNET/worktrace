"""API-level exception types.

The service layer currently raises ``ValueError`` or SQLite errors. These
API-specific exception classes are defined so the API boundary can grow its own
error vocabulary without changing existing service behaviour. Facades do not
wrap existing service exceptions yet; they are reserved for future use.
"""

from __future__ import annotations


class ApiError(Exception):
    """Base class for API-layer errors."""


class NotFoundError(ApiError):
    """Raised when a requested resource does not exist."""


class ValidationError(ApiError):
    """Raised when input validation fails at the API boundary."""


class StateError(ApiError):
    """Raised when an operation is not valid for the current runtime state."""


__all__ = ["ApiError", "NotFoundError", "StateError", "ValidationError"]
