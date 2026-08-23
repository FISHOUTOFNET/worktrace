from __future__ import annotations

import pytest

from worktrace.runtime.post_privacy_startup import PostPrivacyStartupCoordinator

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]


class FakeAppControl:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.calls = 0

    def is_collection_active(self) -> bool:
        self.calls += 1
        return self.active


def test_post_privacy_coordinator_delegates_collection_active_state() -> None:
    base = FakeAppControl(active=True)
    coordinator = PostPrivacyStartupCoordinator(
        base,
        participants=(),
        privacy_authorized_reader=lambda: False,
    )

    assert coordinator.is_collection_active() is True
    assert base.calls == 1

    base.active = False
    assert coordinator.is_collection_active() is False
    assert base.calls == 2
