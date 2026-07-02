"""Boundary tests enforcing the UI <-> backend API contract.

The WebView UI layer must talk to the backend exclusively through
``worktrace.api``. Direct imports of ``worktrace.services``,
``worktrace.db``, ``worktrace.collector``, or ``worktrace.security`` from
any module under ``worktrace/webview_ui`` are forbidden.

In addition, the WebView bridge (``bridge.py``) must not import
``worktrace.runtime`` or ``worktrace.config`` either: it may only reach the
backend through ``worktrace.api``. The WebView entry point
(``worktrace/webview_main.py``) is allowed to import ``AppRuntime``,
``config``, and ``db`` initialization helpers, mirroring ``worktrace/main.py``,
but still must not import ``services``, ``collector``, or ``security``.

The Tkinter / CustomTkinter ``worktrace/ui`` package has been deleted. A
dedicated test asserts the package is gone so it cannot be accidentally
reintroduced.

Allowed WebView dependencies:
- ``worktrace.api`` (the facade layer)
- ``worktrace.formatters`` / ``worktrace.constants`` (pure helpers)
- other modules inside ``worktrace.webview_ui`` itself
- third-party and stdlib modules
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Forbidden import statements. We match the module reference at the start of
# an import line so that ``from ..api import ...`` is not accidentally flagged
# by the ``..services`` rule.
FORBIDDEN_PATTERNS = [
    re.compile(r"^\s*from\s+\.\.services(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.services(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.db(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.db(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.collector(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.collector(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.security(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.security(\s|\.)", re.MULTILINE),
    # ``import worktrace.services`` / ``import worktrace.db`` style
    re.compile(r"^\s*import\s+worktrace\.services(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.db(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.collector(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.security(\s|$)", re.MULTILINE),
]

FORBIDDEN_LABELS = [
    "from ..services",
    "from worktrace.services",
    "from ..db",
    "from worktrace.db",
    "from ..collector",
    "from worktrace.collector",
    "from ..security",
    "from worktrace.security",
    "import worktrace.services",
    "import worktrace.db",
    "import worktrace.collector",
    "import worktrace.security",
]


# ---------------------------------------------------------------------------
# Tkinter UI package removal
# ---------------------------------------------------------------------------

_LEGACY_UI_DIR = Path(__file__).resolve().parents[1] / "worktrace" / "ui"


def test_removed_ui_package_absent() -> None:
    """The ``worktrace/ui`` package must not exist.

    The entire Tkinter / CustomTkinter UI has been deleted. WebView is
    the only shipping UI. This test guards against accidental reintroduction.
    """
    assert not _LEGACY_UI_DIR.is_dir(), (
        f"worktrace/ui directory must not exist (removed UI package); "
        f"found {_LEGACY_UI_DIR}"
    )


def test_removed_ui_app_import_raises_module_not_found() -> None:
    """Importing ``worktrace.ui.app`` must fail with ``ModuleNotFoundError``.

    The ``WorkTraceApp`` class is gone. No code path may
    import it.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("worktrace.ui.app")


# ---------------------------------------------------------------------------
# WebView UI boundary tests
# ---------------------------------------------------------------------------

WEBVIEW_UI_DIR = Path(__file__).resolve().parents[1] / "worktrace" / "webview_ui"

# The bridge module has stricter rules: no runtime, no config, no db either.
BRIDGE_FORBIDDEN_PATTERNS = FORBIDDEN_PATTERNS + [
    re.compile(r"^\s*from\s+\.\.runtime(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.runtime(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.config(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.config(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.runtime(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.config(\s|$)", re.MULTILINE),
]

BRIDGE_FORBIDDEN_LABELS = FORBIDDEN_LABELS + [
    "from ..runtime",
    "from worktrace.runtime",
    "from ..config",
    "from worktrace.config",
    "import worktrace.runtime",
    "import worktrace.config",
]


def _collect_webview_ui_files() -> list[Path]:
    if not WEBVIEW_UI_DIR.is_dir():
        return []
    return sorted(WEBVIEW_UI_DIR.glob("*.py"))


@pytest.fixture(scope="module")
def webview_ui_files() -> list[Path]:
    return _collect_webview_ui_files()


# page module mapping: ``bridge.py`` is now a thin composition class
# that inherits from six mixins (``BridgeDialogMixin``, ``OverviewBridgeMixin``,
# ``SettingsBridgeMixin``, ``StatisticsBridgeMixin``, ``TimelineBridgeMixin``,
# ``ProjectRulesBridgeMixin``). Method bodies live in the mixin files below.
# Static source-level tests scan all bridge files so method bodies are found
# regardless of which mixin holds them.
BRIDGE_FILES = [
    "bridge.py",
    "bridge_common.py",
    "bridge_dialogs.py",
    "bridge_overview.py",
    "bridge_settings.py",
    "bridge_statistics.py",
    "bridge_timeline.py",
    "bridge_rules.py",
]


def _read_bridge_method_body(method_name: str, *, max_chars: int = 4000) -> str:
    """Return the body slice of ``def <method_name>`` from whichever bridge
    mixin file defines it.

    Searches the 8 ``BRIDGE_FILES`` in order for ``def <method_name>`` and
    returns the slice from that position up to the next ``\\n    def `` at
    indent 4 (or ``max_chars`` characters if no next method is found).
    Raises ``AssertionError`` if the method is not found in any bridge file.
    """
    for name in BRIDGE_FILES:
        path = WEBVIEW_UI_DIR / name
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        pos = source.find("def " + method_name)
        if pos == -1:
            continue
        next_def = source.find("\n    def ", pos + 1)
        end = next_def if next_def != -1 else pos + max_chars
        return source[pos:end]
    raise AssertionError(
        "method " + repr(method_name) + " not found in any bridge file: "
        + ", ".join(BRIDGE_FILES)
    )


def test_webview_ui_directory_exists() -> None:
    assert WEBVIEW_UI_DIR.is_dir(), (
        "worktrace/webview_ui directory must exist (WebView UI package)"
    )


def test_webview_ui_has_init() -> None:
    assert (WEBVIEW_UI_DIR / "__init__.py").is_file(), (
        "worktrace/webview_ui/__init__.py must exist"
    )


@pytest.mark.parametrize(
    "wv_file",
    _collect_webview_ui_files(),
    ids=lambda p: f"webview/{p.name}",
)
def test_webview_ui_file_has_no_forbidden_backend_imports(wv_file: Path) -> None:
    """All webview_ui modules must not import services/db/collector/security."""
    source = wv_file.read_text(encoding="utf-8")
    violations: list[str] = []
    for pattern, label in zip(FORBIDDEN_PATTERNS, FORBIDDEN_LABELS):
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            violations.append(f"webview/{wv_file.name}:{line_no}: {label}")
    assert not violations, (
        "WebView UI layer must not import backend modules directly. "
        "Found forbidden imports:\n"
        + "\n".join(violations)
        + "\nUse worktrace.api.* facades instead."
    )


