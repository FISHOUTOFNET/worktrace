"""Python bridge exposed to the WebView frontend via pywebview.

Boundary rules (enforced by tests/test_ui_backend_boundary.py):

- This module may import ``worktrace.api`` and nothing else from the backend.
  It must not import ``worktrace.services``, ``worktrace.db``,
  ``worktrace.collector``, ``worktrace.security``, ``worktrace.runtime``, or
  ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

Composition structure (Phase M4 page-level split):

``WebViewBridge`` is now a thin composition class that inherits from six
mixins, each owning a page-level slice of the bridge surface:

- ``BridgeDialogMixin`` (``bridge_dialogs.py``): native save / open file
  dialog helpers (``_choose_csv_save_path`` / ``_choose_backup_save_path``
  / ``_choose_backup_open_path``).
- ``OverviewBridgeMixin`` (``bridge_overview.py``): ``get_status``,
  ``toggle_pause``, ``get_overview``, ``get_recent_activities``.
- ``SettingsBridgeMixin`` (``bridge_settings.py``): first-run notice,
  settings / privacy status, clipboard capture toggle, encrypted backup
  export / import / manifest preview, clear-all-local-data.
- ``StatisticsBridgeMixin`` (``bridge_statistics.py``):
  ``get_statistics_export_summary``, ``export_statistics_csv``.
- ``TimelineBridgeMixin`` (``bridge_timeline.py``): all timeline read /
  edit / split / merge / hide / delete / batch / restore methods.
- ``ProjectRulesBridgeMixin`` (``bridge_rules.py``): the 12 Project Rules
  bridge methods (Phase M3 split).

Shared helpers (``_coerce_activity_ids``, ``_validate_datetime_inputs``,
``_safe_resource_display_name``, ``_snapshot_summary``,
``_statistics_summary_payload``, ``_GENERIC_ERROR``, ``_RECENT_LIMIT``,
``_DATE_SHAPE_RE``, ``_DATETIME_SHAPE_RE``) live in ``bridge_common.py``.
Each mixin imports what it needs from its own owning module; this module
only exposes ``WebViewBridge``.

The bridge is the only data path between JS and Python. As of Phase 1 the
Overview page is fully migrated: ``get_status``, ``toggle_pause``,
``get_overview``, and ``get_recent_activities`` are the production data path
for the Overview page. As of Phase 2 the Timeline page is migrated as a
read-only page: ``get_timeline`` and ``get_timeline_session_details`` are the
production data path for the Timeline page. Phase 2.1 hardens the Timeline
bridge so the ``resource_name`` never falls back to the raw ``window_title``
column (which can contain file paths, URLs, or email subjects) and passes
through an explicit ``is_in_progress`` flag for open sessions/activities.
The timeline service marks ``is_in_progress`` before projecting or replacing
an open activity's ``end_time`` for display; the API and bridge only pass
this flag through. Consumers must not infer in-progress state from the
displayed ``end_time``, because open activities may carry a projected
display ``end_time``.

Phase 3A adds minimal Timeline editing: ``list_projects_for_timeline``,
``update_timeline_project``, and ``update_timeline_note`` are the production
write path for project reclassification and session-note editing. They go
through ``worktrace.api`` only, validate input, and never return tracebacks
or sensitive raw fields. The session note returned by ``get_timeline`` is
the user-authored note (the editing target), not captured metadata.

Phase 3B.1 adds the minimal time-correction foundation:
``update_timeline_activity_time`` and ``update_timeline_session_time`` are
the production write path for correcting a single closed activity's
``start_time``/``end_time``. Session-level correction is only supported for
single-activity sessions; multi-activity sessions return a clear Chinese
message directing the user to per-activity editing. In-progress activities
cannot be edited (their displayed ``end_time`` may be a projected value).
Errors are mapped from stable ``TimelineTimeEditError`` codes to Chinese
messages without echoing tracebacks, SQL, or internal field names.

Phase 3B.2 adds the minimal activity-split foundation:
``split_timeline_activity`` and ``split_timeline_session`` are the production
write path for splitting a single closed activity into two at a given
``split_time``. The original activity keeps its id and becomes the front
half; a new activity is inserted for the back half. Session-level split is
only supported for single-activity sessions; multi-activity sessions return
a clear Chinese message directing the user to per-activity splitting.
In-progress activities cannot be split. Errors are mapped from stable
``TimelineSplitError`` codes to Chinese messages without echoing
tracebacks, SQL, or internal field names.

Phase 3B.3 adds the minimal activity-merge foundation:
``merge_timeline_activities`` is the production write path for merging
exactly two closed, adjacent, same-project/same-resource/same-status
activities into one. The earlier activity keeps its id and start_time; its
end_time is extended to the later activity's end_time. The later activity
is soft-deleted. Only two activities can be merged per call; arbitrary-
length batch merge and multi-activity session whole-merge are NOT
supported. Errors are mapped from stable ``TimelineMergeError`` codes to
Chinese messages without echoing tracebacks, SQL, or internal field names.

Phase 3B.4 adds the minimal hide / soft-delete foundation:
``hide_timeline_activity``, ``soft_delete_timeline_activity``,
``hide_timeline_session``, and ``soft_delete_timeline_session`` are the
production write path for hiding or soft-deleting a single closed activity.
Hide sets ``is_hidden = 1``; soft delete sets ``is_deleted = 1``. Neither
physically deletes the row or touches assignment / resource / note /
session-note rows. Session-level operations only support single-activity
sessions; multi-activity sessions return a clear Chinese message directing
the user to per-activity editing. In-progress activities cannot be hidden
or deleted. Errors are mapped from stable ``TimelineVisibilityError`` codes
to Chinese messages without echoing tracebacks, SQL, or internal field
names. This phase does not change the existing project / note / time /
split / merge semantics.

Phase 3B.6 adds the first batch write capability:
``batch_update_timeline_activities_project`` reclassifies multiple closed,
non-hidden, non-deleted activities to the same project in a single atomic
transaction. It is the production write path for batch project
reassignment only; batch hide / delete / time correction / split / merge
are NOT supported. In-progress, hidden, and deleted activities are
rejected. The service layer uses a rowcount guard and rollback so no
partial write is ever persisted. Errors are mapped from stable
``TimelineBatchProjectError`` codes to Chinese messages without echoing
tracebacks, SQL, window titles, file paths, notes, or internal exception
details.

Phase 3B.7 adds the second batch write capability:
``batch_update_timeline_activities_note`` overwrites the note on multiple
closed, non-hidden, non-deleted activities with the same note value in a
single atomic transaction. It is the production write path for batch note
overwrite only; batch note append / merge, batch hide / delete / time
correction / split / merge are NOT supported. Only ``activity_log.note``
and ``updated_at`` are modified (``source`` is intentionally not changed).
Empty string is allowed and is used to batch-clear notes. In-progress,
hidden, and deleted activities are rejected. The service layer uses a
rowcount guard and rollback so no partial write is ever persisted. Errors
are mapped from stable ``TimelineBatchNoteError`` codes to Chinese
messages without echoing tracebacks, SQL, window titles, file paths,
notes, or internal exception details.

Phase 3B.8 adds the single activity restore foundation:
``restore_timeline_activity`` restores a single hidden or soft-deleted
activity by setting ``is_hidden = 0`` and ``is_deleted = 0`` in a single
atomic UPDATE with a rowcount guard. ``get_timeline_restorable_activities``
returns a display-safe recovery list of hidden / deleted closed activities
for a given date so the user can select which activity to restore. Only
``is_hidden``, ``is_deleted``, and ``updated_at`` are modified; no other
fields, resource rows, assignment rows, or session notes are touched. The
row is never physically deleted. In-progress activities cannot be
restored. Activities that are neither hidden nor deleted are rejected as
``not_restorable``. Errors are mapped from stable
``TimelineRestoreActivityError`` codes to Chinese messages without
echoing tracebacks, SQL, window titles, file paths, notes, or internal
exception details. This phase does NOT implement batch restore, undo
stack, permanent delete, or any new DB schema.

Phase 5B adds the first minimal Project Rules WebView write foundation:
``get_project_rules`` remains the display-safe read path, and
``set_project_rule_enabled`` may only enable/disable one existing folder or
keyword rule per call. It does NOT create, edit, delete, enable, or disable
projects; it does NOT create, edit, or delete rules; it does NOT perform
conflict preview, backfill, automatic rules, DB schema changes, native
dialogs, file writes, or network access. Errors collapse to stable Chinese
messages without tracebacks, SQL, raw exception text, window titles,
clipboard, notes, paths, or internal fields.

Phase 5C adds the second minimal Project Rules WebView write foundation:
``create_project_keyword_rule`` creates one new keyword rule on an existing
rule-target project (validated via ``project_api.list_rule_target_projects``,
the same eligibility rule the legacy Tkinter dialog uses). It does NOT
create folder rules, projects, or edit/delete existing rules; it does NOT
perform conflict preview, backfill, automatic rules, DB schema changes,
native dialogs, file writes, or network access. The success payload is the
narrow created-rule summary only; the frontend re-fetches the full Project
Rules list via ``get_project_rules`` after success. Errors are mapped from
stable codes to Chinese messages without tracebacks, SQL, raw exception
text, window titles, clipboard, notes, paths, or internal fields.

Phase 5D adds the third minimal Project Rules WebView write foundation:
``delete_project_keyword_rule`` deletes one existing keyword rule. It only
deletes a keyword rule; it does not delete folder rules, projects, or
edit/enable/disable any rule or project. A ``rule_id`` that points at a
folder rule is rejected as ``关键词规则不存在`` rather than deleting the
folder rule. It does NOT perform conflict preview, backfill, automatic
rules, DB schema changes, native dialogs, file writes, or network access.
The success payload is the narrow deleted-rule summary only; the frontend
re-fetches the full Project Rules list via ``get_project_rules`` after
success. Errors are mapped from stable codes to Chinese messages without
tracebacks, SQL, raw exception text, window titles, clipboard, notes,
paths, or internal fields.

Phase 5E opens the Project Rules folder rule CRUD foundation:
``create_project_folder_rule`` creates one new folder rule on an existing
rule-target project (validated via ``project_api.list_rule_target_projects``,
the same eligibility rule the legacy Tkinter dialog and Phase 5C keyword
creation use). ``update_project_folder_rule`` updates one existing folder
rule's ``folder_path`` and ``recursive`` (a ``rule_id`` that points at a
keyword rule is rejected as ``文件夹规则不存在``; the existing ``project_id``
is preserved). ``delete_project_folder_rule`` deletes one existing folder
rule (a ``rule_id`` that points at a keyword rule is rejected as
``文件夹规则不存在``). The three facades together open the folder rule
create / edit / delete foundation; they do NOT perform conflict preview,
backfill, automatic rules, DB schema changes, native file picker dialogs,
file writes (beyond the rule row itself), or network access. The success
payload is the narrow written-rule summary only; the frontend re-fetches
the full Project Rules list via ``get_project_rules`` after success. Errors
are mapped from stable codes to Chinese messages without tracebacks, SQL,
raw exception text, window titles, clipboard, notes, paths, or internal
fields.
"""

