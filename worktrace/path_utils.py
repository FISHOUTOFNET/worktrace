from __future__ import annotations

import ntpath
import re

from .constants import ANCHOR_FILE_EXTENSIONS

_ANCHOR_EXT_RE = "|".join(re.escape(ext.lstrip(".")) for ext in ANCHOR_FILE_EXTENSIONS)
_ANCHOR_EXT_SET = {item.casefold() for item in ANCHOR_FILE_EXTENSIONS}
_DRIVE_PATH_RE = re.compile(
    rf"(?P<path>[A-Za-z]:[\\/][^\r\n<>|?*]+?\.({_ANCHOR_EXT_RE}))(?=$|[\s\"'）)\]】。；;，,]| - )",
    re.IGNORECASE,
)
_UNC_PATH_RE = re.compile(
    rf"(?P<path>\\\\[^\\/\r\n<>|?*]+[\\/][^\r\n<>|?*]+?\.({_ANCHOR_EXT_RE}))(?=$|[\s\"'）)\]】。；;，,]| - )",
    re.IGNORECASE,
)


def normalize_path_key(path: str) -> str:
    cleaned = _clean_path(path)
    if not cleaned:
        return ""
    cleaned = cleaned.replace("/", "\\")
    if cleaned.startswith("\\\\"):
        cleaned = "\\\\" + re.sub(r"\\+", r"\\", cleaned[2:])
    else:
        cleaned = re.sub(r"\\+", r"\\", cleaned)
    cleaned = _strip_trailing_separators(cleaned)
    return cleaned.casefold()


def normalize_folder_key(path: str) -> str:
    return normalize_path_key(path)


def is_path_under_folder(path: str, folder: str, recursive: bool = True) -> bool:
    path_key = normalize_path_key(path)
    folder_key = normalize_folder_key(folder)
    if not path_key or not folder_key or path_key == folder_key:
        return False
    prefix = folder_key + "\\"
    if not path_key.startswith(prefix):
        return False
    remainder = path_key[len(prefix) :]
    if not remainder:
        return False
    return recursive or "\\" not in remainder


def extract_file_path_from_title(window_title: str | None) -> str | None:
    title = (window_title or "").strip()
    if not title:
        return None
    matches = list(_UNC_PATH_RE.finditer(title)) + list(_DRIVE_PATH_RE.finditer(title))
    if not matches:
        return None
    match = sorted(matches, key=lambda item: item.start())[-1]
    candidate = _clean_path(match.group("path"))
    return candidate if looks_like_anchor_file_path(candidate) else None


def split_file_path(path: str) -> tuple[str, str, str]:
    full_path = _strip_trailing_separators(_clean_path(path).replace("/", "\\"))
    parent_dir = ntpath.dirname(full_path)
    file_name = ntpath.basename(full_path)
    file_stem = ntpath.splitext(file_name)[0]
    return full_path, parent_dir, file_stem


def looks_like_anchor_file_path(path: str | None) -> bool:
    candidate = _clean_path(path or "")
    if not candidate:
        return False
    if not (_is_drive_path(candidate) or _is_unc_path(candidate)):
        return False
    _, ext = ntpath.splitext(candidate)
    return ext.casefold() in _ANCHOR_EXT_SET


def _clean_path(path: str) -> str:
    return str(path or "").strip().strip("\"'“”‘’")


def _strip_trailing_separators(path: str) -> str:
    if _is_drive_root(path) or _is_unc_share_root(path):
        return path
    return path.rstrip("\\/")


def _is_drive_path(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path))


def _is_unc_path(path: str) -> bool:
    return path.startswith("\\\\") and len([part for part in re.split(r"[\\/]+", path) if part]) >= 3


def _is_drive_root(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]?$", path))


def _is_unc_share_root(path: str) -> bool:
    if not path.startswith("\\\\"):
        return False
    return len([part for part in re.split(r"[\\/]+", path) if part]) <= 2
