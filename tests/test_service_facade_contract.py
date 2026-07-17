from __future__ import annotations

import pytest

from worktrace.services import recovery_service

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_facade_attribute_replacement_is_visible_to_core(monkeypatch):
    marker = object()
    monkeypatch.setattr(recovery_service, "repair_missing_activity_resources", marker)
    assert recovery_service._core.repair_missing_activity_resources is marker
