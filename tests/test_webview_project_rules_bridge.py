from __future__ import annotations

"""Explicit composition entry for the complete Project Rules bridge contract suite.

The contract cases are retained byte-for-byte in a non-collected support module.
This collected module binds their local constructor name to the canonical test
builder. Production ``WebViewBridge`` is neither patched nor given an optional
composition fallback.
"""

from tests.support import project_rules_bridge_contract_cases as _cases
from tests.support.application import build_test_bridge

_cases.WebViewBridge = build_test_bridge
pytestmark = _cases.pytestmark

for _name, _value in vars(_cases).items():
    if _name.startswith("test_") or hasattr(_value, "_pytestfixturefunction") or hasattr(
        _value, "_fixture_function_marker"
    ):
        globals()[_name] = _value

del _name, _value
