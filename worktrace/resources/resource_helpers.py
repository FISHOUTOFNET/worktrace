"""Shared helpers for resource detectors.

Consolidates title/file-name parsing, identity-key construction, and folder
index lookups so that individual detectors (Office/WPS, LocalFile, IDE, Email,
Browser) no longer each carry their own copy of these utilities.

Title/file-name extraction (``extract_file_name_from_title``,
``normalize_file_name``, ``extract_anchor_file_name``) continues to live in
:mod:`worktrace.resources.title_parsing` and is re-exported here for a single
import surface.
"""

from __future__ import annotations

import logging
import ntpath
import re

from ..path_utils import (
    extract_file_path_from_title,
    looks_like_local_file_path,
    normalize_path_key,
    split_file_path,
)
from ..platforms.base import ActiveWindow
from .title_parsing import (
    extract_anchor_file_name,
    extract_file_name_from_title,
    normalize_file_name,
)

__all__ = [
    "extract_anchor_file_name",
    "extract_file_name_from_title",
    "normalize_file_name",
    "normalize_for_key",
    "resolve_unique_indexed_path_from_title",
    "resolve_file_candidate",
    "build_path_or_name_identity",
    "display_name_from_path_or_name",
]


def normalize_for_key(value: str) -> str:
    """Normalize a free-form string for use in an identity key.

    Lowercases, collapses whitespace to ``-``, and keeps alphanumerics, ``.``,
    ``_``, ``-``, CJK characters, and ``@`` (so email subjects/addresses are
    preserved). Other characters become ``-``. Returns ``"unknown"`` for empty
    input.
    """
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff@]+", "-", value)
    return value.strip("-") or "unknown"


def resolve_unique_indexed_path_from_title(
    window_title: str | None,
    *,
    include_excluded: bool = True,
    activity_start_time: str | None = None,
) -> str | None:
    """Safely resolve a unique indexed file path from a window title.

    Wraps :func:`worktrace.services.folder_index_service.resolve_unique_path_from_title`
    and returns ``None`` on any error (e.g. folder index unavailable or
    multiple ambiguous candidates), so callers can treat the folder index as a
    best-effort lookup.
    """
    if not (window_title or "").strip():
        return None
    try:
        from ..services.folder_index_service import resolve_unique_path_from_title

        return resolve_unique_path_from_title(
            window_title,
            include_excluded=include_excluded,
            activity_start_time=activity_start_time,
        )
    except Exception:
        logging.debug("folder index lookup failed for title", exc_info=True)
        return None


def resolve_file_candidate(
    active_window: ActiveWindow,
    allowed_extensions: frozenset[str] | set[str] | None = None,
    *,
    prefer_hint: bool = True,
    allow_title_path: bool = True,
    allow_title_file: bool = True,
    use_folder_index: bool = True,
) -> str | None:
    """Resolve a file path or bare file name for a detector.

    Resolution order (each step gated by its flag):

    1. ``file_path_hint`` (when ``prefer_hint``) — always accepted when
       present. The hint is trusted as an explicit signal, so it is not
       filtered by ``allowed_extensions``.
    2. Full path extracted from ``window_title`` (when ``allow_title_path``).
    3. File name extracted from ``window_title`` (when ``allow_title_file``),
       optionally filtered by ``allowed_extensions`` (so random title words
       are not mistaken for file names).
    4. Folder-index reverse lookup from ``window_title`` (when
       ``use_folder_index``) — returns a full path when the index has a unique
       match.

    Returns the resolved string (full path or bare file name), or ``None``.
    """
    if prefer_hint:
        hint = (active_window.file_path_hint or "").strip()
        if hint:
            return hint

    title = active_window.window_title or ""

    if allow_title_path:
        title_path = extract_file_path_from_title(title)
        if title_path:
            return title_path

    if allow_title_file:
        file_name = extract_file_name_from_title(title)
        if file_name:
            if allowed_extensions:
                _, ext = ntpath.splitext(file_name)
                if ext.casefold() in allowed_extensions:
                    return file_name
            else:
                return file_name

    if use_folder_index:
        indexed = resolve_unique_indexed_path_from_title(
            title,
            include_excluded=True,
            activity_start_time=active_window.activity_start_time,
        )
        if indexed:
            return indexed

    return None


def build_path_or_name_identity(path_or_name: str, path_prefix: str, name_prefix: str) -> str:
    """Build an identity key that distinguishes full paths from bare names.

    When ``path_or_name`` looks like a local file path, the key is
    ``"{path_prefix}:{normalize_path_key(full_path)}"``. Otherwise it is
    ``"{name_prefix}:{normalize_file_name(file_name)}"``.
    """
    full_path, _parent, _stem = split_file_path(path_or_name)
    file_name = ntpath.basename(full_path)
    if looks_like_local_file_path(full_path):
        return f"{path_prefix}:{normalize_path_key(full_path)}"
    return f"{name_prefix}:{normalize_file_name(file_name)}"


def display_name_from_path_or_name(path_or_name: str) -> str:
    """Return the bare file name (basename) of a path or name string."""
    full_path, _parent, _stem = split_file_path(path_or_name)
    return ntpath.basename(full_path)