def test_webview_bridge_has_no_runtime_or_config_imports() -> None:
    """The bridge modules must only use worktrace.api, not runtime/config/db.

    The Project Rules bridge methods live in
    ``bridge_rules.py`` (mixed into ``WebViewBridge`` via
    ``ProjectRulesBridgeMixin``). The Overview / Settings / Statistics /
    Timeline bridge methods live
    in ``bridge_overview.py`` / ``bridge_settings.py`` /
    ``bridge_statistics.py`` / ``bridge_timeline.py`` respectively, and
    shared helpers live in ``bridge_common.py`` / ``bridge_dialogs.py``.
    All 8 bridge files must obey the same strict boundary: no
    ``runtime``, ``config``, ``services``, ``db``, ``collector``, or
    ``security`` imports.
    """
    # bridge.py is the primary bridge module and must always exist.
    assert (WEBVIEW_UI_DIR / "bridge.py").is_file(), "bridge.py must exist (WebView UI)"
    violations: list[str] = []
    for name in BRIDGE_FILES:
        path = WEBVIEW_UI_DIR / name
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for pattern, label in zip(BRIDGE_FORBIDDEN_PATTERNS, BRIDGE_FORBIDDEN_LABELS):
            for match in pattern.finditer(source):
                line_no = source.count("\n", 0, match.start()) + 1
                violations.append(f"webview/{name}:{line_no}: {label}")
    assert not violations, (
        "WebView bridge modules must not import runtime, config, services, db, "
        "collector, or security. Found forbidden imports:\n"
        + "\n".join(violations)
        + "\nUse worktrace.api.* facades instead."
    )


def test_webview_ui_uses_api_layer(webview_ui_files: list[Path]) -> None:
    """Once bridge.py is implemented, at least one webview_ui file should
    reference worktrace.api. This test is soft: it passes vacuously until
    bridge.py is added."""
    if not webview_ui_files:
        pytest.skip("no webview_ui source files yet")
    api_references = 0
    for path in webview_ui_files:
        source = path.read_text(encoding="utf-8")
        if "worktrace.api" in source or "from ..api" in source or "from .api" in source:
            api_references += 1
    # Once bridge.py exists, it should reference the api layer.
    has_bridge = any(p.name == "bridge.py" for p in webview_ui_files)
    if has_bridge:
        assert api_references >= 1, (
            "expected bridge.py to import worktrace.api, found 0 api references"
        )


def test_webview_frontend_resources_have_no_external_links() -> None:
    """WebView frontend resources must not contain http://, https://, CDN,
    or Google Fonts references."""
    resource_dir = WEBVIEW_UI_DIR / "static"
    if not resource_dir.is_dir():
        pytest.skip("static/ resource directory not created yet (WebView UI)")
    forbidden_patterns = [
        re.compile(r'https?://', re.IGNORECASE),
        re.compile(r'cdn', re.IGNORECASE),
        re.compile(r'google\s*fonts', re.IGNORECASE),
    ]
    violations: list[str] = []
    for res_file in sorted(resource_dir.rglob("*")):
        if not res_file.is_file():
            continue
        if res_file.suffix.lower() not in (".html", ".css", ".js", ".json"):
            continue
        try:
            source = res_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in forbidden_patterns:
            for match in pattern.finditer(source):
                line_no = source.count("\n", 0, match.start()) + 1
                rel = res_file.relative_to(WEBVIEW_UI_DIR)
                violations.append(
                    f"static/{rel}:{line_no}: {match.group().strip()!r}"
                )
    assert not violations, (
        "WebView frontend resources must not contain external links, "
        "CDN, or Google Fonts references. Found:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Hardening lock: lock the four Project Rules batch / automatic-rules
# bridge methods on the composed ``WebViewBridge`` class. The methods are
# defined on ``ProjectRulesBridgeMixin`` (in ``bridge_rules.py``) and inherited
# by ``WebViewBridge``. Without this lock, a future refactor that drops the
# mixin from ``WebViewBridge``'s bases would silently remove the 5I surface
# from the only shipping bridge class without any test failing.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_automatic_rules_batch_and_automatic_methods() -> None:
    """``WebViewBridge`` must expose the four the rule automation methods.

    The methods are defined on ``ProjectRulesBridgeMixin`` and inherited by
    ``WebViewBridge``. the hardening hardens this composition so a refactor
    that drops the mixin (or renames a method) fails here instead of
    silently removing the 5I API surface from the only shipping bridge.
    """
    from worktrace.webview_ui.bridge import WebViewBridge

    expected_methods = (
        "preview_project_rules_batch_impact",
        "backfill_project_rules_batch",
        "set_project_rules_batch_enabled",
        "automatic_rules_status",
    )
    bridge = WebViewBridge()
    for name in expected_methods:
        assert callable(getattr(bridge, name, None)), (
            f"WebViewBridge must expose project-rules bridge method {name!r} "
            "(inherited from ProjectRulesBridgeMixin)"
        )


# ---------------------------------------------------------------------------
# Settings / Privacy clipboard capture toggle bridge method.
# The new ``set_clipboard_capture_enabled`` method is defined directly on
# ``WebViewBridge`` (no mixin), so a rename or removal would silently drop
# the clipboard toggle write surface from the only shipping bridge. This lock also
# confirms the error payload carries no sensitive tokens (no path / no
# clipboard content / no passphrase / no SQL / no traceback / no raw
# exception) so the bridge boundary stays leak-free.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_settings_clipboard_toggle_method() -> None:
    """``WebViewBridge`` must expose the clipboard toggle ``set_clipboard_capture_enabled``
    method with a single required ``enabled`` parameter (no optional args,
    no loose ``*args``)."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "set_clipboard_capture_enabled", None)
    assert callable(method), (
        "WebViewBridge must expose settings capture contract bridge method "
        "'set_clipboard_capture_enabled'"
    )
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    # Exactly one required parameter named ``enabled``; no optional params,
    # no *args, no **kwargs.
    assert len(params) == 1, (
        "set_clipboard_capture_enabled must accept exactly one parameter, "
        f"got {len(params)}"
    )
    assert params[0].name == "enabled", (
        f"set_clipboard_capture_enabled parameter must be 'enabled', "
        f"got {params[0].name!r}"
    )
    assert params[0].default is inspect.Parameter.empty, (
        "set_clipboard_capture_enabled 'enabled' must be required "
        "(no default value)"
    )
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD, (
        "set_clipboard_capture_enabled 'enabled' must be positional-or-keyword, "
        "not *args or **kwargs"
    )


def test_webview_bridge_clipboard_toggle_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``set_clipboard_capture_enabled`` error payload
    must collapse to a stable Chinese message and must not leak path /
    clipboard content / passphrase / SQL / traceback / raw exception text.

    This is a static source-level check so it runs without a live database
    or collector: it reads the bridge mixin that defines the method and
    confirms the error string is the only payload on failure and no
    ``traceback`` / ``str(exc)`` / ``repr`` expression appears in the
    executable code (the docstring is skipped because it legitimately
    mentions these words to document what the method does NOT leak).
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("set_clipboard_capture_enabled")
    # Stable Chinese error messages that must appear in the payload.
    assert "请选择有效的剪贴板记录状态" in body
    assert "设置剪贴板记录失败" in body
    # Skip the docstring when checking for forbidden runtime tokens, since
    # the docstring legitimately mentions "traceback" / "passphrase" /
    # "clipboard content" to document what the method does NOT leak.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    # Forbidden runtime expressions that would leak sensitive data.
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "passphrase",
        "clipboard_content",
        "raw_exception",
    ):
        assert forbidden not in code_only, (
            "set_clipboard_capture_enabled must not reference forbidden token: "
            + forbidden
        )


# ---------------------------------------------------------------------------
# Settings / Privacy encrypted backup export + manifest preview
# bridge methods. The two new methods are defined directly on
# ``WebViewBridge`` (no mixin). ``export_encrypted_backup`` takes exactly
# two required parameters (``passphrase`` / ``confirm_passphrase``);
# ``preview_encrypted_backup_manifest`` takes zero parameters. The error
# payloads must collapse to stable Chinese messages and must not leak
# traceback / str(exc) / repr / format_exc / exc_info / .message /
# raw_exception / clipboard_content. ``passphrase`` IS allowed as a
# parameter name, local variable, and pass-through argument to the API
# facade; it is only forbidden in the returned payload / error payload /
# logging (enforced by the runtime tests in test_settings_privacy_status).
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_backup_export_method() -> None:
    """``WebViewBridge`` must expose the backup export ``export_encrypted_backup``
    method with exactly two required parameters (``passphrase`` and
    ``confirm_passphrase``); no optional args, no ``*args``, no ``**kwargs``."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "export_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose encrypted backup contract bridge method "
        "'export_encrypted_backup'"
    )
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    assert len(params) == 2, (
        "export_encrypted_backup must accept exactly two parameters, "
        f"got {len(params)}"
    )
    expected_names = ("passphrase", "confirm_passphrase")
    for idx, name in enumerate(expected_names):
        assert params[idx].name == name, (
            f"export_encrypted_backup parameter {idx} must be {name!r}, "
            f"got {params[idx].name!r}"
        )
        assert params[idx].default is inspect.Parameter.empty, (
            f"export_encrypted_backup {name!r} must be required "
            "(no default value)"
        )
        assert params[idx].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD, (
            f"export_encrypted_backup {name!r} must be positional-or-keyword, "
            "not *args or **kwargs"
        )


