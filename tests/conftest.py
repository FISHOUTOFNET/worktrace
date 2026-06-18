from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worktrace import db


@pytest.fixture()
def temp_db(tmp_path):
    path = tmp_path / "worktrace.db"
    db.initialize_database(path)
    return path
