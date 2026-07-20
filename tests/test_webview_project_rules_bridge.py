from __future__ import annotations

"""Explicit composition entry for the complete Project Rules bridge contract suite.

The contract cases remain unchanged in a non-collected support module. This
collected module binds their local constructor symbol to the canonical test
builder before statically importing the test functions. Production
``WebViewBridge`` is never patched and retains its strict services contract.
"""

from tests.support import project_rules_bridge_contract_cases as _cases
from tests.support.application import build_test_bridge

_cases.WebViewBridge = build_test_bridge
pytestmark = _cases.pytestmark

from tests.support.project_rules_bridge_contract_cases import *  # noqa: E402,F403
