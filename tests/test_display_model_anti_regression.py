from __future__ import annotations

from worktrace.api import view_model_api


def test_view_model_api_does_not_export_revision_alias_builder():
    assert not hasattr(view_model_api, "compute_refresh_revision")
