"""Private contracts for constructing an FD Work entry draft."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FDWorkEntryDraft:
    """The only WorkTrace facts allowed to cross into the FD Work page."""

    work_date: str
    case_label: str
    case_query: str
    duration_hours: str
    narrative: str


@dataclass(frozen=True)
class FDWorkEntryRequest:
    """Timeline identity and optimistic-version contract from the local UI."""

    report_date: str
    projection_instance_key: str
    expected_projection_revision: str


class FDWorkEntryError(ValueError):
    """Fail-closed domain error with a privacy-safe public code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


__all__ = ["FDWorkEntryDraft", "FDWorkEntryError", "FDWorkEntryRequest"]
