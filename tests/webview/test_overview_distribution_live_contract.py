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
    source = read_js("overview.js")
    render = func_body(source, "renderProjectDistribution")
    projection = func_body(source, "aggregateLiveProjection")

    assert 'bar.setAttribute("aria-label", "今日总时长分解")' in render
    assert "App.validateLiveClock(segment && segment.live_clock)" in render
    assert "aggregateLiveProjection(clock, durableSeconds, true)" in render
    assert "App.projectLiveClockDurationNow(clock, Date.now())" in projection
    assert "App.computeClockDurationNow" not in source
    assert "App.liveClockDataAttributes" in render
    assert 'data-duration-format="compact-hours"' in render
    assert '"overview-project-distribution"' in render
