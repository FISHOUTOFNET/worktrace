"""Shared page-level ViewModel presentation helpers."""

from __future__ import annotations

from typing import Any

from . import page_revision_service
from .report_revision_service import get_report_structure_revision


def apply_structure_revision(
    payload: dict[str, Any],
    *,
    report_date: str,
    today: str,
    snapshot=None,
) -> None:
    """Attach the canonical structural revision used by heartbeat refreshes.

    ``snapshot`` remains accepted while page builders are migrated to an
    explicit read context.  It is intentionally not hashed here: page loads
    and heartbeat checks must use the same owner and the same algorithm.
    """

    del snapshot
    payload["structure_revision"] = get_report_structure_revision(report_date)
    page_revision_service.apply_page_revision(
        payload,
        report_date=report_date,
        today=today,
    )

__all__ = ["apply_structure_revision"]
