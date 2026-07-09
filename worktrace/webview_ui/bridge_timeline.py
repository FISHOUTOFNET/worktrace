"""Timeline bridge mixin.

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` in ``bridge.py`` inherits ``TimelineBridgeMixin`` so the
Timeline page method names stay on ``WebViewBridge``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import (
    project_api,
    timeline_api,
    view_model_api,
)
from ..formatters import format_duration, format_resource_type
from .bridge_common import (
    _DATE_SHAPE_RE,
    _GENERIC_ERROR,
    _coerce_activity_ids,
)

logger = logging.getLogger(__name__)



class TimelineBridgeMixin:
    """Timeline page bridge methods.

    Mixed into ``WebViewBridge`` in ``bridge.py`` so the Timeline page
    method names stay on ``WebViewBridge``. The mixin must NOT add
    ``__init__``; it relies on the host class.
    """

    def get_timeline(self, date: str | None = None) -> dict[str, Any]:
        """Return the Timeline page ViewModel for a single date.

        The complete Timeline ViewModel (sessions, live_clock, Activity
        Display Model fields, persisted_open overlay, project transition,
        duration override, raw/display totals) is built by
        ``view_model_service`` from a single snapshot sample. The legacy
        ``live_projection`` alias is no longer surfaced; the Activity
        Display Model is the sole live semantics owner.
        """
        try:
            return view_model_api.get_timeline_view_model(date)
        except Exception:
            logger.exception("webview bridge get_timeline failed")
            return dict(_GENERIC_ERROR)

    def get_timeline_session_details(
        self,
        activity_ids: list[int],
        report_date: str | None = None,
    ) -> dict[str, Any]:
        """Return the Timeline Details ViewModel for a session.

        The complete Details ViewModel (DB detail rows, display-safe
        resource/project fields,
        edit_disabled / disable_reason, live clock fields, single-sample
        Activity Display Model contract) is built by
        ``view_model_service``. ``live_projection`` / ``live_display``
        aliases are not surfaced.
        """
        try:
            ids = [int(aid) for aid in (activity_ids or [])]
            return view_model_api.get_session_details_view_model(ids, report_date)
        except Exception:
            logger.exception("webview bridge get_timeline_session_details failed")
            return dict(_GENERIC_ERROR)

    def get_timeline_session_activity_summary(
        self,
        activity_ids: list[int],
        report_date: str | None = None,
    ) -> dict[str, Any]:
        """Return session-scoped activity duration summaries for Timeline."""
        try:
            ids_result = self._coerce_session_summary_activity_ids(activity_ids)
            if ids_result is None:
                return {"ok": False, "error": "请选择有效的活动时段"}
            ids = ids_result
            if report_date is not None and (
                not isinstance(report_date, str) or not _DATE_SHAPE_RE.match(report_date)
            ):
                return {"ok": False, "error": "日期无效"}
            if not ids:
                return {
                    "ok": True,
                    "date": report_date,
                    "activity_ids": [],
                    "summary_rows": [],
                }
            return view_model_api.get_session_activity_summary_view_model(ids, report_date)
        except (TypeError, ValueError):
            return {"ok": False, "error": "请选择有效的活动时段"}
        except Exception:
            logger.exception("webview bridge get_timeline_session_activity_summary failed")
            return dict(_GENERIC_ERROR)

    @staticmethod
    def _coerce_session_summary_activity_ids(activity_ids: Any) -> list[int] | None:
        if not isinstance(activity_ids, (list, tuple)):
            return None
        ids: list[int] = []
        seen: set[int] = set()
        for raw in activity_ids:
            if isinstance(raw, bool) or not isinstance(raw, int):
                return None
            value = raw
            if value <= 0:
                return None
            if value in seen:
                continue
            seen.add(value)
            ids.append(value)
        return ids

    def list_projects_for_timeline(self) -> dict[str, Any]:
        """Return the list of projects selectable for Timeline reclassification.

        Returns only display-safe fields (``id``, ``name``, ``description``).
        The "未归类" system project is included so the frontend can represent
        "uncategorized" without inventing a sentinel value. No sensitive
        fields are surfaced.
        """
        try:
            projects = project_api.list_selectable_projects()
            items: list[dict[str, Any]] = []
            for project in projects:
                items.append(
                    {
                        "id": int(project.get("id") or 0),
                        "name": str(project.get("name") or ""),
                        "description": str(project.get("description") or ""),
                    }
                )
            return {"ok": True, "projects": items}
        except Exception:
            logger.exception("webview bridge list_projects_for_timeline failed")
            return dict(_GENERIC_ERROR)

    def update_timeline_project(
        self,
        activity_ids: list[int],
        project_id: int,
    ) -> dict[str, Any]:
        """Reclassify a Timeline session's activities to a project.

        ``activity_ids`` is the session's full activity id list (all
        activities move together). ``project_id`` must be one of the ids
        returned by ``list_projects_for_timeline``; the frontend must
        never pass a free-form value.
        free-form value.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "操作失败"}`` on any failure. Errors never
        include tracebacks, SQL messages, file paths, or window titles.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            # ``bool`` is a subclass of ``int``; reject it so ``True`` is
            # not coerced to project id ``1``.
            if isinstance(project_id, bool):
                return {"ok": False, "error": "请选择有效的项目"}
            try:
                pid = int(project_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "请选择有效的项目"}
            timeline_api.reclassify_timeline_session_project(ids, pid)
            return {"ok": True}
        except ValueError as exc:
            if str(exc) == "not_project_activity":
                return {"ok": False, "error": "系统状态记录不支持项目编辑"}
            # Input validation failed. Return a generic message without
            # echoing the underlying ValueError text, which could reveal
            # internal field names or ids.
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_project failed")
            return dict(_GENERIC_ERROR)

    def update_timeline_note(
        self,
        activity_ids: list[int],
        note: str,
        report_date: str,
    ) -> dict[str, Any]:
        """Write the session note for a Timeline session.

        ``activity_ids`` is the session's activity id list; the first id is
        used as the session-note key (``first_activity_id``). ``note`` is the
        new note text. ``report_date`` is the ``YYYY-MM-DD`` date being
        viewed. The note is stored in ``project_session_note``. Legitimate
        newlines inside the note are preserved; whitespace-only notes
        delete the row.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "操作失败"}`` on any failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            if not isinstance(note, str):
                return {"ok": False, "error": "备注内容无效"}
            if len(note) > timeline_api.TIMELINE_NOTE_MAX_LENGTH:
                return {"ok": False, "error": "备注过长"}
            if not isinstance(report_date, str) or not report_date:
                return {"ok": False, "error": "日期无效"}
            # Lightweight shape check; the API does the full validation.
            if not _DATE_SHAPE_RE.match(report_date):
                return {"ok": False, "error": "日期无效"}
            first_activity_id = ids[0]
            timeline_api.update_timeline_session_note(
                report_date, first_activity_id, note
            )
            return {"ok": True}
        except ValueError as exc:
            if str(exc) == "not_project_activity":
                return {"ok": False, "error": "系统状态记录不支持项目编辑"}
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_note failed")
            return dict(_GENERIC_ERROR)

    def update_timeline_note_and_duration(
        self,
        activity_ids: list[int],
        note: str,
        adjusted_duration_seconds: int | None,
        report_date: str,
    ) -> dict[str, Any]:
        """Write note + user-adjusted duration for a Timeline session.

        ``activity_ids`` is the session's activity id list; the first id is
        used as the session key (``first_activity_id``). ``note`` is the new
        note text. ``adjusted_duration_seconds`` is the user-accepted
        duration in seconds (``None`` clears the override, restoring the
        raw collected duration). ``report_date`` is the ``YYYY-MM-DD`` date
        being viewed.

        The adjusted duration is stored in
        ``project_session_note.adjusted_duration_seconds`` and NEVER
        modifies ``activity_log``. Clearing the duration input (passing
        ``None``) removes the override.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            if not isinstance(note, str):
                return {"ok": False, "error": "备注内容无效"}
            if len(note) > timeline_api.TIMELINE_NOTE_MAX_LENGTH:
                return {"ok": False, "error": "备注过长"}
            if not isinstance(report_date, str) or not report_date:
                return {"ok": False, "error": "日期无效"}
            if not _DATE_SHAPE_RE.match(report_date):
                return {"ok": False, "error": "日期无效"}
            # Validate adjusted duration: ``None`` clears the override;
            # ``0`` is valid and means display/declare zero duration;
            # negative is invalid. ``bool`` and non-numeric are rejected.
            duration_value: int | None = None
            if adjusted_duration_seconds is not None:
                if isinstance(adjusted_duration_seconds, bool):
                    return {"ok": False, "error": "时长无效"}
                try:
                    duration_value = int(adjusted_duration_seconds)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "时长无效"}
                if duration_value < 0:
                    return {"ok": False, "error": "时长无效"}
                if duration_value > timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS:
                    return {"ok": False, "error": "时长无效"}
            first_activity_id = ids[0]
            timeline_api.update_timeline_session_note_and_duration(
                report_date, first_activity_id, note, duration_value
            )
            return {"ok": True}
        except ValueError as exc:
            if str(exc) == "not_project_activity":
                return {"ok": False, "error": "系统状态记录不支持项目编辑"}
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_note_and_duration failed")
            return dict(_GENERIC_ERROR)
