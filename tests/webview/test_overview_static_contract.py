from __future__ import annotations

import os
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import func_body, read_js


def test_overview_status_only_recent_rows_do_not_use_project_name_as_status_title():
    body = func_body(read_js("overview.js"), "showRecent")

    assert 'item.row_kind === "status_only"' in body
    assert "var titleText = isStatusOnly" in body
    assert "item.display_status || item.status_label" in body
    assert "App.formatProjectLabel(item.project_name, item.project_description)" in body

    status_branch_start = body.find("var titleText = isStatusOnly")
    normal_project_start = body.find("App.formatProjectLabel", status_branch_start)
    status_branch = body[status_branch_start:normal_project_start]
    assert "item.project_name" not in status_branch
