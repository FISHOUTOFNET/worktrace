"""Canonical identity helpers for FD Work case labels."""

from __future__ import annotations

import re
from hashlib import sha256

_UNICODE_SPACES = "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
_SPACE_TRANSLATION = str.maketrans({character: " " for character in _UNICODE_SPACES})
_CASE_NUMBER_PREFIX = re.compile(
    r"^#?([0-9]{2}[A-Za-z]{2}[0-9]{4})(?:\s|$)"
)


def normalize_case_label(value: object) -> str:
    return str(value or "").translate(_SPACE_TRANSLATION).strip()


def case_label_hash(value: object) -> str:
    return sha256(normalize_case_label(value).encode("utf-8")).hexdigest()


def extract_case_number(value: object) -> str:
    """Return the canonical leading FD Work case number, when recognized."""

    match = _CASE_NUMBER_PREFIX.match(normalize_case_label(value))
    return match.group(1).upper() if match is not None else ""


def case_search_query(value: object) -> str:
    """Derive the native autocomplete query without weakening label identity."""

    normalized = normalize_case_label(value)
    return extract_case_number(normalized) or normalized


__all__ = [
    "case_label_hash",
    "case_search_query",
    "extract_case_number",
    "normalize_case_label",
]
