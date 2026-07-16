from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract]


def test_pyinstaller_spec_bundles_every_database_schema_resource():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "WorkTrace.spec").read_text(encoding="utf-8")

    for name in ("schema.sql", "schema_internal.sql", "schema_indexes.sql"):
        assert (root / "worktrace" / name).is_file()
        assert name in spec
