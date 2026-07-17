from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one replacement, found {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    content = read(path)
    start_index = content.find(start)
    if start_index < 0:
        raise AssertionError(f"{path}: start marker missing: {start!r}")
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise AssertionError(f"{path}: end marker missing: {end!r}")
    end_index += len(end)
    write(path, content[:start_index] + replacement + content[end_index:])


def add_domain_limits() -> None:
    write(
        "worktrace/domain_limits.py",
        textwrap.dedent(
            '''\
            """Shared durable-domain limits used by every ingress boundary."""

            NOTE_MAX_LENGTH = 2000
            ADJUSTED_DURATION_MAX_SECONDS = 24 * 60 * 60

            __all__ = ["ADJUSTED_DURATION_MAX_SECONDS", "NOTE_MAX_LENGTH"]
            '''
        ),
    )
    replace_once(
        "worktrace/api/timeline_api.py",
        "from ..services import (\n",
        "from ..domain_limits import ADJUSTED_DURATION_MAX_SECONDS, NOTE_MAX_LENGTH\nfrom ..services import (\n",
    )
    replace_once(
        "worktrace/api/timeline_api.py",
        "TIMELINE_NOTE_MAX_LENGTH = 2000\nTIMELINE_ADJUSTED_DURATION_MAX_SECONDS = 24 * 60 * 60\n",
        "TIMELINE_NOTE_MAX_LENGTH = NOTE_MAX_LENGTH\nTIMELINE_ADJUSTED_DURATION_MAX_SECONDS = ADJUSTED_DURATION_MAX_SECONDS\n",
    )
    replace_once(
        "worktrace/services/secure_backup_validation.py",
        "from ..db import CURRENT_SCHEMA_VERSION, expected_schema_fingerprint, schema_fingerprint\n",
        "from ..db import CURRENT_SCHEMA_VERSION, expected_schema_fingerprint, schema_fingerprint\nfrom ..domain_limits import NOTE_MAX_LENGTH\n",
    )
    replace_once(
        "worktrace/services/secure_backup_validation.py",
        '''            if note.get("mode") == "set":
                if not isinstance(note.get("value"), str):
                    raise BackupValidationError("note value")
''',
        '''            if note.get("mode") == "set":
                note_value = note.get("value")
                if not isinstance(note_value, str):
                    raise BackupValidationError("note value")
                if len(note_value) > NOTE_MAX_LENGTH:
                    raise BackupValidationError("note value length")
''',
    )


def fix_reverse_clock() -> None:
    path = "worktrace/services/activity_fact_repository.py"
    replace_once(
        path,
        '''    safe_end = max(str(end_time or ""), str(row["start_time"] or ""))
    duration, reversed_clock = _duration_seconds(
        str(row["start_time"]),
        safe_end,
    )
''',
        '''    start_time = str(row["start_time"] or "")
    requested_end = str(end_time or start_time)
    duration, reversed_clock = _duration_seconds(start_time, requested_end)
    safe_end = start_time if reversed_clock else requested_end
''',
    )
    replace_once(
        path,
        '''        safe_end = max(str(end_time or ""), str(row["start_time"] or ""))
        if close_activity(conn, activity_id, safe_end):
''',
        '''        if close_activity(conn, activity_id, end_time):
''',
    )


def unify_frontend_generation_reset() -> None:
    init_path = "worktrace/webview_ui/js/init.js"
    reset_function = textwrap.dedent(
        '''\
            function resetClientGeneration(reason) {
                if (App.requestCoordinator) App.requestCoordinator.bumpDataEpoch();
                App.timelineLoaded = false;
                App.statisticsLoaded = false;
                App.rulesLoaded = false;
                App.settingsLoaded = false;
                App.currentSessions = [];
                App.selectedProjectionInstanceKey = null;
                App.selectedProjectionRevision = null;
                App.editingSession = null;
                App.detailsOwner = null;
                App.timelineOwner = null;
                App.mutationOwner = null;
                App.mutationState = "idle";
                App.detailsInFlight = {};
                App.projectsCache = null;
                App.projectsLoading = false;
                App.projectsLoadPromise = null;
                App.lastTimelineData = null;
                App.lastProjectRulesData = null;
                App.lastSessionDetailsViewModel = null;
                App.lastSessionActivitySummaryViewModel = null;
                App.lastRefreshState = null;
                App.statisticsAcceptedPayload = null;
                App.rulesLoadPromise = null;
                App.activePageRefreshInFlight = false;
                App.activePageRefreshPromise = null;
                App.activePageRefreshPending = null;
                App.reconcileInFlight = false;
                App.liveClockContractRefreshRequested = false;
                App.liveClockContractViolation = null;
                App.firstRunNoticeLoaded = false;
                App.firstRunNoticeLoading = false;
                liveRuntimeStore.reset();
                App._monotonicRenderState = {};
                App.overviewRequestToken = (App.overviewRequestToken || 0) + 1;
                App.timelineRequestToken = (App.timelineRequestToken || 0) + 1;
                App.statisticsRequestToken = (App.statisticsRequestToken || 0) + 1;
                App.rulesRequestToken = (App.rulesRequestToken || 0) + 1;
                App.settingsRequestToken = (App.settingsRequestToken || 0) + 1;
                App.lastClientGenerationResetReason = String(reason || "data_generation_changed");
            }
            App.resetClientGeneration = resetClientGeneration;
        '''
    )
    replace_between(
        init_path,
        "function resetClientGeneration()",
        "    App.resetClientGeneration = resetClientGeneration;",
        reset_function,
    )

    settings_path = "worktrace/webview_ui/js/settings.js"
    replace_between(
        settings_path,
        "    function resetFrontendAfterLocalDataReplacement() {",
        "    App.resetFrontendAfterLocalDataReplacement = resetFrontendAfterLocalDataReplacement;\n",
        "",
    )
    replace_once(
        settings_path,
        "            resetFrontendAfterLocalDataReplacement();\n",
        '            App.resetClientGeneration("secure_import");\n',
    )
    replace_once(
        settings_path,
        "            resetFrontendAfterLocalDataReplacement();\n",
        '            App.resetClientGeneration("clear_all_local_data");\n',
    )
    replace_once(
        settings_path,
        '''            App.firstRunNoticeLoading = false;
            App.firstRunNoticeLoaded = true;
            if (!result || result.ok === false) {
''',
        '''            App.firstRunNoticeLoading = false;
            if (!result || result.ok === false) {
''',
    )
    replace_once(
        settings_path,
        '''                return false;
            }
            App.firstRunNoticeRequired = result.accepted === false;
''',
        '''                return false;
            }
            App.firstRunNoticeLoaded = true;
            App.firstRunNoticeRequired = result.accepted === false;
''',
    )


def add_tests() -> None:
    write(
        "tests/test_data_integrity_boundaries.py",
        textwrap.dedent(
            '''\
            from __future__ import annotations

            import sqlite3

            import pytest

            from tests.support import activity_factory as activity_service
            from worktrace.constants import STATUS_ERROR
            from worktrace.domain_limits import NOTE_MAX_LENGTH
            from worktrace.services.secure_backup_validation import (
                BackupValidationError,
                _validate_operation_payload,
            )


            pytestmark = [pytest.mark.contract, pytest.mark.db]


            def test_reverse_clock_close_marks_error_before_clamping(temp_db):
                activity_id = activity_service.create_activity(
                    "Word",
                    "winword.exe",
                    "Doc",
                    start_time="2026-07-01 10:00:00",
                )

                activity_service.close_activity_row(
                    activity_id,
                    "2026-07-01 09:59:00",
                )

                row = activity_service.get_activity(activity_id)
                assert row["end_time"] == "2026-07-01 10:00:00"
                assert int(row["duration_seconds"]) == 0
                assert row["status"] == STATUS_ERROR


            def test_backup_operation_rejects_note_above_domain_limit():
                operation = {
                    "operation_type": "edit_session",
                    "payload": {
                        "payload_version": 4,
                        "note": {"mode": "set", "value": "x" * (NOTE_MAX_LENGTH + 1)},
                    },
                }
                conn = sqlite3.connect(":memory:")
                try:
                    with pytest.raises(BackupValidationError, match="note value length"):
                        _validate_operation_payload(operation, conn)
                finally:
                    conn.close()
            '''
        ),
    )
    write(
        "tests/test_frontend_generation_contract.py",
        textwrap.dedent(
            '''\
            from pathlib import Path


            ROOT = Path(__file__).resolve().parents[1]
            JS = ROOT / "worktrace" / "webview_ui" / "js"


            def test_settings_uses_single_client_generation_reset():
                source = (JS / "settings.js").read_text(encoding="utf-8")
                assert "resetFrontendAfterLocalDataReplacement" not in source
                assert 'App.resetClientGeneration("secure_import")' in source
                assert 'App.resetClientGeneration("clear_all_local_data")' in source


            def test_client_generation_reset_clears_all_runtime_owners():
                source = (JS / "init.js").read_text(encoding="utf-8")
                start = source.index("function resetClientGeneration(reason)")
                end = source.index("App.resetClientGeneration = resetClientGeneration", start)
                body = source[start:end]
                for required in (
                    "bumpDataEpoch()",
                    "selectedProjectionInstanceKey = null",
                    "detailsOwner = null",
                    "mutationOwner = null",
                    "projectsCache = null",
                    "lastRefreshState = null",
                    "activePageRefreshPending = null",
                    "liveRuntimeStore.reset()",
                    "_monotonicRenderState = {}",
                ):
                    assert required in body


            def test_first_run_notice_failure_remains_retryable():
                source = (JS / "settings.js").read_text(encoding="utf-8")
                start = source.index("function loadFirstRunNotice()")
                end = source.index("App.loadFirstRunNotice = loadFirstRunNotice", start)
                body = source[start:end]
                failure_check = body.index("if (!result || result.ok === false)")
                loaded_assignment = body.index("App.firstRunNoticeLoaded = true")
                assert failure_check < loaded_assignment
            '''
        ),
    )


def verify() -> None:
    settings = read("worktrace/webview_ui/js/settings.js")
    if "resetFrontendAfterLocalDataReplacement" in settings:
        raise AssertionError("duplicate frontend replacement reset remains")
    fact_repository = read("worktrace/services/activity_fact_repository.py")
    if "safe_end = max(" in fact_repository:
        raise AssertionError("reverse clock is still clamped before detection")


def main() -> None:
    add_domain_limits()
    fix_reverse_clock()
    unify_frontend_generation_reset()
    add_tests()
    verify()


if __name__ == "__main__":
    main()