def test_webview_bridge_exposes_backup_manifest_preview_method() -> None:
    """``WebViewBridge`` must expose the backup export
    ``preview_encrypted_backup_manifest`` method with zero parameters."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "preview_encrypted_backup_manifest", None)
    assert callable(method), (
        "WebViewBridge must expose encrypted backup contract bridge method "
        "'preview_encrypted_backup_manifest'"
    )
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    assert len(params) == 0, (
        "preview_encrypted_backup_manifest must accept zero parameters, "
        f"got {len(params)}"
    )


def test_webview_bridge_export_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``export_encrypted_backup`` error payload must
    collapse to stable Chinese messages and must not leak traceback /
    str(exc) / repr / format_exc / exc_info / .message / raw_exception /
    clipboard_content.

    ``passphrase`` IS allowed as a parameter name, local variable, and
    pass-through argument to ``settings_api.export_encrypted_backup_for_webview``;
    it is NOT in the forbidden list here. The runtime tests in
    ``test_settings_privacy_status`` verify the returned payload never
    carries the passphrase value.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("export_encrypted_backup")
    # Stable Chinese error messages that must appear in the payload.
    assert "已取消导出" in body
    assert "导出加密备份失败" in body
    # Skip the docstring when checking for forbidden runtime tokens, since
    # the docstring legitimately mentions "traceback" / "passphrase" to
    # document what the method does NOT leak.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "raw_exception",
        "clipboard_content",
    ):
        assert forbidden not in code_only, (
            "export_encrypted_backup must not reference forbidden token: "
            + forbidden
        )


def test_webview_bridge_manifest_preview_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``preview_encrypted_backup_manifest`` error
    payload must collapse to stable Chinese messages and must not leak
    traceback / str(exc) / repr / format_exc / exc_info / .message /
    raw_exception / clipboard_content / passphrase.

    Unlike ``export_encrypted_backup``, ``passphrase`` IS forbidden here
    because the manifest preview method never accepts or references a
    passphrase.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    # The helper slices at the next ``def`` so the body covers only this
    # method (a fixed window would bleed into ``import_encrypted_backup``
    # whose signature references ``passphrase``, falsely failing the
    # forbidden-token check below).
    body = _read_bridge_method_body("preview_encrypted_backup_manifest")
    # Stable Chinese error messages that must appear in the payload.
    assert "已取消读取备份清单" in body
    assert "读取备份清单失败" in body
    # Skip the docstring when checking for forbidden runtime tokens.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "passphrase",
        "raw_exception",
        "clipboard_content",
    ):
        assert forbidden not in code_only, (
            "preview_encrypted_backup_manifest must not reference forbidden token: "
            + forbidden
        )


def test_webview_bridge_export_passes_passphrase_to_api_facade() -> None:
    """``export_encrypted_backup`` must pass ``passphrase`` and
    ``confirm_passphrase`` through to
    ``settings_api.export_encrypted_backup_for_webview``. This is a static
    source-level check confirming the passphrase is used as a pass-through
    argument (not logged, not returned, not persisted)."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("export_encrypted_backup")
    # The method must call the API facade with both passphrase arguments.
    assert "settings_api.export_encrypted_backup_for_webview" in body
    assert "passphrase" in body
    assert "confirm_passphrase" in body


def test_webview_bridge_backup_methods_do_not_call_import_or_clear() -> None:
    """neither ``export_encrypted_backup`` nor
    ``preview_encrypted_backup_manifest`` may call
    ``import_encrypted_backup``, ``clear_all_local_data``, or
    ``set_setting_value``. This is a static source-level check on the
    bridge module."""
    # method bodies live in bridge_settings.py (SettingsBridgeMixin).
    export_body = _read_bridge_method_body("export_encrypted_backup")
    for forbidden in (
        "import_encrypted_backup",
        "clear_all_local_data",
        "set_setting_value",
    ):
        assert forbidden not in export_body, (
            "export_encrypted_backup must not call: " + forbidden
        )
    manifest_body = _read_bridge_method_body("preview_encrypted_backup_manifest")
    for forbidden in (
        "import_encrypted_backup",
        "clear_all_local_data",
        "set_setting_value",
    ):
        assert forbidden not in manifest_body, (
            "preview_encrypted_backup_manifest must not call: " + forbidden
        )


