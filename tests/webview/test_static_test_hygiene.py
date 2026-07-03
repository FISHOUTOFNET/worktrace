"""Anti-regression hygiene tests for WebView static contract test files.

Scans ``tests/webview/test_*.py`` to forbid reintroduction of:
- ``pytest_collection_modifyitems`` / ``item._obj`` (collection-time workaround).
- Fixed character window slicing (``source[pos:pos + N]`` where N > 1).
- The deleted ``tests/webview/conftest.py``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import REPO_ROOT  # noqa: E402

WEBVIEW_TEST_DIR = Path(_HERE)
_HYGIENE_FILE_NAME = os.path.basename(__file__)


def _read_test_files() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for path in sorted(WEBVIEW_TEST_DIR.glob("test_*.py")):
        if path.name == _HYGIENE_FILE_NAME:
            continue
        results.append((path.name, path.read_text(encoding="utf-8")))
    return results


_COLLECTION_HOOK_RE = re.compile(r"pytest_collection_modifyitems")
_ITEM_OBJ_RE = re.compile(r"item\._obj")


def test_no_collection_modifyitems_or_item_obj_replacement():
    for name, source in _read_test_files():
        assert not _COLLECTION_HOOK_RE.search(source), (
            name + " must not use pytest_collection_modifyitems"
        )
        assert not _ITEM_OBJ_RE.search(source), (
            name + " must not replace item._obj"
        )


_PLUS = r"\+"
_WS = r"\s*"
_DIGITS = r"\d+"
_FIXED_WINDOW_RE = re.compile(
    r"(?<![\w])(source|body|section|snippet)"
    + _WS + r"\[" + r"[^\]]*?" + r":"
    + r"[^\]]*?" + _PLUS + _WS
    + r"(" + _DIGITS + r")" + r"[^\]]*?" + r"\]"
)


def test_no_fixed_character_window_slicing():
    offenders: list[str] = []
    for name, source in _read_test_files():
        for line_no, line in enumerate(source.splitlines(), 1):
            for match in _FIXED_WINDOW_RE.finditer(line):
                if match.group(2) == "1":
                    continue
                offenders.append(name + ":" + str(line_no) + ": " + line.strip())
    assert not offenders, (
        "Fixed window slicing found. Use func_body / html_section_by_id / "
        "html_element_by_id / js_catch_block or real boundaries instead:\n"
        + "\n".join(offenders)
    )


def test_no_conftest_py_in_webview_tests():
    conftest_path = WEBVIEW_TEST_DIR / "conftest.py"
    assert not conftest_path.exists(), (
        "tests/webview/conftest.py must not exist"
    )
