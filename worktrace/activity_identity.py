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
class ActivityIdentity:
    is_anchor_file: bool
    display_name: str
    identity_key: str
    app_name: str | None = None
    process_name: str | None = None
    title_hint: str | None = None
    full_path: str | None = None
    parent_dir: str | None = None
    file_stem: str | None = None


def infer_activity_identity(
    app_name: str | None,
    process_name: str | None,
    window_title: str | None,
    file_path_hint: str | None = None,
) -> ActivityIdentity:
    app = (app_name or "").strip()
    process = (process_name or "").strip()
    title = (window_title or "").strip()

    full_path_candidate = file_path_hint if looks_like_anchor_file_path(file_path_hint) else None
    full_path_candidate = full_path_candidate or extract_file_path_from_title(title)
    if full_path_candidate:
        full_path, parent_dir, file_stem = split_file_path(full_path_candidate)
        file_name = full_path.rsplit("\\", 1)[-1]
        return ActivityIdentity(
            is_anchor_file=True,
            display_name=file_name,
            identity_key=f"file_path:{normalize_path_key(full_path)}",
            app_name=app or None,
            process_name=process or None,
            title_hint=file_name,
            full_path=full_path,
            parent_dir=parent_dir,
            file_stem=file_stem,
        )

    file_name = extract_anchor_file_name(title)
    if file_name:
        return ActivityIdentity(
            is_anchor_file=True,
            display_name=file_name,
            identity_key=f"file:{normalize_file_name(file_name)}",
            app_name=app or None,
            process_name=process or None,
            title_hint=file_name,
            file_stem=re.sub(r"\.[^.]+$", "", file_name),
        )

    display = app or process or "未知应用"
    key_parts = [part for part in (app, process) if part]
    key_base = "|".join(key_parts) if key_parts else "unknown"
    return ActivityIdentity(
        is_anchor_file=False,
        display_name=display,
        identity_key=f"app:{_slug(key_base)}",
        app_name=app or None,
        process_name=process or None,
        title_hint=None,
    )


def infer_identity_for_activity(activity: dict) -> ActivityIdentity:
    return infer_activity_identity(
        activity.get("app_name"),
        activity.get("process_name"),
        activity.get("window_title"),
        activity.get("file_path_hint"),
    )


def attach_activity_identity(row: dict) -> dict:
    item = dict(row)
    identity = infer_identity_for_activity(item)
    item["activity_display_name"] = identity.display_name
    item["activity_identity_key"] = identity.identity_key
    item["is_anchor_file"] = identity.is_anchor_file
    item["anchor_full_path"] = identity.full_path or ""
    item["anchor_parent_dir"] = identity.parent_dir or ""
    item["anchor_file_stem"] = identity.file_stem or ""
    item["anchor_title_hint"] = identity.title_hint or ""
    return item


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