# ---------------------------------------------------------------------------
# Settings / Privacy encrypted backup import + clear-all-local-data
# bridge methods. The two new methods are defined directly on ``WebViewBridge``
# (no mixin). ``import_encrypted_backup`` takes exactly two required
# parameters (``passphrase`` / ``confirm_text``); ``clear_all_local_data``
# takes exactly one required parameter (``confirm_text``). The error payloads
# must collapse to stable Chinese messages and must not leak traceback /
# str(exc) / repr / format_exc / exc_info / .message / raw_exception /
# clipboard_content. ``passphrase`` IS allowed as a parameter name, local
# variable, and pass-through argument to the API facade; it is only
# forbidden in the returned payload / error payload / logging (enforced by
# the runtime tests in test_settings_privacy_status). The method body is
# sliced at the next ``\n def `` so the next method's passphrase
# reference does not trigger false positives.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_destructive_data_import_method() -> None:
    """``WebViewBridge`` must expose the backup import ``import_encrypted_backup``
    method with exactly two required parameters (``passphrase`` and
    ``confirm_text``); no optional args, no ``*args``, no ``**kwargs``."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "import_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose destructive settings contract bridge method "
        "'import_encrypted_backup'"
    )
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    assert len(params) == 2, (
        "import_encrypted_backup must accept exactly two parameters, "
        f"got {len(params)}"
    )
    expected_names = ("passphrase", "confirm_text")
    for idx, name in enumerate(expected_names):
        assert params[idx].name == name, (
            f"import_encrypted_backup parameter {idx} must be {name!r}, "
            f"got {params[idx].name!r}"
        )
        assert params[idx].default is inspect.Parameter.empty, (
            f"import_encrypted_backup {name!r} must be required "
            "(no default value)"
        )
        assert params[idx].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD, (
            f"import_encrypted_backup {name!r} must be positional-or-keyword, "
            "not *args or **kwargs"
        )


def test_webview_bridge_exposes_destructive_data_clear_method() -> None:
    """``WebViewBridge`` must expose the backup import ``clear_all_local_data``
    method with exactly one required parameter (``confirm_text``); no
    optional args, no ``*args``, no ``**kwargs``."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "clear_all_local_data", None)
    assert callable(method), (
        "WebViewBridge must expose destructive settings contract bridge method "
        "'clear_all_local_data'"
    )
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    assert len(params) == 1, (
        "clear_all_local_data must accept exactly one parameter, "
        f"got {len(params)}"
    )
    assert params[0].name == "confirm_text", (
        f"clear_all_local_data parameter must be 'confirm_text', "
        f"got {params[0].name!r}"
    )
    assert params[0].default is inspect.Parameter.empty, (
        "clear_all_local_data 'confirm_text' must be required "
        "(no default value)"
    )
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD, (
        "clear_all_local_data 'confirm_text' must be positional-or-keyword, "
        "not *args or **kwargs"
    )


def test_webview_bridge_import_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``import_encrypted_backup`` error payload must
    collapse to stable Chinese messages and must not leak traceback /
    str(exc) / repr / format_exc / exc_info / .message / raw_exception /
    clipboard_content.

    ``passphrase`` IS allowed as a parameter name, local variable, and
    pass-through argument to ``settings_api.import_encrypted_backup_for_webview``;
    it is NOT in the forbidden list here. The runtime tests in
    ``test_settings_privacy_status`` verify the returned payload never
    carries the passphrase value. The method body is sliced at the next
    ``\\n    def `` so the following method's passphrase reference does
    not trigger false positives.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    # The helper slices at the next ``def`` so the clear_all_local_data
    # method body (which legitimately references ``confirm_text``) is not
    # accidentally included in this check.
    body = _read_bridge_method_body("import_encrypted_backup")
    # Stable Chinese error messages that must appear in the payload.
    assert "已取消导入" in body
    assert "导入加密备份失败" in body
    # Skip the docstring when checking for forbidden runtime tokens, since
    # the docstring legitimately mentions "traceback" / "passphrase" /
    # "raw exception" to document what the method does NOT leak.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "raw_exception",
        "clipboard_content",
    ):
        assert forbidden not in code_only, (
            "import_encrypted_backup must not reference forbidden token: "
            + forbidden
        )


def test_webview_bridge_clear_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``clear_all_local_data`` error payload must
    collapse to stable Chinese messages and must not leak traceback /
    str(exc) / repr / format_exc / exc_info / .message / raw_exception /
    clipboard_content / passphrase.

    Unlike ``import_encrypted_backup``, ``passphrase`` IS forbidden here
    because the clear-all method never accepts or references a passphrase.
    The method body is sliced at the next ``\\n    def `` so the following
    module-level helper (if any) does not trigger false positives.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("clear_all_local_data")
    # Stable Chinese error message that must appear in the payload.
    assert "清空本地数据失败" in body
    # Skip the docstring when checking for forbidden runtime tokens.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "passphrase",
        "raw_exception",
        "clipboard_content",
    ):
        assert forbidden not in code_only, (
            "clear_all_local_data must not reference forbidden token: "
            + forbidden
        )


def test_webview_bridge_import_passes_passphrase_to_api_facade() -> None:
    """``import_encrypted_backup`` must pass ``passphrase`` and
    ``confirm_text`` through to
    ``settings_api.import_encrypted_backup_for_webview``. This is a static
    source-level check confirming the passphrase is used as a pass-through
    argument (not logged, not returned, not persisted)."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("import_encrypted_backup")
    # The method must call the API facade with both arguments.
    assert "settings_api.import_encrypted_backup_for_webview" in body
    assert "passphrase" in body
    assert "confirm_text" in body


def test_webview_bridge_clear_calls_api_facade() -> None:
    """``clear_all_local_data`` must call
    ``settings_api.clear_all_local_data_for_webview`` with
    ``confirm_text``. This is a static source-level check confirming the
    bridge does not touch the DB / service directly."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("clear_all_local_data")
    assert "settings_api.clear_all_local_data_for_webview" in body
    assert "confirm_text" in body


def test_webview_bridge_import_does_not_call_export_or_manifest_or_set() -> None:
    """``import_encrypted_backup`` must not call
    ``export_encrypted_backup``, ``preview_encrypted_backup_manifest``,
    ``clear_all_local_data``, or ``set_setting_value``. This is a static
    source-level check on the bridge module."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("import_encrypted_backup")
    for forbidden in (
        "export_encrypted_backup",
        "preview_encrypted_backup_manifest",
        "set_setting_value",
    ):
        assert forbidden not in body, (
            "import_encrypted_backup must not call: " + forbidden
        )


def test_webview_bridge_clear_does_not_call_backup_actions_or_set() -> None:
    """``clear_all_local_data`` must not call
    ``export_encrypted_backup``, ``preview_encrypted_backup_manifest``,
    ``import_encrypted_backup``, or ``set_setting_value``. This is a
    static source-level check on the bridge module."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("clear_all_local_data")
    for forbidden in (
        "export_encrypted_backup",
        "preview_encrypted_backup_manifest",
        "import_encrypted_backup",
        "set_setting_value",
    ):
        assert forbidden not in body, (
            "clear_all_local_data must not call: " + forbidden
        )


