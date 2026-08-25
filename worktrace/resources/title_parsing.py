from __future__ import annotations

import ntpath
import re

from ..constants import ANCHOR_FILE_EXTENSIONS
from ..path_utils import has_auto_project_extension

_FILE_RE = re.compile(
    r"(?P<name>[^\\/:*?\"<>|\r\n]+?\.[^\\/:*?\"<>|\r\n\s.]+)(?=$|[\s\"'）)\]】。；;，,]| - )",
    re.IGNORECASE,
)
_VERSION_LIKE_RE = re.compile(r"^(?:v(?:ersion)?\s*)?\d+(?:\.\d+){1,4}$", re.IGNORECASE)
_COMMON_DOMAIN_SUFFIXES = frozenset(
    {"com", "org", "net", "io", "dev", "app", "cn", "co", "info", "biz", "edu", "gov"}
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


def extract_probable_file_name(window_title: str | None) -> str | None:
    """Return a conservative bare-file candidate without an extension allowlist.

    This is intentionally stricter than :func:`extract_file_name_from_title`.
    It is used only as the low-confidence fallback after application-specific
    detectors have had first refusal. Obvious URLs, domains, and version numbers
    are rejected so a dotted window title does not become a file merely because
    it contains a period.
    """

    title = (window_title or "").strip()
    if not title or "://" in title:
        return None
    file_name = extract_file_name_from_title(title)
    if not file_name or _VERSION_LIKE_RE.fullmatch(file_name):
        return None

    stem, ext = ntpath.splitext(file_name)
    extension = ext[1:]
    if not stem.strip() or not extension:
        return None
    if len(extension) < 2 or len(extension) > 16:
        return None
    if not any(char.isalpha() for char in extension):
        return None
    if not all(char.isalnum() or char in {"_", "+", "-"} for char in extension):
        return None
    if extension.casefold() in _COMMON_DOMAIN_SUFFIXES:
        domain_stem = stem.strip()
        if domain_stem and re.fullmatch(r"[A-Za-z0-9-]+", domain_stem):
            return None
    return file_name


def normalize_file_name(file_name: str) -> str:
    return _clean_file_name(file_name).casefold()


def _clean_file_name(value: str) -> str:
    cleaned = value.strip().strip(" -—–_|[]()（）")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned
