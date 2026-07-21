"""Stage 6 governance: bridge composition and test isolation contracts.

These tests guard the bridge-layer composition invariants required by Stage 6
of the WorkTrace PR #25 finalization:

1. Bridge mixins must not import production module-global API facades. They
   reach the application only through ``self._services.<capability>`` fields
   on the composed ``WebViewBridge``.
2. ``ApplicationServices`` must declare every capability as a required field.
   Optional capabilities (``Optional[...]`` / ``= None`` defaults) would let
   production callers forget to wire a capability and silently degrade the
   bridge surface.
3. Tests must not monkeypatch production module-global application API. The
   only sanctioned replacement point is the capability field on
   ``ApplicationServices``. External boundaries (file system, pywebview, OS
   adapter, time source) may still be patched.
4. Fake capabilities must expose explicit method signatures matching the
   production protocols. Catch-all fakes with ``*args, **kwargs`` would hide
   signature drift between the bridge and the application surface.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKTRACE_ROOT = ROOT / "worktrace"
WEBVIEW_BRIDGE_DIR = WORKTRACE_ROOT / "webview_ui"
TESTS_ROOT = ROOT / "tests"

_BRIDGE_MIXIN_FILES = (
    "bridge_overview.py",
    "bridge_settings.py",
    "bridge_statistics.py",
    "bridge_timeline.py",
    "bridge_rules.py",
)

_PRODUCTION_API_MODULES = (
    "worktrace.api.view_model_api",
    "worktrace.api.settings_api",
    "worktrace.api.statistics_api",
    "worktrace.api.export_api",
    "worktrace.api.project_api",
    "worktrace.api.rule_api",
    "worktrace.api.rule_history_api",
    "worktrace.api.timeline_api",
    "worktrace.api.app_api",
)


def _read_source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_bridge_mixins_do_not_import_production_api_facades() -> None:
    """Bridge mixins must call capabilities through ``self._services`` only.

    The stable ``worktrace.api.errors`` mapping is permitted because it is not
    a facade — it only exposes public error codes/messages. All concrete
    service facades (``view_model_api``, ``settings_api``, ``statistics_api``,
    ``export_api``, ``project_api``, ``rule_api``, ``rule_history_api``,
    ``timeline_api``, ``app_api``) must be reached through ``self._services``.
    """
    forbidden_module_names = {
        api_module.rsplit(".", 1)[-1] for api_module in _PRODUCTION_API_MODULES
    }
    for filename in _BRIDGE_MIXIN_FILES:
        source = _read_source(f"worktrace/webview_ui/{filename}")
        # Disallow deep imports from production API facades (e.g. `from ..api.app_api import X`)
        assert "from ..api." not in source, f"{filename}: from ..api.<module> import"
        # Disallow facade imports via `from ..api import <facade>` or `import <facade>`
        for module_name in forbidden_module_names:
            assert f"import {module_name}" not in source, f"{filename}: import {module_name}"


def test_application_services_has_no_optional_capabilities() -> None:
    """ApplicationServices must require every capability explicitly."""
    source = _read_source("worktrace/api/application_services.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ApplicationServices":
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    annotation = ast.unparse(statement.annotation)
                    assert "Optional" not in annotation, (
                        f"ApplicationServices.{statement.target.id} must not be Optional"
                    )
                    if statement.value is not None:
                        pytest.fail(
                            f"ApplicationServices.{statement.target.id} must not have a default value"
                        )
    # Also assert that ApplicationServices is a frozen dataclass with required fields.
    assert "@dataclass(frozen=True)" in source, "ApplicationServices must be a frozen dataclass"


def test_tests_do_not_monkeypatch_production_api_modules() -> None:
    """Tests must not monkeypatch production module-global API facades.

    The sanctioned replacement point is the capability field on
    ApplicationServices. Patching production module globals would break the
    bridge composition boundary that Stage 6 enforces.
    """
    forbidden_patterns = (
        'monkeypatch.setattr(bridge_rules_module.rule_api',
        'monkeypatch.setattr(bridge_rules_module.project_api',
        'monkeypatch.setattr(bridge_rules_module.rule_history_api',
        'monkeypatch.setattr(bridge_timeline_module.timeline_api',
        'monkeypatch.setattr(bridge_timeline_module.project_api',
        'monkeypatch.setattr(bridge_timeline_module.view_model_api',
        'monkeypatch.setattr(bridge_settings_module.settings_api',
        'monkeypatch.setattr(bridge_statistics_module.statistics_api',
        'monkeypatch.setattr(bridge_statistics_module.export_api',
        'monkeypatch.setattr(bridge_overview_module.view_model_api',
        'patch("worktrace.api.',
        'patch("worktrace.api.',
    )
    for root, _dirs, files in _walk_python_files(TESTS_ROOT):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = Path(root) / filename
            relative = path.relative_to(ROOT).as_posix()
            if relative == "tests/test_stage6_bridge_composition_governance.py":
                continue
            source = path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                assert pattern not in source, f"{relative}: forbidden monkeypatch pattern {pattern!r}"


def test_fake_capabilities_expose_explicit_signatures() -> None:
    """Fake capabilities must declare explicit method signatures.

    Catch-all fakes using ``*args, **kwargs`` would hide signature drift
    between the bridge surface and the capability protocols.
    """
    from tests.support import application as support

    fake_classes = (
        support.FakeOverviewCapability,
        support.FakeSettingsCapability,
        support.FakeBackupCapability,
        support.FakeStatisticsCapability,
        support.FakeTimelineCapability,
        support.FakeRulesCapability,
    )
    for fake_cls in fake_classes:
        for name, member in inspect.getmembers(fake_cls, predicate=inspect.isfunction):
            if name.startswith("_") or name in {"__init__"}:
                continue
            signature = inspect.signature(member)
            for parameter_name, parameter in signature.parameters.items():
                if parameter_name == "self":
                    continue
                assert parameter.kind not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ), (
                    f"{fake_cls.__name__}.{name} must not accept *args or **kwargs "
                    f"(parameter {parameter_name!r} is {parameter.kind})"
                )


def test_bridge_mixins_do_not_use_dynamic_capability_probes() -> None:
    """Bridge mixins must not dynamically probe for capabilities at runtime.

    Dynamic probes (``getattr(self._services, ...)`` or
    ``hasattr(self._services, ...)``) would let a caller forget to wire a
    capability and silently degrade the bridge surface. Every capability
    must be a required field reached through direct attribute access.
    """
    forbidden_patterns = (
        "getattr(self._services",
        "hasattr(self._services",
        "getattr(self.services",
        "hasattr(self.services",
    )
    for filename in _BRIDGE_MIXIN_FILES:
        source = _read_source(f"worktrace/webview_ui/{filename}")
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"{filename}: dynamic capability probe {pattern!r} is forbidden; "
                "use a required field on ApplicationServices instead"
            )


def test_bridge_delete_and_archive_methods_have_no_default_parameters() -> None:
    """Bridge delete/archive methods must require every argument explicitly.

    Default parameters on delete/archive methods would allow callers to omit
    critical arguments (e.g. ``apply_to_history``) and silently change
    semantics. Every argument must be required.
    """
    for filename in _BRIDGE_MIXIN_FILES:
        source = _read_source(f"worktrace/webview_ui/{filename}")
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not (node.name.startswith("delete_") or node.name.startswith("archive_")):
                continue
            args = node.args
            defaults = list(args.defaults)
            kw_defaults = list(args.kw_defaults)
            assert not defaults, (
                f"{filename}:{node.name}: positional defaults are forbidden "
                f"on delete/archive methods (found {len(defaults)})"
            )
            assert not kw_defaults, (
                f"{filename}:{node.name}: keyword-only defaults are forbidden "
                f"on delete/archive methods (found {len(kw_defaults)})"
            )


def _walk_python_files(root: Path):
    for root_str, dirs, files in root.walk() if hasattr(root, "walk") else _legacy_walk(root):
        yield root_str, dirs, files


def _legacy_walk(root: Path):
    import os
    for entry in os.walk(str(root)):
        yield entry[0], entry[1], entry[2]
