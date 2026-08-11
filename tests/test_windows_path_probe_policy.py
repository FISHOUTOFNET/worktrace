from __future__ import annotations

import pytest

from worktrace.platforms import windows_path_resolver
from worktrace.platforms.windows_path_resolver import WindowsPathResolver

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


def test_com_capable_word_requires_path_even_without_extension_in_title():
    resolver = WindowsPathResolver()

    assert resolver.privacy_path_required("WINWORD.EXE", "Legal Opinion - Word") is True
    assert resolver.privacy_path_required("Code.exe", "Visual Studio Code") is False


def test_word_com_probe_resolves_full_path_from_stem_only_title(monkeypatch):
    resolver = WindowsPathResolver()
    monkeypatch.setattr(
        windows_path_resolver,
        "_is_registered_prog_id",
        lambda prog_id: prog_id == "Word.Application",
    )
    monkeypatch.setattr(
        windows_path_resolver,
        "_get_com_file_path_subprocess",
        lambda _prog_id, _expression: r"D:\Matter\Legal Opinion.docx",
    )

    resolved = resolver.resolve_active_file_path(
        "winword.exe",
        "Legal Opinion - Word",
        pid=1234,
    )

    assert resolved == r"D:\Matter\Legal Opinion.docx"
