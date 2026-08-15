"""Versioned privacy policy metadata and bundled policy text."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

PRIVACY_POLICY_VERSION = "1"
PRIVACY_POLICY_EFFECTIVE_DATE = "2026-08-15"
PRIVACY_POLICY_TITLE = "有迹隐私政策"
PRIVACY_NOTICE_TITLE = "隐私与数据"
PRIVACY_NOTICE_HIGHLIGHTS = (
    "本地优先",
    "不主动读取正文",
    "不截屏录屏",
    "复制文字默认关闭",
)


def _policy_path() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "worktrace" / "privacy_policy_zh-CN.txt"
    return Path(__file__).resolve().with_name("privacy_policy_zh-CN.txt")


@lru_cache(maxsize=1)
def get_privacy_policy_text() -> str:
    """Return the exact policy text shipped with this application build."""

    return _policy_path().read_text(encoding="utf-8").strip()


PRIVACY_POLICY_TEXT = get_privacy_policy_text()


__all__ = [
    "PRIVACY_NOTICE_HIGHLIGHTS",
    "PRIVACY_NOTICE_TITLE",
    "PRIVACY_POLICY_EFFECTIVE_DATE",
    "PRIVACY_POLICY_TEXT",
    "PRIVACY_POLICY_TITLE",
    "PRIVACY_POLICY_VERSION",
    "get_privacy_policy_text",
]
