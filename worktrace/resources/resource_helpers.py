"""Shared helpers for resource detectors.

Consolidates title/file-name parsing and identity-key construction so that
individual detectors (Office/WPS, LocalFile, IDE, Email, Browser) no longer
each carry their own copy of these utilities.

Title/file-name extraction (``extract_file_name_from_title``,
``normalize_file_name``, ``extract_anchor_file_name``) continues to live in
:mod:`worktrace.resources.title_parsing` and is re-exported here for a single
import surface.
"""

from __future__ import annotations

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
    "resolve_file_candidate",
    "build_path_or_name_identity",
    "display_name_from_path_or_name",
]


def normalize_for_key(value: str) -> str:
    """Normalize a free-form string for use in an identity key."""

    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff@]+", "-", value)
    return value.strip("-") or "unknown"


def resolve_file_candidate(
    active_window: ActiveWindow,
    allowed_extensions: frozenset[str] | set[str] | None = None,
    *,
    prefer_hint: bool = True,
    allow_title_path: bool = True,
    allow_title_file: bool = True,
) -> str | None:
    """Resolve a file path or bare file name for a detector."""

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

    return None


def build_path_or_name_identity(path_or_name: str, path_prefix: str, name_prefix: str) -> str:
    """Build an identity key that distinguishes full paths from bare names."""

    full_path, _parent, _stem = split_file_path(path_or_name)
    file_name = ntpath.basename(full_path)
    if looks_like_local_file_path(full_path):
        return f"{path_prefix}:{normalize_path_key(full_path)}"
    return f"{name_prefix}:{normalize_file_name(file_name)}"


def display_name_from_path_or_name(path_or_name: str) -> str:
    """Return the bare file name (basename) of a path or name string."""

    full_path, _parent, _stem = split_file_path(path_or_name)
    return ntpath.basename(full_path)