from __future__ import annotations

import logging
from typing import Any

# API facades are imported at module level so tests that monkeypatch
# ``bridge_module.project_api`` / ``bridge_module.rule_api`` continue to
# resolve after the Phase M4 page-level split. The mixin methods look up
# these modules in their own module namespace (not here), but because
# Python ``import`` binds to the same module object, monkeypatching an
# attribute on the module object affects every reference.
from ..api import (
    app_api,
    export_api,
    project_api,
    rule_api,
    settings_api,
    statistics_api,
    timeline_api,
)
from .bridge_dialogs import BridgeDialogMixin
from .bridge_overview import OverviewBridgeMixin
from .bridge_rules import ProjectRulesBridgeMixin
from .bridge_settings import SettingsBridgeMixin
from .bridge_statistics import StatisticsBridgeMixin
from .bridge_timeline import TimelineBridgeMixin

logger = logging.getLogger(__name__)


class WebViewBridge(
    BridgeDialogMixin,
    OverviewBridgeMixin,
    SettingsBridgeMixin,
    StatisticsBridgeMixin,
    TimelineBridgeMixin,
    ProjectRulesBridgeMixin,
):
    """Bridge object exposed to JS through pywebview's JS API.

    Each method returns a plain dict (or list inside a dict) so pywebview can
    serialize it to JS. Errors never include tracebacks or sensitive fields.

    Phase M4 composition: the method bodies now live in the six mixin
    modules listed above. ``WebViewBridge`` itself only owns ``__init__``
    and ``set_window``; every public bridge method is inherited.
    """

    def __init__(self) -> None:
        # Phase 4B: the pywebview window is injected by ``webview_main.py``
        # after ``create_window`` so the bridge can open a native save dialog
        # for the CSV export. Stays ``None`` until ``set_window`` is called,
        # so importing / unit-testing the bridge never starts the GUI.
        self._window: Any = None

    def set_window(self, window: Any) -> None:
        """Inject the pywebview window so the bridge can open native dialogs.

        Called by ``worktrace.webview_main`` after ``webview.create_window``
        returns. The bridge must not construct a window itself: that would
        start the GUI on import / during tests. Until this is called the
        CSV export save dialog is unavailable and returns a stable error.
        """
        self._window = window


__all__ = ["WebViewBridge"]
