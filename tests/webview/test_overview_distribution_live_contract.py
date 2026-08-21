from __future__ import annotations

import os
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from static_helpers import func_body, read_js  # noqa: E402


def test_overview_distribution_reuses_shared_live_clock_targets():
    render = func_body(read_js("overview.js"), "renderProjectDistribution")

    assert 'bar.setAttribute("aria-label", "今日总时长分解")' in render
    assert "App.validateLiveClock(segment && segment.live_clock)" in render
    assert "App.computeClockDurationNow(clock, Date.now())" in render
    assert "App.liveClockDataAttributes" in render
    assert 'data-duration-format="compact-hours"' in render
    assert '"overview-project-distribution"' in render
