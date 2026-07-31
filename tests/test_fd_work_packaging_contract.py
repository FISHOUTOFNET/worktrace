from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = [pytest.mark.contract, pytest.mark.parallel_safe]
ROOT = Path(__file__).resolve().parents[1]


def test_fd_work_adapter_is_explicitly_packaged():
    spec = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'fd_work' / 'fd_work_adapter.js'" in spec
    assert "'worktrace/integrations/fd_work'" in spec


def test_fd_work_does_not_change_database_schema():
    for name in ("schema.sql", "schema_internal.sql", "schema_indexes.sql"):
        source = (ROOT / "worktrace" / name).read_text(encoding="utf-8").lower()
        assert "fd_work" not in source


def test_fd_work_does_not_enter_projection_statistics_export_or_collector_hot_paths():
    protected = (
        ROOT / "worktrace" / "services" / "report_projection_provider.py",
        ROOT / "worktrace" / "services" / "report_projection_builder.py",
        ROOT / "worktrace" / "services" / "statistics_service.py",
        ROOT / "worktrace" / "services" / "export_service.py",
        ROOT / "worktrace" / "collector" / "collector.py",
    )
    for path in protected:
        if path.exists():
            assert "integrations.fd_work" not in path.read_text(encoding="utf-8")