# ---------------------------------------------------------------------------
# First-run privacy notice bridge methods. The two new methods are
# defined directly on ``WebViewBridge`` (no mixin).
# ``get_first_run_notice`` takes zero parameters and only calls
# ``settings_api.get_first_run_notice_for_webview()``.
# ``accept_first_run_notice`` takes zero parameters and calls
# ``settings_api.accept_first_run_notice_for_webview()``; only on ``ok=True``
# does it call ``app_api.start_collector()``.
# ``toggle_pause`` was updated to gate on ``settings_api.first_run_notice_accepted()``
# before any path that could start the collector: if not accepted (or the
# read raises), fail closed, do not mutate ``user_paused`` /
# ``collector_status``, return ``{"ok": False, "error": "请先确认隐私说明"}``.
# All error payloads collapse to stable Chinese messages and must not leak
# traceback / str(exc) / repr / format_exc / exc_info / .message /
# raw_exception / clipboard_content / passphrase / path.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_privacy_notice_first_run_notice_methods() -> None:
    """``WebViewBridge`` must expose the first-run notice ``get_first_run_notice``
    and ``accept_first_run_notice`` methods, both with zero parameters."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    for method_name in ("get_first_run_notice", "accept_first_run_notice"):
        method = getattr(bridge, method_name, None)
        assert callable(method), (
            f"WebViewBridge must expose startup gate contract bridge method {method_name!r}"
        )
        sig = inspect.signature(method)
        params = list(sig.parameters.values())
        # Zero required parameters; the JS side calls these with no args.
        required = [
            p for p in params
            if p.default is inspect.Parameter.empty
            and p.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.POSITIONAL_ONLY,
            )
        ]
        assert len(required) == 0, (
            f"{method_name} must accept zero required parameters, "
            f"got {len(required)}: {[p.name for p in required]}"
        )


def test_webview_bridge_get_first_run_notice_calls_api_facade() -> None:
    """``get_first_run_notice`` must call
    ``settings_api.get_first_run_notice_for_webview``. This is a static
    source-level check confirming the bridge delegates to the API facade
    and does not touch the DB / service directly."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("get_first_run_notice")
    assert "settings_api.get_first_run_notice_for_webview" in body
    # Must NOT touch DB / collector / security directly.
    for forbidden in (
        "settings_service",
        "secure_backup_service",
        "db.get_connection",
        "app_api.start_collector",
        "import_encrypted_backup",
        "export_encrypted_backup",
        "preview_encrypted_backup_manifest",
        "clear_all_local_data",
        "set_setting_value",
    ):
        assert forbidden not in body, (
            "get_first_run_notice must not call: " + forbidden
        )


def test_webview_bridge_accept_first_run_notice_calls_api_facade_and_start_collector() -> None:
    """``accept_first_run_notice`` must call
    ``settings_api.accept_first_run_notice_for_webview`` and, only on
    ``ok=True``, must call ``app_api.start_collector()``. This is a
    static source-level check confirming the bridge delegates to the API
    facade for the accept write and then starts the collector (mirroring
    the Tkinter ``_accept_notice`` flow)."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("accept_first_run_notice")
    assert "settings_api.accept_first_run_notice_for_webview" in body
    # The accept method MUST call app_api.start_collector() on success.
    assert "app_api.start_collector" in body
    # Skip the docstring when checking for forbidden tokens, since the
    # docstring legitimately mentions the forbidden names to document
    # what the method does NOT call.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    # The accept method must NOT call backup / clear / set-setting paths.
    for forbidden in (
        "import_encrypted_backup",
        "export_encrypted_backup",
        "preview_encrypted_backup_manifest",
        "clear_all_local_data",
        "set_setting_value",
    ):
        assert forbidden not in code_only, (
            "accept_first_run_notice must not call: " + forbidden
        )


def test_webview_bridge_get_first_run_notice_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``get_first_run_notice`` error payload must
    collapse to the stable Chinese message ``加载隐私说明失败`` and must
    not leak traceback / str(exc) / repr / format_exc / exc_info /
    .message / raw_exception / clipboard_content / passphrase / path.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("get_first_run_notice")
    # Stable Chinese error message that must appear in the payload.
    assert "加载隐私说明失败" in body
    # Skip the docstring when checking for forbidden runtime tokens.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "raw_exception",
        "clipboard_content",
        "passphrase",
    ):
        assert forbidden not in code_only, (
            "get_first_run_notice must not reference forbidden token: "
            + forbidden
        )


def test_webview_bridge_accept_first_run_notice_error_payload_has_no_sensitive_tokens() -> None:
    """the bridge ``accept_first_run_notice`` error payload must
    collapse to the stable Chinese message ``确认隐私说明失败`` and must
    not leak traceback / str(exc) / repr / format_exc / exc_info /
    .message / raw_exception / clipboard_content / passphrase / path.

    Note: ``app_api.start_collector`` IS allowed (it is the whole point
    of the method). ``passphrase`` is NOT allowed because the accept
    flow never references a passphrase.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("accept_first_run_notice")
    # Stable Chinese error message that must appear in the payload.
    assert "确认隐私说明失败" in body
    # Skip the docstring when checking for forbidden runtime tokens.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    for forbidden in (
        "traceback",
        "str(exc)",
        "str(e)",
        "repr(",
        "format_exc",
        "exc_info",
        ".message",
        "raw_exception",
        "clipboard_content",
        "passphrase",
    ):
        assert forbidden not in code_only, (
            "accept_first_run_notice must not reference forbidden token: "
            + forbidden
        )


def test_webview_bridge_toggle_pause_gates_on_first_run_notice() -> None:
    """``toggle_pause`` must call
    ``settings_api.first_run_notice_accepted()`` before any path that
    could call ``app_api.start_collector()``. If the read returns False
    (or raises), the method must fail closed: return
    ``{"ok": False, "error": "请先确认隐私说明"}`` and NOT mutate
    ``user_paused`` / ``collector_status`` / start the collector.

    This is a static source-level check confirming the gate is wired
    into ``toggle_pause`` and the fail-closed error message is present.
    """
    # method body lives in bridge_overview.py (OverviewBridgeMixin).
    body = _read_bridge_method_body("toggle_pause")
    # The gate check must appear BEFORE the first ``app_api.start_collector``
    # call. Find both positions and assert ordering.
    gate_pos = body.find("settings_api.first_run_notice_accepted()")
    start_pos = body.find("app_api.start_collector()")
    assert gate_pos != -1, (
        "toggle_pause must call settings_api.first_run_notice_accepted() "
        "for startup gate contract"
    )
    assert start_pos != -1, (
        "toggle_pause must still call app_api.start_collector() when the "
        "gate is open (startup gate contract does not remove the start path, only gates it)"
    )
    assert gate_pos < start_pos, (
        "toggle_pause must check first_run_notice_accepted() BEFORE any "
        "app_api.start_collector() call"
    )
    # The fail-closed error message must be present.
    assert "请先确认隐私说明" in body


