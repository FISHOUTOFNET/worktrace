from __future__ import annotations

import re
from dataclasses import dataclass

from .constants import ANCHOR_FILE_EXTENSIONS
from .path_utils import extract_file_path_from_title, looks_like_anchor_file_path, normalize_path_key, split_file_path

_ANCHOR_EXT_RE = "|".join(re.escape(ext.lstrip(".")) for ext in ANCHOR_FILE_EXTENSIONS)
_FILE_RE = re.compile(
    rf"(?P<name>[^\\/:*?\"<>|\r\n]+?\.({_ANCHOR_EXT_RE}))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResourceIdentity:
    resource_role: str
    resource_type: str
    display_name: str
    canonical_key: str
    app_name: str | None = None
    process_name: str | None = None
    title_hint: str | None = None
    full_path: str | None = None
    parent_dir: str | None = None
    file_stem: str | None = None


def infer_resource_identity(
    app_name: str | None,
    process_name: str | None,
    window_title: str | None,
    file_path_hint: str | None = None,
) -> ResourceIdentity:
    app = (app_name or "").strip()
    process = (process_name or "").strip()
    title = (window_title or "").strip()

    full_path_candidate = file_path_hint if looks_like_anchor_file_path(file_path_hint) else None
    full_path_candidate = full_path_candidate or extract_file_path_from_title(title)
    if full_path_candidate:
        full_path, parent_dir, file_stem = split_file_path(full_path_candidate)
        file_name = full_path.rsplit("\\", 1)[-1]
        return ResourceIdentity(
            resource_role="anchor",
            resource_type="file",
            display_name=file_name,
            canonical_key=f"file_path:{normalize_path_key(full_path)}",
            app_name=app or None,
            process_name=process or None,
            title_hint=file_name,
            full_path=full_path,
            parent_dir=parent_dir,
            file_stem=file_stem,
        )

    file_name = extract_anchor_file_name(title)
    if file_name:
        return ResourceIdentity(
            resource_role="anchor",
            resource_type="file",
            display_name=file_name,
            canonical_key=f"file:{normalize_file_name(file_name)}",
            app_name=app or None,
            process_name=process or None,
            title_hint=file_name,
            file_stem=re.sub(r"\.[^.]+$", "", file_name),
        )

    display = app or process or "未知应用"
    key_parts = [part for part in (app, process) if part]
    key_base = "|".join(key_parts) if key_parts else "unknown"
    return ResourceIdentity(
        resource_role="auxiliary",
        resource_type="app",
        display_name=display,
        canonical_key=f"app:{_slug(key_base)}",
        app_name=app or None,
        process_name=process or None,
        title_hint=None,
    )


def extract_anchor_file_name(window_title: str | None) -> str | None:
    title = (window_title or "").strip()
    if not title:
        return None
    matches = list(_FILE_RE.finditer(title))
    if not matches:
        return None
    raw = matches[-1].group("name").strip()
    return _clean_file_name(raw)


def normalize_file_name(file_name: str) -> str:
    return _clean_file_name(file_name).casefold()


def _clean_file_name(value: str) -> str:
    cleaned = value.strip().strip(" -—–_|[]()（）")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff]+", "-", value)
    return value.strip("-") or "unknown"
