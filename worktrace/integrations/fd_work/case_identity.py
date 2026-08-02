"""Canonical identity helpers for FD Work case labels."""

from __future__ import annotations

from hashlib import sha256

_UNICODE_SPACES = "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
_SPACE_TRANSLATION = str.maketrans({character: " " for character in _UNICODE_SPACES})


def normalize_case_label(value: object) -> str:
    return str(value or "").translate(_SPACE_TRANSLATION).strip()


def case_label_hash(value: object) -> str:
    return sha256(normalize_case_label(value).encode("utf-8")).hexdigest()


__all__ = ["case_label_hash", "normalize_case_label"]