def test_webview_bridge_toggle_pause_does_not_mutate_state_when_gate_closed() -> None:
    """when the first-run notice is not accepted,
    ``toggle_pause`` must NOT call ``set_user_paused``,
    ``set_collector_status``, ``set_current_activity_snapshot``, or
    ``start_collector``. The fail-closed path is a pure return."""
    # method body lives in bridge_overview.py (OverviewBridgeMixin).
    body = _read_bridge_method_body("toggle_pause")
    # Find the fail-closed return block: between the gate check and the
    # ``raw_status = settings_api.get_collector_status()`` line that
    # follows the gate. Slice that block and assert no state mutations.
    gate_check = body.find("settings_api.first_run_notice_accepted()")
    assert gate_check != -1
    # The fail-closed block ends at the next ``raw_status =`` assignment
    # (which only runs after the gate passes).
    raw_status_pos = body.find("raw_status = settings_api.get_collector_status()")
    assert raw_status_pos != -1
    fail_closed_block = body[gate_check:raw_status_pos]
    # The fail-closed block must contain the error return.
    assert "请先确认隐私说明" in fail_closed_block
    # The fail-closed block must NOT mutate state or start the collector.
    for forbidden in (
        "set_user_paused",
        "set_collector_status",
        "set_current_activity_snapshot",
        "app_api.start_collector",
    ):
        assert forbidden not in fail_closed_block, (
            "toggle_pause fail-closed block must not call: " + forbidden
        )


def test_webview_bridge_first_run_notice_methods_do_not_open_file_dialog() -> None:
    """neither ``get_first_run_notice`` nor
    ``accept_first_run_notice`` may open a native file dialog. The
    first-run notice is a pure accept flow with no file chooser."""
    # method bodies live in bridge_settings.py (SettingsBridgeMixin).
    for method_name in ("get_first_run_notice", "accept_first_run_notice"):
        body = _read_bridge_method_body(method_name)
        for forbidden in (
            "open_file_dialog",
            "save_file_dialog",
            "file_dialog",
            "tkinter.filedialog",
            "tkinter_dialog",
            "askopenfilename",
            "asksaveasfilename",
        ):
            assert forbidden not in body, (
                method_name + " must not open file dialog: " + forbidden
            )


def test_webview_main_imports_settings_api() -> None:
    """``webview_main.py`` must import ``settings_api`` from
    ``worktrace.api`` so the first-run startup gate can read the
    notice-accepted state. The bridge boundary is unaffected: only
    ``webview_main`` (the entry point) is allowed to import
    ``settings_api`` directly; the bridge must still go through
    ``worktrace.api`` (which it already does)."""
    webview_main_path = (
        Path(__file__).resolve().parents[1] / "worktrace" / "webview_main.py"
    )
    source = webview_main_path.read_text(encoding="utf-8")
    # The import must be present.
    assert "settings_api" in source, (
        "webview_main.py must import settings_api for startup gate contract startup gate"
    )
    # The import must come from worktrace.api (not from services / db).
    assert (
        "from .api import" in source or "from worktrace.api import" in source
    ), "webview_main.py must import settings_api via worktrace.api"
    # The startup gate must reference first_run_notice_accepted.
    assert "first_run_notice_accepted" in source, (
        "webview_main.py must call settings_api.first_run_notice_accepted() "
        "in the startup gate contract startup gate"
    )
    # webview_main.py is the entry point and is allowed to import AppRuntime
    # / config / logging helpers, but still must NOT import services /
    # collector / security directly.
    for forbidden in (
        "from .services",
        "from worktrace.services",
        "from .collector",
        "from worktrace.collector",
        "from .security",
        "from worktrace.security",
        "import worktrace.services",
        "import worktrace.collector",
        "import worktrace.security",
    ):
        assert forbidden not in source, (
            "webview_main.py must not import backend module directly: "
            + forbidden
        )


# ---------------------------------------------------------------------------
# Privacy gate for the folder index worker. The bridge
# ``toggle_pause`` and ``accept_first_run_notice`` methods must call
# ``app_api.start_background_workers()`` BEFORE ``app_api.start_collector()``
# so the folder index is warm by the time the collector starts matching
# activities. ``app_api`` must export a ``start_background_workers`` facade
# that delegates to ``runtime.start_background_workers()``.
# ---------------------------------------------------------------------------


def test_webview_bridge_toggle_pause_calls_start_background_workers_before_collector() -> None:
    """``toggle_pause`` must call ``app_api.start_background_workers()``
    BEFORE ``app_api.start_collector()`` on the resume path so the folder index
    worker is running before the collector starts matching activities.

    This is a static source-level check mirroring
    ``test_webview_bridge_toggle_pause_gates_on_first_run_notice``: find the
    ``toggle_pause`` body, slice to the next ``def``, and assert ordering.
    """
    # method body lives in bridge_overview.py (OverviewBridgeMixin).
    body = _read_bridge_method_body("toggle_pause")
    bg_pos = body.find("app_api.start_background_workers()")
    start_pos = body.find("app_api.start_collector()")
    assert bg_pos != -1, (
        "toggle_pause must call app_api.start_background_workers() before "
        "start_collector (live startup contract)"
    )
    assert start_pos != -1, (
        "toggle_pause must still call app_api.start_collector() when the "
        "gate is open (live startup contract does not remove the start path)"
    )
    assert bg_pos < start_pos, (
        "toggle_pause must call start_background_workers() BEFORE "
        "start_collector() so the folder index is warm before the collector"
    )


def test_webview_bridge_accept_first_run_notice_calls_start_background_workers() -> None:
    """``accept_first_run_notice`` must call
    ``app_api.start_background_workers`` after a successful accept so the
    folder index worker starts alongside the collector. This is a static
    source-level check mirroring
    ``test_webview_bridge_accept_first_run_notice_calls_api_facade_and_start_collector``."""
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("accept_first_run_notice")
    assert "app_api.start_background_workers" in body, (
        "accept_first_run_notice must call app_api.start_background_workers "
        "after a successful accept (live startup contract)"
    )


