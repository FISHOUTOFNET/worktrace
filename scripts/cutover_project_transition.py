from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def path(relative: str) -> Path:
    return ROOT / relative


def read(relative: str) -> str:
    return path(relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    path(relative).write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_exact(relative: str, old: str, new: str, *, count: int = 1) -> None:
    content = read(relative)
    actual = content.count(old)
    if actual != count:
        raise RuntimeError(f"{relative}: expected {count} occurrences, found {actual}: {old[:80]!r}")
    write(relative, content.replace(old, new))


def regex_replace(relative: str, pattern: str, replacement: str, *, count: int = 1) -> None:
    content = read(relative)
    updated, actual = re.subn(pattern, replacement, content, count=count, flags=re.MULTILINE | re.DOTALL)
    if actual != count:
        raise RuntimeError(f"{relative}: expected {count} regex matches, found {actual}: {pattern[:80]!r}")
    write(relative, updated)


PROJECT_OWNERSHIP_SERVICE = r'''"""Project ownership state — internal candidate and official display label."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from .project_attribution_policy import is_official_project_source


@dataclass(frozen=True)
class ProjectLabel:
    """Display-safe project label.

    ``id`` is ``None`` for suggested-project names and uncategorized
    candidates. Only manual/folder/keyword sources are formal display projects.
    """

    name: str
    id: int | None = None
    description: str = ""
    source: str = "uncategorized"
    is_uncategorized: bool = False
    is_suggested_project: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectLabel | None":
        if not data or not isinstance(data, dict):
            return None
        return cls(
            name=str(data.get("name") or "").strip() or UNCATEGORIZED_PROJECT,
            id=int(data["id"]) if data.get("id") is not None else None,
            description=str(data.get("description") or ""),
            source=str(data.get("source") or "uncategorized"),
            is_uncategorized=bool(data.get("is_uncategorized", False)),
            is_suggested_project=bool(data.get("is_suggested_project", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "is_uncategorized": self.is_uncategorized,
            "is_suggested_project": self.is_suggested_project,
        }


@dataclass(frozen=True)
class ProjectOwnershipState:
    """Internal ownership state held by ``ActivitySessionRecorder``.

    ``candidate_project`` remains internal inference state. Runtime snapshots and
    page DTOs expose only ``display_project``.
    """

    display_project: ProjectLabel | None = None
    candidate_project: ProjectLabel | None = None


def uncategorized_label() -> ProjectLabel:
    return ProjectLabel(
        name=UNCATEGORIZED_PROJECT,
        id=None,
        description="",
        source="uncategorized",
        is_uncategorized=True,
        is_suggested_project=False,
    )


def labels_equal(a: ProjectLabel | None, b: ProjectLabel | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a.id is not None and b.id is not None:
        return int(a.id) == int(b.id)
    return a.name.strip().casefold() == b.name.strip().casefold()


def candidate_project_for_activity(
    activity: dict | None,
    resource: Any = None,
) -> ProjectLabel:
    if activity is None:
        return uncategorized_label()
    status = str(activity.get("status") or "")
    if status and status != "normal":
        return uncategorized_label()
    from .project_inference_service import candidate_project_label_for_activity

    label_dict = candidate_project_label_for_activity(activity, _resource_dict(resource))
    return ProjectLabel.from_dict(label_dict) or uncategorized_label()


def _resource_dict(resource: Any) -> dict | None:
    if resource is None:
        return None
    if isinstance(resource, dict):
        return resource
    try:
        return {
            "resource_kind": resource.resource_kind,
            "resource_subtype": resource.resource_subtype,
            "display_name": resource.display_name,
            "identity_key": resource.identity_key,
            "is_anchor": int(resource.is_anchor),
            "app_name": resource.app_name,
            "process_name": resource.process_name,
            "window_title": resource.window_title,
            "path_hint": resource.path_hint,
            "uri_host": resource.uri_host,
        }
    except AttributeError:
        return None


def _is_official_label(label: ProjectLabel | None) -> bool:
    return bool(label is not None and is_official_project_source(label.source))


def begin_ownership_for_new_resource(candidate: ProjectLabel) -> ProjectOwnershipState:
    """Assign the formal display project immediately for an official candidate."""

    if _is_official_label(candidate):
        return ProjectOwnershipState(
            display_project=candidate,
            candidate_project=candidate,
        )
    return ProjectOwnershipState(
        display_project=uncategorized_label(),
        candidate_project=candidate,
    )


def clear_ownership_state() -> ProjectOwnershipState:
    return ProjectOwnershipState()


def empty_state() -> ProjectOwnershipState:
    return ProjectOwnershipState()


__all__ = [
    "ProjectLabel",
    "ProjectOwnershipState",
    "begin_ownership_for_new_resource",
    "candidate_project_for_activity",
    "clear_ownership_state",
    "empty_state",
    "labels_equal",
    "uncategorized_label",
]
'''


SNAPSHOT_PUBLISHER = r'''from __future__ import annotations

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from ..contracts.live_display_contracts import ActivitySnapshotContract
from ..resources.types import DetectedResource
from ..services.project_ownership_service import ProjectOwnershipState, uncategorized_label
from ..services.runtime_activity_state_service import (
    clear_runtime_activity_state,
    get_runtime_activity_snapshot,
    publish_runtime_activity_snapshot,
)
from .transition_types import seconds_between

SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


class SnapshotPublisher:
    """Sole publisher of the process-local, display-safe activity sample."""

    def publish(
        self,
        *,
        payload: dict | None,
        start_time: str | None,
        at_time: str,
        project_ownership_state: ProjectOwnershipState | None,
        persisted_activity_id: int | None,
    ) -> None:
        if payload is None or start_time is None:
            self.clear()
            return

        elapsed = seconds_between(start_time, at_time)
        resource = payload.get("resource")
        resource_display_name = ""
        resource_kind = ""
        resource_subtype = ""
        resource_identity_key = ""
        if isinstance(resource, DetectedResource):
            resource_display_name = resource.display_name
            resource_kind = resource.resource_kind
            resource_subtype = resource.resource_subtype
            resource_identity_key = resource.identity_key

        activity_display_name = resource_display_name
        if not activity_display_name:
            activity_display_name = payload.get("app_name") or payload.get("process_name") or ""
        status = payload.get("status") or STATUS_NORMAL

        ownership = project_ownership_state
        if (
            status in SYSTEM_STATUSES
            or ownership is None
            or ownership.display_project is None
        ):
            display_label = uncategorized_label()
        else:
            display_label = ownership.display_project

        snapshot: ActivitySnapshotContract = {
            "app_name": payload.get("app_name") or "",
            "process_name": payload.get("process_name") or "",
            "activity_display_name": activity_display_name,
            "resource_kind": resource_kind,
            "resource_subtype": resource_subtype,
            "resource_display_name": resource_display_name,
            "resource_identity_key": resource_identity_key,
            "status": status,
            "start_time": start_time,
            "elapsed_seconds": elapsed,
            "persisted_activity_id": persisted_activity_id,
            "is_persisted": persisted_activity_id is not None,
            "display_project": display_label.to_dict(),
        }
        publish_runtime_activity_snapshot(snapshot, "collector_snapshot_publish")

    def clear(self, reason: str = "snapshot_clear") -> None:
        clear_runtime_activity_state(
            reason,
            clear_snapshot=True,
            clear_ownership=False,
        )

    def read(self) -> ActivitySnapshotContract | None:
        value = get_runtime_activity_snapshot()
        return value if isinstance(value, dict) else None


DEFAULT_SNAPSHOT_PUBLISHER = SnapshotPublisher()
'''


LIVE_TIME_SERVICE = r'''from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta

from ..constants import TIME_FORMAT
from ..contracts.live_display_contracts import ActivitySnapshotContract

MAX_LIVE_DURATION_SECONDS = 36 * 60 * 60


def snapshot_elapsed_seconds(
    snapshot: ActivitySnapshotContract | None,
    now: datetime | None = None,
) -> int:
    """Return the elapsed seconds stored in the collector snapshot."""

    del now
    if not snapshot:
        return 0
    return safe_int(snapshot.get("elapsed_seconds"))


def snapshot_total_seconds(
    snapshot: ActivitySnapshotContract | None,
    now: datetime | None = None,
) -> int:
    return snapshot_elapsed_seconds(snapshot, now=now)


def snapshot_current_seconds(
    snapshot: ActivitySnapshotContract | None,
    now: datetime | None = None,
) -> int:
    return snapshot_elapsed_seconds(snapshot, now=now)


def snapshot_seconds_for_date_range(
    snapshot: ActivitySnapshotContract | None,
    start_date: str,
    end_date: str,
    now: datetime | None = None,
) -> int:
    if not snapshot:
        return 0
    start_dt = snapshot_start_time(snapshot)
    if start_dt is None:
        return 0
    total_seconds = snapshot_total_seconds(snapshot, now=now)
    if total_seconds <= 0:
        return 0
    try:
        range_start_date = date.fromisoformat(start_date)
        range_end_date = date.fromisoformat(end_date)
    except ValueError:
        return 0
    range_start = datetime.combine(range_start_date, datetime_time.min)
    range_end = datetime.combine(range_end_date + timedelta(days=1), datetime_time.min)
    activity_end = start_dt + timedelta(seconds=total_seconds)
    overlap_start = max(start_dt, range_start)
    overlap_end = min(activity_end, range_end)
    return max(0, int((overlap_end - overlap_start).total_seconds()))


def snapshot_start_time(snapshot: ActivitySnapshotContract | None) -> datetime | None:
    if not snapshot:
        return None
    start_text = str(snapshot.get("start_time") or "").strip()
    if not start_text:
        return None
    try:
        return datetime.strptime(start_text, TIME_FORMAT)
    except ValueError:
        return None


def snapshot_persisted_id(snapshot: ActivitySnapshotContract | None) -> int | None:
    value = safe_int((snapshot or {}).get("persisted_activity_id"))
    return value or None


def safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
'''


PROJECT_OWNERSHIP_TEST = r'''"""Project ownership has immediate official display and no transition DTO."""

from __future__ import annotations

import json

import pytest

from tests.support import runtime_state_fixture
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import folder_rule_service, project_service

pytestmark = [pytest.mark.db, pytest.mark.live_display, pytest.mark.contract]


def _snapshot() -> dict:
    raw = runtime_state_fixture.get_setting("current_activity_snapshot", "") or ""
    return json.loads(raw) if raw else {}


def _normal(title: str, path: str | None = None) -> ActiveWindow:
    return ActiveWindow("Code", "code.exe", title, file_path_hint=path)


def _setup_two_projects(temp_db):
    project_a = project_service.create_project("ProjectA")
    project_b = project_service.create_project("ProjectB")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjectA", project_a)
    folder_rule_service.create_or_update_folder_rule("D:\\ProjectB", project_b)
    return project_a, project_b


def _assert_snapshot_has_only_official_project_contract(snapshot: dict) -> None:
    assert "display_project" in snapshot
    for retired in (
        "candidate_project",
        "project_transition",
        "project_transition_pending",
        "inferred_project_name",
        "extra_seconds",
        "checkpoint_seconds",
    ):
        assert retired not in snapshot


def test_resource_switch_applies_official_project_immediately(temp_db):
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", "D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    first = _snapshot()
    assert first["display_project"]["name"] == "ProjectA"
    _assert_snapshot_has_only_official_project_contract(first)

    machine.transition_to(
        "recording",
        _normal("b.py", "D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:00:01",
    )
    switched = _snapshot()
    assert switched["activity_display_name"] == "b.py"
    assert switched["display_project"]["name"] == "ProjectB"
    _assert_snapshot_has_only_official_project_contract(switched)


def test_unmapped_resource_is_uncategorized_not_inherited(temp_db):
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", "D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("tmp", "D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:00:01",
    )
    snapshot = _snapshot()
    assert snapshot["display_project"]["name"] == "未归类"
    assert snapshot["display_project"]["is_uncategorized"] is True
    _assert_snapshot_has_only_official_project_contract(snapshot)


def test_session_boundary_does_not_inherit_formal_project(temp_db):
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", "D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to("stopped", at_time="2026-06-18 09:00:05")
    machine.transition_to(
        "recording",
        _normal("tmp", "D:\\Unmapped\\tmp"),
        at_time="2026-06-18 10:00:00",
    )
    snapshot = _snapshot()
    assert snapshot["display_project"]["name"] == "未归类"
    _assert_snapshot_has_only_official_project_contract(snapshot)
'''


CUTOVER_CONTRACT_TEST = r'''from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.live_display, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_project_transition_type_and_public_fields_are_removed():
    production = {
        relative: _text(relative)
        for relative in (
            "worktrace/contracts/live_display_contracts.py",
            "worktrace/api/dto.py",
            "worktrace/collector/snapshot_publisher.py",
            "worktrace/services/project_ownership_service.py",
            "worktrace/services/live_display_service.py",
            "worktrace/services/activity_display_policy.py",
            "worktrace/services/activity_display_span.py",
            "worktrace/services/activity_row_overlay.py",
            "worktrace/services/view_model_service.py",
        )
    }
    globally_retired = (
        "ProjectTransition",
        "project_transition_pending",
        "inferred_project_name",
        "snapshot_extra_seconds",
    )
    offenders = [
        f"{relative}: {token}"
        for relative, source in production.items()
        for token in globally_retired
        if token in source
    ]
    public_only = (
        "worktrace/contracts/live_display_contracts.py",
        "worktrace/api/dto.py",
        "worktrace/collector/snapshot_publisher.py",
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_span.py",
        "worktrace/services/activity_row_overlay.py",
        "worktrace/services/view_model_service.py",
    )
    for relative in public_only:
        source = production[relative]
        for token in ("candidate_project", "project_transition", '"extra_seconds"'):
            if token in source:
                offenders.append(f"{relative}: {token}")
    assert offenders == []


def test_runtime_snapshot_contract_has_one_project_field():
    source = _text("worktrace/collector/snapshot_publisher.py")
    assert '"display_project": display_label.to_dict()' in source
    assert '"elapsed_seconds": elapsed' in source
    assert '"persisted_activity_id": persisted_activity_id' in source
'''


SNAPSHOT_FACTORY = r'''from __future__ import annotations

from datetime import datetime, timedelta

from worktrace.constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)


def current_activity_snapshot(
    *,
    elapsed_seconds: int = 120,
    status: str = STATUS_NORMAL,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
    project_name: str = "TestProject",
    start_time: str | None = None,
    app_name: str = "AppA",
    process_name: str = "AppA.exe",
    window_title: str = "Window",
    inferred_project_name: str | None = None,
    extra_seconds: int = 0,
) -> dict:
    """Build the canonical snapshot shape.

    The last two parameters remain test-call compatibility aliases only; they
    are deliberately not serialized into the snapshot.
    """

    del extra_seconds
    if inferred_project_name is not None:
        project_name = inferred_project_name
    if start_time is None:
        start = datetime.now() - timedelta(seconds=elapsed_seconds)
        start_time = start.strftime(TIME_FORMAT)
    return {
        "app_name": app_name,
        "process_name": process_name,
        "window_title": window_title,
        "start_time": start_time,
        "elapsed_seconds": elapsed_seconds,
        "status": status,
        "is_persisted": is_persisted,
        "persisted_activity_id": persisted_activity_id,
        "display_project": {
            "id": None,
            "name": project_name,
            "description": "",
            "source": "uncategorized",
            "is_uncategorized": project_name in {"", "未归类"},
            "is_suggested_project": False,
        },
    }


def normal_snapshot(**kwargs) -> dict:
    kwargs.setdefault("status", STATUS_NORMAL)
    return current_activity_snapshot(**kwargs)


def persisted_open_snapshot(activity_id: int, **kwargs) -> dict:
    return current_activity_snapshot(
        is_persisted=True,
        persisted_activity_id=activity_id,
        **kwargs,
    )


def unpersisted_normal_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(is_persisted=False, **kwargs)


def idle_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_IDLE, **kwargs)


def paused_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_PAUSED, **kwargs)


def excluded_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_EXCLUDED, **kwargs)


def error_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_ERROR, **kwargs)
'''


LIVE_TIME_TEST = r'''from datetime import datetime

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.live_display, pytest.mark.parallel_safe]

from worktrace.services.live_time_service import snapshot_elapsed_seconds, snapshot_total_seconds


def test_snapshot_elapsed_seconds_uses_snapshot_sample_not_current_clock():
    snapshot = {
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": 1,
    }

    assert snapshot_elapsed_seconds(snapshot, now=datetime(2026, 6, 18, 9, 0, 5)) == 1
    assert snapshot_total_seconds(snapshot, now=datetime(2026, 6, 18, 9, 0, 5)) == 1


def test_snapshot_elapsed_seconds_is_not_recomputed_from_wall_clock_gap():
    snapshot = {
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": 42,
    }

    assert snapshot_elapsed_seconds(snapshot, now=datetime(2026, 6, 20, 9, 0, 1)) == 42
'''


def update_contracts() -> None:
    relative = "worktrace/contracts/live_display_contracts.py"
    content = read(relative)
    content = content.replace('DisplayBasePolicy = Literal[\n    "suppressed",\n    "persisted_extra",\n]', 'DisplayBasePolicy = Literal[\n    "suppressed",\n    "persisted_open",\n]')
    content, count = re.subn(
        r'\nclass ProjectTransitionContract\(TypedDict, total=False\):.*?\n\nclass ActivitySnapshotContract',
        '\nclass ActivitySnapshotContract',
        content,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError("live_display_contracts.py: ProjectTransitionContract block mismatch")
    retired_fields = {
        "inferred_project_name:",
        "checkpoint_seconds:",
        "extra_seconds:",
        "candidate_project:",
        "project_transition:",
        "project_transition_pending:",
    }
    lines = [
        line
        for line in content.splitlines()
        if not any(line.strip().startswith(field) for field in retired_fields)
    ]
    content = "\n".join(lines)
    content = content.replace(
        "    ``candidate_project``, ``project_transition`` and\n"
        "    ``inferred_project_name`` are temporary compatibility metadata only.\n"
        "    Display projection, revisions, structural signatures, and frontend\n"
        "    continuity identities must use the official ``display_project`` instead.\n",
        "    The snapshot carries one formal project block: ``display_project``.\n"
        "    Candidate inference remains internal to the collector and never enters\n"
        "    page DTOs, revisions, structural signatures, or frontend identity.\n",
    )
    write(relative, content)


def update_api_dto() -> None:
    regex_replace(
        "worktrace/api/dto.py",
        r'class ActivitySnapshot\(TypedDict, total=False\):.*?\n\nclass SessionProjectPreview',
        '''class ActivitySnapshot(TypedDict, total=False):
    activity_display_name: str
    app_name: str
    process_name: str
    status: str
    start_time: str
    elapsed_seconds: int
    is_persisted: bool
    persisted_activity_id: int
    resource_display_name: str
    display_project: dict[str, Any]


class SessionProjectPreview''',
    )


def update_recorder() -> None:
    relative = "worktrace/collector/activity_session_recorder.py"
    replace_exact(relative, "    advance_ownership,\n", "")
    replace_exact(
        relative,
        "            self.project_ownership_state = advance_ownership(\n"
        "                self.project_ownership_state,\n"
        "                at_time,\n"
        "            )\n",
        "",
    )
    replace_exact(
        relative,
        "        self.project_ownership_state = begin_ownership_for_new_resource(\n"
        "            self.project_ownership_state,\n"
        "            candidate,\n"
        "            at_time,\n"
        "        )\n",
        "        self.project_ownership_state = begin_ownership_for_new_resource(candidate)\n",
    )
    replace_exact(
        relative,
        "            persisted_activity_id=self.persisted_activity_id,\n"
        "            checkpoint_seconds=self.persisted_checkpoint_seconds,\n",
        "            persisted_activity_id=self.persisted_activity_id,\n",
    )


def update_live_display_service() -> None:
    relative = "worktrace/services/live_display_service.py"
    replace_exact(relative, "    snapshot_extra_seconds,\n", "")
    replace_exact(
        relative,
        "    return snapshot_elapsed_seconds(snapshot) + snapshot_extra_seconds(snapshot)\n",
        "    return snapshot_elapsed_seconds(snapshot)\n",
    )
    regex_replace(
        relative,
        r'\n\ndef _project_transition_for_display\(.*?\n\ndef _official_project_name_for_persisted_row',
        '\n\ndef _official_project_name_for_persisted_row',
    )
    content = read(relative)
    content, count = re.subn(
        r'\n\s*"candidate_project": None,\n\s*"project_transition": \{\n.*?\n\s*\},\n\s*"project_transition_pending": False,',
        '',
        content,
        count=2,
        flags=re.DOTALL,
    )
    if count != 2:
        raise RuntimeError(f"live_display_service.py: empty public project blocks: {count}")
    content, count = re.subn(
        r'\n    candidate_project_dict = snapshot\.get\("candidate_project"\) if snapshot else None\n'
        r'    if not isinstance\(candidate_project_dict, dict\) or not candidate_project_dict:\n'
        r'        candidate_project_dict = display_project_dict\n'
        r'    project_transition_dict = _project_transition_for_display\(snapshot\)\n'
        r'    project_transition_pending = False',
        '',
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("live_display_service.py: summary compatibility block mismatch")
    for line in (
        '        "candidate_project": candidate_project_dict,\n',
        '        "project_transition": project_transition_dict,\n',
        '        "project_transition_pending": project_transition_pending,\n',
    ):
        if content.count(line) != 1:
            raise RuntimeError(f"live_display_service.py: expected one {line!r}")
        content = content.replace(line, "")
    content = content.replace(
        "    Returns a dict with: ``project_id``, ``project_name``,\n"
        "    ``project_description``, ``display_project``, ``candidate_project``,\n"
        "    ``project_transition``, ``project_transition_pending``,\n"
        "    ``is_uncategorized``, ``is_classified``, ``status``, ``start_time``.\n",
        "    Returns formal display attribution plus classification, status, and start time.\n",
    )
    content, count = re.subn(
        r'\n    candidate_project_dict = snapshot\.get\("candidate_project"\) if snapshot else None\n'
        r'    if not isinstance\(candidate_project_dict, dict\) or not candidate_project_dict:\n'
        r'        candidate_project_dict = display_project_dict\n'
        r'    project_transition_dict = _project_transition_for_display\(snapshot\)',
        '',
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("live_display_service.py: field extraction compatibility block mismatch")
    for line in (
        '        "candidate_project": candidate_project_dict,\n',
        '        "project_transition": project_transition_dict,\n',
        '        "project_transition_pending": False,\n',
    ):
        if content.count(line) != 1:
            raise RuntimeError(f"live_display_service.py: expected one field {line!r}")
        content = content.replace(line, "")
    content = content.replace(
        "        # fall back to ``inferred_project_name`` which may carry the\n"
        "        # suggested project name and leak it into the formal display.\n",
        "        # fall back to candidate inference metadata.\n",
    )
    write(relative, content)


def update_display_policy() -> None:
    relative = "worktrace/services/activity_display_policy.py"
    replace_exact(relative, "from .live_time_service import snapshot_extra_seconds\n", "")
    replace_exact(relative, '            base_policy="persisted_extra",\n', '            base_policy="persisted_open",\n')
    replace_exact(relative, "            aggregate_base_seconds=snapshot_extra_seconds(snapshot),\n", "            aggregate_base_seconds=0,\n")
    replace_exact(relative, '            base_policy_reason="persisted_open_extra",\n', '            base_policy_reason="persisted_open_current_elapsed",\n')


def update_display_span() -> None:
    relative = "worktrace/services/activity_display_span.py"
    content = read(relative)
    content, count = re.subn(
        r'\n\s*"candidate_project": None,\n\s*"project_transition": \{\n.*?\n\s*\},\n\s*"project_transition_pending": False,',
        '',
        content,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError(f"activity_display_span.py: empty block mismatch {count}")
    for line in (
        '        candidate_project = project_fields["candidate_project"]\n',
        '        "candidate_project": candidate_project,\n',
        '        "project_transition": project_fields["project_transition"],\n',
        '        "project_transition_pending": bool(project_fields["project_transition_pending"]),\n',
    ):
        expected = 2 if line.startswith("        candidate_project =") else 1
        if content.count(line) != expected:
            raise RuntimeError(f"activity_display_span.py: expected {expected} occurrences {line!r}")
        content = content.replace(line, "")
    write(relative, content)


def update_row_overlay() -> None:
    relative = "worktrace/services/activity_row_overlay.py"
    for line in (
        '            row["candidate_project"] = span.get("candidate_project")\n',
        '            row["project_transition"] = span.get("project_transition")\n',
        '            row["project_transition_pending"] = bool(span.get("project_transition_pending"))\n',
    ):
        replace_exact(relative, line, "")


def update_display_projection() -> None:
    relative = "worktrace/services/activity_display_projection.py"
    replace_exact(
        relative,
        "from .project_attribution_policy import candidate_project_fields, official_project_fields\n",
        "from .project_attribution_policy import official_project_fields\n",
    )
    content = read(relative)
    content, count = re.subn(
        r'return _anchor_project_from_official_fields\(\n\s*official_project_fields\((.*?)\),\n\s*candidate_project_fields\((.*?)\),\n\s*\)',
        r'return _anchor_project_from_official_fields(official_project_fields(\1))',
        content,
        count=2,
        flags=re.DOTALL,
    )
    if count != 2:
        raise RuntimeError(f"activity_display_projection.py: anchor call mismatch {count}")
    content = content.replace(
        "def _anchor_project_from_official_fields(\n"
        "    official: dict[str, Any],\n"
        "    candidate: dict[str, Any],\n"
        ") -> dict[str, Any]:\n",
        "def _anchor_project_from_official_fields(official: dict[str, Any]) -> dict[str, Any]:\n",
    )
    if '        "candidate_project": candidate,\n' not in content:
        raise RuntimeError("activity_display_projection.py: candidate return field missing")
    content = content.replace('        "candidate_project": candidate,\n', "")
    write(relative, content)


def update_view_model() -> None:
    relative = "worktrace/services/view_model_service.py"
    content = read(relative).replace("project\ntransition", "official project\nattribution")
    content, count = re.subn(
        r'\n\ndef _detail_candidate_project_dict\(.*?\n\ndef _detail_report_attribution_fields',
        '\n\ndef _detail_report_attribution_fields',
        content,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError("view_model_service.py: candidate detail helper mismatch")
    for line in (
        '        "candidate_project": row.get("candidate_project") or _detail_candidate_project_dict(row),\n',
        '        "project_transition": row.get("project_transition"),\n',
        '        "project_transition_pending": bool(row.get("project_transition_pending")),\n',
    ):
        if content.count(line) != 1:
            raise RuntimeError(f"view_model_service.py: expected one {line!r}")
        content = content.replace(line, "")
    write(relative, content)


def update_test_guard() -> None:
    relative = "tests/test_deprecated_live_semantics_guard.py"
    content = read(relative)
    content = content.replace(
        "Compatibility metadata may be decoded at an\n"
        "ingress boundary, but it must not regain lifecycle, projection, revision, or\n"
        "frontend-identity meaning.\n",
        "Retired compatibility metadata is absent from production contracts and cannot\n"
        "regain lifecycle, projection, revision, or frontend-identity meaning.\n",
    )
    write(relative, content)


def main() -> int:
    write("worktrace/services/project_ownership_service.py", PROJECT_OWNERSHIP_SERVICE)
    write("worktrace/collector/snapshot_publisher.py", SNAPSHOT_PUBLISHER)
    write("worktrace/services/live_time_service.py", LIVE_TIME_SERVICE)
    write("tests/test_project_ownership_pending.py", PROJECT_OWNERSHIP_TEST)
    write("tests/test_project_transition_cutover_contract.py", CUTOVER_CONTRACT_TEST)
    write("tests/support/snapshot_factory.py", SNAPSHOT_FACTORY)
    write("tests/test_live_time_service.py", LIVE_TIME_TEST)

    update_contracts()
    update_api_dto()
    update_recorder()
    update_live_display_service()
    update_display_policy()
    update_display_span()
    update_row_overlay()
    update_display_projection()
    update_view_model()
    update_test_guard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
