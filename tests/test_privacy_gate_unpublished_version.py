from worktrace import privacy_policy
from worktrace.services import privacy_gate_service


def test_unpublished_policy_keeps_internal_version_one() -> None:
    assert privacy_policy.PRIVACY_POLICY_VERSION == "1"
    assert privacy_gate_service.PRIVACY_NOTICE_VERSION == "1"


def test_unpublished_version_two_acceptance_is_normalized_to_one(monkeypatch) -> None:
    persisted: list[str] = []
    monkeypatch.setattr(
        privacy_gate_service,
        "get_privacy_notice_version",
        lambda: "2",
    )
    monkeypatch.setattr(
        privacy_gate_service,
        "set_privacy_notice_version",
        persisted.append,
    )

    assert privacy_gate_service.is_privacy_notice_accepted() is True
    assert persisted == ["1"]


def test_unknown_privacy_version_still_requires_acceptance(monkeypatch) -> None:
    persisted: list[str] = []
    monkeypatch.setattr(
        privacy_gate_service,
        "get_privacy_notice_version",
        lambda: "unexpected",
    )
    monkeypatch.setattr(
        privacy_gate_service,
        "set_privacy_notice_version",
        persisted.append,
    )

    assert privacy_gate_service.is_privacy_notice_accepted() is False
    assert persisted == []