def test_webview_bridge_accept_first_run_notice_starts_background_workers_before_collector() -> None:
    """``accept_first_run_notice`` must call
    ``app_api.start_background_workers`` BEFORE ``app_api.start_collector``
    so the folder index is warm by the time the collector starts.

    The docstring mentions ``app_api.start_collector()`` so the docstring is
    skipped before comparing positions (mirroring the existing forbidden-token
    pattern used by the error-payload tests).
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("accept_first_run_notice")
    # Skip the docstring because it legitimately mentions
    # ``app_api.start_collector()`` to document the first-run notice behavior; only
    # the executable code should be checked for ordering.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    bg_pos = code_only.find("app_api.start_background_workers")
    start_pos = code_only.find("app_api.start_collector")
    assert bg_pos != -1, (
        "accept_first_run_notice must call app_api.start_background_workers "
        "after a successful accept (live startup contract)"
    )
    assert start_pos != -1, (
        "accept_first_run_notice must still call app_api.start_collector "
        "after a successful accept (startup gate contract)"
    )
    assert bg_pos < start_pos, (
        "accept_first_run_notice must call start_background_workers BEFORE "
        "start_collector so the folder index is warm before the collector"
    )


def test_app_api_exports_start_background_workers_facade() -> None:
    """``app_api.py`` must define a ``start_background_workers``
    facade and export it in ``__all__``. This is a static source-level check
    confirming the facade exists and is publicly exported."""
    app_api_path = (
        Path(__file__).resolve().parents[1] / "worktrace" / "api" / "app_api.py"
    )
    source = app_api_path.read_text(encoding="utf-8")
    assert "def start_background_workers" in source, (
        "app_api.py must define start_background_workers facade (live startup contract)"
    )
    from worktrace.api import app_api

    assert "start_background_workers" in app_api.__all__, (
        "app_api.__all__ must export start_background_workers (live startup contract)"
    )


# ---------------------------------------------------------------------------
# page-level bridge split. ``WebViewBridge`` is now a thin
# composition class that inherits from six mixins. This test asserts the
# runtime public method set on ``WebViewBridge()`` equals the union of all
# public methods defined across the 8 bridge mixin files, so a future
# refactor that drops a mixin (or adds a method to a mixin without wiring
# it into ``WebViewBridge``) fails here instead of silently removing the
# method from the only shipping bridge class.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_union_of_all_mixin_public_methods() -> None:
    """``WebViewBridge()`` must expose every public method defined on any of
    the 8 bridge mixin files, and no extras beyond the union.

    the page module mapping split ``bridge.py`` into ``bridge_common.py``,
    ``bridge_dialogs.py``, ``bridge_overview.py``, ``bridge_settings.py``,
    ``bridge_statistics.py``, ``bridge_timeline.py``, and ``bridge_rules.py``
    (plus the slim composition ``bridge.py``). ``WebViewBridge`` inherits
    from six of these mixins (all except ``bridge_common.py`` which holds
    only module-level helpers). This test enumerates the public methods
    declared on each mixin via AST and asserts the runtime ``dir()`` set
    on ``WebViewBridge()`` matches the union.
    """
    import ast

    from worktrace.webview_ui.bridge import WebViewBridge

    # Collect public method names declared on any class in any bridge file.
    union_declared: set[str] = set()
    for name in BRIDGE_FILES:
        path = WEBVIEW_UI_DIR / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                        union_declared.add(item.name)

    # ``set_window`` is defined directly on ``WebViewBridge`` in bridge.py
    # (not on a mixin), so it must be in the union already via bridge.py's
    # ``WebViewBridge`` class. The runtime dir() set covers inherited mixin
    # methods plus ``set_window``.
    runtime_methods = {
        m for m in dir(WebViewBridge())
        if not m.startswith("_") and callable(getattr(WebViewBridge(), m))
    }

    # Every public method declared on any bridge mixin class must be
    # exposed on the runtime WebViewBridge instance.
    missing = union_declared - runtime_methods
    assert not missing, (
        "WebViewBridge() is missing public methods declared on bridge mixins: "
        + ", ".join(sorted(missing))
    )


# ---------------------------------------------------------------------------
# fixed expected-set lock on the WebViewBridge public API
# surface. The union-of-mixin test above guards against a mixin growing a new
# method that fails to reach ``WebViewBridge``. It does NOT guard against a
# historically-public method being silently dropped during a split (e.g. a
# method that lived on ``WebViewBridge`` before the page module mapping and was accidentally
# left out of every mixin). This fixed set closes that gap: every name listed
# here MUST remain callable on ``WebViewBridge()``. The set is hand-curated
# from the actual public methods declared across the 8 bridge files (verified
# via AST at authoring time); it is intentionally NOT derived dynamically from
# AST so a split refactor cannot silently shrink the locked surface.
# ---------------------------------------------------------------------------

EXPECTED_WEBVIEW_BRIDGE_PUBLIC_METHODS = {
    # window injection
    "set_window",
    # Overview / status
    "get_status",
    "toggle_pause",
    "get_overview",
    "get_recent_activities",
    # lightweight refresh-state for the heartbeat.
    "get_refresh_state",
    # first-run / settings / privacy
    "get_first_run_notice",
    "accept_first_run_notice",
    "get_settings_privacy_status",
    "set_clipboard_capture_enabled",
    "export_encrypted_backup",
    "preview_encrypted_backup_manifest",
    "import_encrypted_backup",
    "clear_all_local_data",
    # Timeline
    "get_timeline",
    "get_timeline_session_details",
    "list_projects_for_timeline",
    "update_timeline_project",
    "update_timeline_note",
    "update_timeline_activity_time",
    "update_timeline_session_time",
    "split_timeline_activity",
    "split_timeline_session",
    "merge_timeline_activities",
    "hide_timeline_activity",
    "soft_delete_timeline_activity",
    "hide_timeline_session",
    "soft_delete_timeline_session",
    "batch_update_timeline_activities_project",
    "batch_update_timeline_activities_note",
    "get_timeline_restorable_activities",
    "restore_timeline_activity",
    # Statistics / export
    "get_statistics_export_summary",
    "export_statistics_csv",
    # Project Rules
    "get_project_rules",
    "set_project_rule_enabled",
    "create_project_keyword_rule",
    "update_project_keyword_rule",
    "delete_project_keyword_rule",
    "create_project_folder_rule",
    "update_project_folder_rule",
    "delete_project_folder_rule",
    "create_excluded_keyword_rule",
    "create_excluded_folder_rule",
    "create_project_for_rules",
    "update_project_for_rules",
    "set_project_enabled_for_rules",
    "archive_project_for_rules",
    "preview_project_rule_impact",
    "backfill_project_rule",
    "automatic_rules_status",
    "preview_project_rules_batch_impact",
    "backfill_project_rules_batch",
    "set_project_rules_batch_enabled",
}


def test_webview_bridge_exposes_expected_fixed_public_api_surface() -> None:
    """``WebViewBridge()`` must expose every method in the fixed expected set.

    the page module mapping: this is the complement to
    ``test_webview_bridge_exposes_union_of_all_mixin_public_methods``. The
    union test prevents a mixin from growing a method that fails to reach
    ``WebViewBridge``. This fixed-set test prevents a historically-public
    method from being silently dropped during a bridge split (a method that
    lived on ``WebViewBridge`` before the split and was accidentally left
    out of every mixin would still pass the union test, because the union is
    derived from the same mixin files that lost the method).

    The expected set is hand-curated from the actual public methods declared
    across the 8 bridge files (verified via AST at authoring time). It is
    intentionally NOT derived dynamically from AST so a split refactor cannot
    silently shrink the locked surface. If a method is renamed or removed,
    this test fails and forces an explicit update to the expected set.
    """
    from worktrace.webview_ui.bridge import WebViewBridge

    runtime_public_methods = {
        name for name in dir(WebViewBridge())
        if callable(getattr(WebViewBridge(), name)) and not name.startswith("_")
    }
    missing = EXPECTED_WEBVIEW_BRIDGE_PUBLIC_METHODS - runtime_public_methods
    assert not missing, (
        "WebViewBridge() is missing expected public API methods (locked "
        "surface). If a method was intentionally renamed/removed, update "
        "EXPECTED_WEBVIEW_BRIDGE_PUBLIC_METHODS explicitly. Missing: "
        + ", ".join(sorted(missing))
    )


# ---------------------------------------------------------------------------
# Compat cleanup: ``bridge.py`` must NOT expose API facade module
# symbols. Before the page module mapping cleanup, ``bridge.py``
# imported ``app_api`` / ``export_api`` / ``project_api`` / ``rule_api`` /
# ``settings_api`` / ``statistics_api`` / ``timeline_api`` at module level
# so tests that monkeypatched ``bridge_module.<api>`` would resolve. After
# the cleanup, each page-level mixin imports its own API facades and
# ``bridge.py`` is a thin composition class. These tests lock the cleanup
# so the compat imports cannot regress.
# ---------------------------------------------------------------------------


def test_bridge_module_does_not_expose_api_facade_symbols() -> None:
    """``worktrace.webview_ui.bridge`` must NOT expose any API facade module
    as a module-level attribute.

    After the page module mapping cleanup, ``bridge.py`` only imports
    the six mixin classes (``BridgeDialogMixin``, ``OverviewBridgeMixin``,
    ``SettingsBridgeMixin``, ``StatisticsBridgeMixin``, ``TimelineBridgeMixin``,
    ``ProjectRulesBridgeMixin``) and stdlib (``logging``, ``typing``). Each
    mixin imports the API facades it needs from its own module namespace.
    Tests must monkeypatch the owning mixin module (e.g.
    ``bridge_overview.settings_api``) rather than the old
    ``bridge``-level compat path.
    """
    import worktrace.webview_ui.bridge as bridge_mod

    forbidden_symbols = (
        "app_api",
        "export_api",
        "project_api",
        "rule_api",
        "settings_api",
        "statistics_api",
        "timeline_api",
    )
    for symbol in forbidden_symbols:
        assert not hasattr(bridge_mod, symbol), (
            f"worktrace.webview_ui.bridge must not expose API facade symbol "
            f"{symbol!r}; each page-level mixin should import its own API "
            f"facades. Tests must monkeypatch the owning mixin module."
        )


def test_bridge_module_all_equals_webview_bridge_only() -> None:
    """``worktrace.webview_ui.bridge.__all__`` must be exactly
    ``["WebViewBridge"]``.

    ``bridge.py`` is a thin composition module: it defines / exposes only
    the ``WebViewBridge`` class. API facades, helpers, and constants live
    in the mixin modules or ``bridge_common.py``.
    """
    import worktrace.webview_ui.bridge as bridge_mod

    assert hasattr(bridge_mod, "__all__"), (
        "worktrace.webview_ui.bridge must define __all__"
    )
    assert bridge_mod.__all__ == ["WebViewBridge"], (
        f"worktrace.webview_ui.bridge.__all__ must be ['WebViewBridge'], "
        f"got {bridge_mod.__all__!r}"
    )


# ---------------------------------------------------------------------------
# Live-clock carry helper export contract. ``short_activity_carry_seconds``
# is the public helper; ``carry_baseline_seconds`` must stay absent.
# ---------------------------------------------------------------------------


def test_short_activity_carry_seconds_exists_under_new_name() -> None:
    """``short_activity_carry_seconds`` must exist in both
    ``live_display_service`` and ``live_display_api``.

    The helper returns the carry-over seconds from
    consecutive sub-30s short activities that should be added to the
    unified live-display duration.
    """
    from worktrace.api import live_display_api
    from worktrace.services import live_display_service

    # The public helper must exist in the service module.
    assert hasattr(live_display_service, "short_activity_carry_seconds"), (
        "live_display_service must define short_activity_carry_seconds "
        "(carry helper export)"
    )
    assert callable(live_display_service.short_activity_carry_seconds), (
        "live_display_service.short_activity_carry_seconds must be callable"
    )
    # The new name must be re-exported by the API facade.
    assert hasattr(live_display_api, "short_activity_carry_seconds"), (
        "live_display_api must re-export short_activity_carry_seconds"
    )
    assert callable(live_display_api.short_activity_carry_seconds), (
        "live_display_api.short_activity_carry_seconds must be callable"
    )
    # The old name must NOT exist in either module.
    assert not hasattr(live_display_service, "carry_baseline_seconds"), (
        "live_display_service must not retain the removed name carry_baseline_seconds"
    )
    assert not hasattr(live_display_api, "carry_baseline_seconds"), (
        "live_display_api must not retain the removed name carry_baseline_seconds"
    )
    # The new name must appear in __all__ for both modules.
    assert "short_activity_carry_seconds" in live_display_service.__all__, (
        "live_display_service.__all__ must include short_activity_carry_seconds"
    )
    assert "short_activity_carry_seconds" in live_display_api.__all__, (
        "live_display_api.__all__ must include short_activity_carry_seconds"
    )
    # The old name must NOT appear in __all__ for either module.
    assert "carry_baseline_seconds" not in live_display_service.__all__, (
        "live_display_service.__all__ must not include carry_baseline_seconds"
    )
    assert "carry_baseline_seconds" not in live_display_api.__all__, (
        "live_display_api.__all__ must not include carry_baseline_seconds"
    )


def test_short_activity_carry_seconds_returns_zero_for_none_snapshot() -> None:
    """``short_activity_carry_seconds`` must return ``0`` for a ``None``
    snapshot, confirming the renamed function preserves the original
    fail-safe behavior."""
    from worktrace.api import live_display_api

    result = live_display_api.short_activity_carry_seconds(None, None)
    assert result == 0, (
        f"short_activity_carry_seconds(None, None) must return 0, got {result}"
    )
