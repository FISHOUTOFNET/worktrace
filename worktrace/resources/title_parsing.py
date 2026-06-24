from __future__ import annotations

import re

from ..constants import ANCHOR_FILE_EXTENSIONS
from ..path_utils import has_auto_project_extension

_FILE_RE = re.compile(
    r"(?P<name>[^\\/:*?\"<>|\r\n]+?\.[^\\/:*?\"<>|\r\n\s.]+)(?=$|[\s\"'）)\]】。；;，,]| - )",
    re.IGNORECASE,
)


def extract_anchor_file_name(window_title: str | None) -> str | None:
    file_name = extract_file_name_from_title(window_title)
    if file_name and has_auto_project_extension(file_name):
        return file_name
    return None


def extract_file_name_from_title(window_title: str | None) -> str | None:
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
