from __future__ import annotations

from pathlib import Path

from worktrace.api import timeline_api


REPO_ROOT = Path(__file__).resolve().parents[1]


def _production_python_sources() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in REPO_ROOT.joinpath("worktrace").rglob("*.py")
    }


def test_activity_service_has_no_legacy_user_edit_write_entries():
    source = REPO_ROOT.joinpath("worktrace", "services", "activity_service.py").read_text(
        encoding="utf-8"
    )
    for symbol in (
        "def update_activity_fields",
        "def _assign_activities_project",
        "def update_activity_project",
        "def update_activity_note",
    ):
        assert symbol not in source
    assert "def update_project_editable_activity_note" not in source
    assert "def update_project_editable_activities_project" not in source


def test_timeline_api_does_not_export_legacy_wrappers():
    exported = set(timeline_api.__all__)
    assert "update_session_note" not in exported
    assert "update_activity_note" not in exported

    source = REPO_ROOT.joinpath("worktrace", "api", "timeline_api.py").read_text(
        encoding="utf-8"
    )
    assert "def update_session_note" not in source
    assert "def update_activity_note" not in source


def test_production_sources_do_not_reintroduce_raw_activity_edit_defs():
    sources = _production_python_sources()
    forbidden = (
        "def update_activity_fields",
        "def _assign_activities_project",
        "def update_activity_project",
        "def update_activity_note",
    )
    offenders = [
        (name, symbol)
        for name, source in sources.items()
        for symbol in forbidden
        if symbol in source
    ]
    assert offenders == []
