"""Pywebview dialog helper mixin for the WebView bridge.

This module was split out of ``bridge.py`` so that the Settings / Statistics
mixins can call native save / open file dialogs without importing ``bridge.py``
(which would create a circular dependency).

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- ``webview`` is imported lazily inside each method so the bridge module
  does not pull the WebView backend into unit tests at import time.
- Full paths returned by the dialog are only used as API facade arguments;
  they never enter JS payloads.
- The mixin does not create a window; it only reads ``self._window`` which
  is injected by the host ``WebViewBridge`` via ``set_window()``.
"""

from __future__ import annotations

from typing import Any

from ..api.export_api import StatisticsExportError


class BridgeDialogMixin:
    """Pywebview dialog helpers shared by Statistics and Settings mixins.

    The mixin is mixed into ``WebViewBridge`` in ``bridge.py``. It must NOT
    add ``__init__``; it relies on the host class having ``self._window``
    (injected via ``set_window()``).
    """

    def _choose_csv_save_path(self) -> str | None:
        """Open the native save dialog and return the chosen path or ``None``.

        Returns ``None`` when the user cancels. Raises
        ``StatisticsExportError("operation_failed")`` when no window has
        been injected or the pywebview save dialog API is unavailable / raises.

        The returned path is the user-chosen string verbatim; path
        normalization (``.csv`` suffix, parent existence) is handled by the
        service layer. The full path never leaves the bridge except as the
        argument to the API write call (which is the only path the bridge
        is allowed to touch).
        """
        window = self._window
        if window is None:
            raise StatisticsExportError("operation_failed")
        # Resolve the save dialog type constant lazily so the bridge module
        # does not import pywebview at import time (which would pull the
        # WebView backend into unit tests). Newer pywebview exposes
        # ``FileDialog.SAVE``; the deprecated ``SAVE_DIALOG`` is the fallback.
        dialog_type = None
        try:
            import webview  # noqa: WPS433 (lazy import, UI-only dependency)

            file_dialog = getattr(webview, "FileDialog", None)
            if file_dialog is not None:
                dialog_type = getattr(file_dialog, "SAVE", None)
            if dialog_type is None:
                dialog_type = getattr(webview, "SAVE_DIALOG", None)
        except Exception:
            dialog_type = None
        if dialog_type is None:
            raise StatisticsExportError("operation_failed")
        try:
            result = window.create_file_dialog(
                dialog_type,
                save_filename="worktrace-export.csv",
                file_types=("CSV Files (*.csv)",),
            )
        except Exception:
            raise StatisticsExportError("operation_failed")
        if not result:
            return None
        # pywebview returns a sequence of strings (or None on cancel). For a
        # save dialog exactly one path is expected; take the first.
        if isinstance(result, (tuple, list)):
            if not result:
                return None
            return str(result[0])
        return str(result)

    def _choose_backup_save_path(self) -> str | None:
        """Open the native save dialog for an encrypted ``.wtbackup`` file.

        Returns ``None`` when the user cancels. Raises a generic ``Exception``
        when no window has been injected or the pywebview save dialog API is
        unavailable / raises; the calling bridge method catches it and
        collapses to ``"导出加密备份失败"``.

        The returned path is the user-chosen string verbatim; suffix
        normalization (``.wtbackup``) is handled by the API facade. The full
        path never leaves the bridge except as the argument to the API
        write call.
        """
        return self._open_backup_dialog(save=True)

    def _choose_backup_open_path(self) -> str | None:
        """Open the native open file dialog for an encrypted ``.wtbackup`` file.

        Returns ``None`` when the user cancels. Raises a generic ``Exception``
        when no window has been injected or the pywebview open dialog API is
        unavailable / raises; the calling bridge method catches it and
        collapses to ``"读取备份清单失败"``.

        The returned path is the user-chosen string verbatim; suffix
        validation (``.wtbackup``) is handled by the API facade. The full
        path never leaves the bridge except as the argument to the API
        read call.
        """
        return self._open_backup_dialog(save=False)

    def _open_backup_dialog(self, save: bool) -> str | None:
        """Shared pywebview dialog helper for ``.wtbackup`` save / open.

        ``save=True`` resolves the SAVE dialog (with a default
        ``worktrace-backup.wtbackup`` filename); ``save=False`` resolves
        the OPEN dialog. Lazy-imports pywebview so the bridge module does
        not pull the WebView backend into unit tests at import time.
        """
        window = self._window
        if window is None:
            raise RuntimeError("webview window not injected")
        dialog_type = None
        try:
            import webview  # noqa: WPS433 (lazy import, UI-only dependency)

            file_dialog = getattr(webview, "FileDialog", None)
            if file_dialog is not None:
                dialog_type = getattr(
                    file_dialog, "SAVE" if save else "OPEN", None
                )
            if dialog_type is None:
                dialog_type = getattr(
                    webview, "SAVE_DIALOG" if save else "OPEN_DIALOG", None
                )
        except Exception:
            dialog_type = None
        if dialog_type is None:
            raise RuntimeError("pywebview FileDialog unavailable")
        try:
            kwargs: dict[str, Any] = {
                "file_types": ("WorkTrace Backup (*.wtbackup)",),
            }
            if save:
                kwargs["save_filename"] = "worktrace-backup.wtbackup"
            result = window.create_file_dialog(dialog_type, **kwargs)
        except Exception:
            raise RuntimeError("webview file dialog failed")
        if not result:
            return None
        # pywebview returns a sequence of strings (or None on cancel). Take
        # the first entry as the chosen path.
        if isinstance(result, (tuple, list)):
            if not result:
                return None
            return str(result[0])
        return str(result)


__all__ = ["BridgeDialogMixin"]
