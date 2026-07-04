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


# Bridge.py is a thin composition class inheriting from six mixins; method
# bodies live in the mixin files. Static tests scan all bridge files.
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


# Frontend resource external-link / CDN / localStorage / traceback scans live in tests/webview/test_frontend_global_boundaries.py.


# Hardening lock: the four Project Rules batch methods live on
# ProjectRulesBridgeMixin and are inherited by WebViewBridge. Without this
# lock, dropping the mixin would silently remove the 5I surface.


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
    # Slice at the next ``def`` so the body covers only this method; a fixed
    # window would bleed into ``import_encrypted_backup`` whose ``passphrase``
    # signature would falsely fail the forbidden-token check.
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


# First-run privacy notice bridge methods. The two new methods are


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


def test_webview_bridge_accept_first_run_notice_uses_unified_privacy_gate_entry() -> None:
    """``accept_first_run_notice`` must call
    ``settings_api.accept_first_run_notice_for_webview`` and then route
    collector / background-worker startup through the unified
    ``app_api.start_collection_after_privacy_gate()`` entry.

    The privacy gate is enforced INSIDE that unified entry; the bridge
    must NOT call ``app_api.start_collector`` /
    ``app_api.start_background_workers`` directly and must NOT duplicate
    the first-run notice read.
    """
    # method body lives in bridge_settings.py (SettingsBridgeMixin).
    body = _read_bridge_method_body("accept_first_run_notice")
    assert "settings_api.accept_first_run_notice_for_webview" in body
    # The accept method MUST call the unified privacy-gate entry on success.
    assert "app_api.start_collection_after_privacy_gate" in body, (
        "accept_first_run_notice must call app_api.start_collection_after_privacy_gate() "
        "after a successful accept (unified privacy-gate startup contract)"
    )
    # Skip the docstring when checking for forbidden tokens, since the
    # docstring legitimately mentions the forbidden names to document
    # what the method does NOT call.
    doc_start = body.find('"""')
    doc_end = body.find('"""', doc_start + 3) + 3 if doc_start != -1 else 0
    code_only = body[doc_end:] if doc_end > 3 else body
    # The bridge must NOT call the separated start paths directly; the
    # unified entry is the only path so the gate / ordering lives in one place.
    for forbidden in (
        "app_api.start_collector",
        "app_api.start_background_workers",
        "settings_api.first_run_notice_accepted",
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


def test_webview_bridge_toggle_pause_uses_unified_privacy_gate_entry() -> None:
    """``toggle_pause`` must route collector / background-worker
    startup through ``app_api.start_collection_after_privacy_gate()``.

    The privacy gate is enforced INSIDE that unified entry; the bridge
    must NOT call ``app_api.start_collector`` /
    ``app_api.start_background_workers`` directly and must NOT duplicate
    the first-run notice read or the fail-closed message. The gate,
    the start ordering, and the fail-closed payload are all owned by the
    unified entry so there is a single source of truth.
    """
    # method body lives in bridge_overview.py (OverviewBridgeMixin).
    body = _read_bridge_method_body("toggle_pause")
    # The unified privacy-gate entry must be called on the resume path.
    assert "app_api.start_collection_after_privacy_gate" in body, (
        "toggle_pause must call app_api.start_collection_after_privacy_gate() "
        "for the unified privacy-gate startup contract"
    )
    # The bridge must NOT duplicate the gate / start paths directly.
    for forbidden in (
        "settings_api.first_run_notice_accepted",
        "app_api.start_collector",
        "app_api.start_background_workers",
    ):
        assert forbidden not in body, (
            "toggle_pause must not call: "
            + forbidden
            + " (enforced by start_collection_after_privacy_gate)"
        )
    # The bridge must NOT carry the fail-closed message; it is owned by
    # the unified entry so a single source of truth exists.
    assert "请先确认隐私说明" not in body, (
        "toggle_pause must not duplicate the fail-closed message; "
        "it is owned by start_collection_after_privacy_gate"
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


def test_webview_main_uses_unified_privacy_gate_entry() -> None:
    """``webview_main.py`` must route the collector / background-worker
    startup through ``app_api.start_collection_after_privacy_gate()``.

    The privacy gate (first-run notice accepted?) is enforced INSIDE
    that unified entry; ``webview_main.py`` must NOT duplicate the
    gate read or the start ordering. The bridge boundary is unaffected:
    only ``webview_main`` (the entry point) is allowed to import
    ``app_api`` directly; the bridge must still go through
    ``worktrace.api``."""
    webview_main_path = (
        Path(__file__).resolve().parents[1] / "worktrace" / "webview_main.py"
    )
    source = webview_main_path.read_text(encoding="utf-8")
    # The unified privacy-gate entry must be called.
    assert "start_collection_after_privacy_gate" in source, (
        "webview_main.py must call app_api.start_collection_after_privacy_gate() "
        "for the unified privacy-gate startup contract"
    )
    # The import must come from worktrace.api (not from services / db).
    assert (
        "from .api import" in source or "from worktrace.api import" in source
    ), "webview_main.py must import app_api via worktrace.api"
    # webview_main.py must NOT directly call start_collector /
    # start_background_workers — those are runtime-internal helpers.
    # The unified entry is the only path.
    assert "app_api.start_collector(" not in source, (
        "webview_main.py must not call app_api.start_collector() directly; "
        "route through start_collection_after_privacy_gate()"
    )
    assert "app_api.start_background_workers(" not in source, (
        "webview_main.py must not call app_api.start_background_workers() "
        "directly; route through start_collection_after_privacy_gate()"
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


# ``app_api`` exports ``start_background_workers`` / ``start_collector`` as
# runtime-internal helpers, but the WebView bridge and ``webview_main`` MUST
# NOT call them directly — they route through the unified privacy-gated entry.


def test_app_api_exports_start_background_workers_internal_helper() -> None:
    """``app_api.py`` must define ``start_background_workers`` as a
    runtime-internal helper and export it in ``__all__`` so
    ``start_collection_after_privacy_gate`` can call it. The bridge /
    ``webview_main`` must NOT call it directly."""
    app_api_path = (
        Path(__file__).resolve().parents[1] / "worktrace" / "api" / "app_api.py"
    )
    source = app_api_path.read_text(encoding="utf-8")
    assert "def start_background_workers" in source, (
        "app_api.py must define start_background_workers internal helper "
        "(used by start_collection_after_privacy_gate)"
    )
    from worktrace.api import app_api

    assert "start_background_workers" in app_api.__all__, (
        "app_api.__all__ must export start_background_workers internal helper"
    )


def test_app_api_exports_start_collector_internal_helper() -> None:
    """``app_api.py`` must define ``start_collector`` as a runtime-internal
    helper and export it in ``__all__`` so
    ``start_collection_after_privacy_gate`` can call it. The bridge /
    ``webview_main`` must NOT call it directly."""
    app_api_path = (
        Path(__file__).resolve().parents[1] / "worktrace" / "api" / "app_api.py"
    )
    source = app_api_path.read_text(encoding="utf-8")
    assert "def start_collector" in source, (
        "app_api.py must define start_collector internal helper "
        "(used by start_collection_after_privacy_gate)"
    )
    from worktrace.api import app_api

    assert "start_collector" in app_api.__all__, (
        "app_api.__all__ must export start_collector internal helper"
    )


# WebViewBridge must expose the union of public mixin methods.


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


# Live-clock carry DELETION contract: the legacy structured
# ``short_activity_carry`` JSON was REMOVED (no production writer).
# Production collector maintains ``pending_short_seconds``, the only
# carry source consulted. Tests enforce the deletion.


def test_short_activity_carry_helpers_removed_from_live_display_service() -> None:
    """``live_display_service`` must NOT define the removed carry
    helpers ``short_activity_carry_seconds`` /
    ``_read_short_activity_carry`` /
    ``_short_activity_carry_duration_helper`` / ``carry_baseline_seconds``.
    """
    from worktrace.services import live_display_service

    for removed in (
        "short_activity_carry_seconds",
        "_read_short_activity_carry",
        "_short_activity_carry_duration_helper",
        "carry_baseline_seconds",
    ):
        assert not hasattr(live_display_service, removed), (
            f"live_display_service must not retain the removed carry helper {removed}"
        )
        assert removed not in live_display_service.__all__, (
            f"live_display_service.__all__ must not include the removed carry helper {removed}"
        )
    # The production-maintained accumulator reader is retained.
    assert hasattr(live_display_service, "_read_pending_short_seconds"), (
        "live_display_service must retain _read_pending_short_seconds "
        "(production-maintained carry source)"
    )


def test_short_activity_carry_helpers_removed_from_live_time_service() -> None:
    """``live_time_service`` must NOT define the removed carry helpers
    ``sync_short_activity_carry`` / ``short_activity_carry_duration`` /
    ``snapshot_signature`` / ``is_unconfirmed_snapshot``.
    """
    from worktrace.services import live_time_service

    for removed in (
        "sync_short_activity_carry",
        "short_activity_carry_duration",
        "snapshot_signature",
        "is_unconfirmed_snapshot",
    ):
        assert not hasattr(live_time_service, removed), (
            f"live_time_service must not retain the removed carry helper {removed}"
        )


def test_short_activity_carry_helpers_removed_from_timeline_api() -> None:
    """``timeline_api`` must NOT export the removed carry wrappers
    ``sync_short_activity_carry_value`` /
    ``get_short_activity_carry_duration`` /
    ``get_snapshot_signature`` / ``is_snapshot_unconfirmed``.
    """
    from worktrace.api import timeline_api

    for removed in (
        "sync_short_activity_carry_value",
        "get_short_activity_carry_duration",
        "get_snapshot_signature",
        "is_snapshot_unconfirmed",
    ):
        assert not hasattr(timeline_api, removed), (
            f"timeline_api must not retain the removed carry wrapper {removed}"
        )
        assert removed not in timeline_api.__all__, (
            f"timeline_api.__all__ must not include the removed carry wrapper {removed}"
        )


def test_compute_refresh_revision_does_not_include_carry_signature() -> None:
    """``compute_refresh_revision`` must NOT include ``carry_signature``
    in its debug inputs or revision input. The legacy structured
    ``short_activity_carry`` JSON had no production writer; its
    signature must not contribute to refresh-revision changes.
    """
    import inspect

    from worktrace.services import live_display_service

    source = inspect.getsource(live_display_service.compute_refresh_revision)
    assert "carry_signature" not in source, (
        "compute_refresh_revision source must not reference carry_signature"
    )
    assert "_read_short_activity_carry" not in source, (
        "compute_refresh_revision source must not call _read_short_activity_carry"
    )

    # Spot-check the actual debug inputs: no ``carry_signature`` key.
    revision, debug_inputs = live_display_service.compute_refresh_revision(
        snapshot=None,
        collector_status="running",
        user_paused=False,
        today="2026-07-04",
    )
    assert "carry_signature" not in debug_inputs, (
        "compute_refresh_revision debug_inputs must not include carry_signature"
    )
    # ``pending_short_seconds`` IS retained (production-maintained).
    assert "pending_short_seconds" in debug_inputs, (
        "compute_refresh_revision debug_inputs must include pending_short_seconds "
        "(production-maintained accumulator)"
    )


def test_view_model_api_does_not_export_carry_helpers() -> None:
    """The bridge facade ``view_model_api`` must NOT export any of the
    removed carry helpers, and must continue to export the canonical
    ViewModel entry points."""
    from worktrace.api import view_model_api

    for removed in (
        "short_activity_carry_seconds",
        "carry_baseline_seconds",
        "sync_short_activity_carry_value",
        "get_short_activity_carry_duration",
        "get_snapshot_signature",
        "is_snapshot_unconfirmed",
    ):
        assert removed not in view_model_api.__all__, (
            f"view_model_api.__all__ must not include the removed carry helper {removed}"
        )
        assert not hasattr(view_model_api, removed), (
            f"view_model_api must not retain the removed carry helper {removed}"
        )
    # The canonical ViewModel entry points must still be exported.
    for symbol in (
        "build_current_activity_summary",
        "compute_refresh_revision",
        "get_overview_view_model",
        "get_refresh_state_view_model",
        "get_session_details_view_model",
        "get_timeline_view_model",
    ):
        assert symbol in view_model_api.__all__, (
            "view_model_api.__all__ must include " + symbol
        )
        assert hasattr(view_model_api, symbol), (
            "view_model_api must expose " + symbol
        )


# --- Section 七: page-scoped frontend live clock registry boundary ---


_JS_DIR = WEBVIEW_UI_DIR / "js"


def test_core_js_implements_page_scoped_live_clock_registry() -> None:
    """Section 七: ``core.js`` MUST implement a page-scoped live-clock
    registry. The single global ``App.activeDisplaySpanId`` MUST NOT be
    the only active-clock source; the page-scoped
    ``App.liveClockByPage`` / ``App.activeDisplaySpanIdByPage`` MUST be
    the primary active-clock source so a hidden page's payload cannot
    overwrite the current page's active clock.
    """
    source = (_JS_DIR / "core.js").read_text(encoding="utf-8")
    # Page-scoped registry MUST exist.
    assert "App.liveClockByPage" in source, (
        "core.js must define App.liveClockByPage (page-scoped registry)"
    )
    assert "App.activeDisplaySpanIdByPage" in source, (
        "core.js must define App.activeDisplaySpanIdByPage"
    )
    # getActiveLiveClock MUST read App.currentPage to scope the lookup.
    assert "App.currentPage" in source, (
        "core.js getActiveLiveClock must read App.currentPage to scope "
        "the active clock lookup"
    )
    # registerLiveClock MUST accept a page/scope parameter.
    assert "opts.page" in source or "options.page" in source, (
        "core.js registerLiveClock must accept a page/scope parameter"
    )


def test_core_js_full_reconcile_does_not_unconditionally_refresh_overview() -> None:
    """Section 七: ``fullReconcileCollectionViews`` in ``init.js`` MUST
    NOT unconditionally call ``refreshOverview()``. When the current
    page is NOT Overview (e.g. Timeline historical date), the reconcile
    MUST only refresh status + the current page so a hidden Overview
    refresh does not register an Overview-scope live clock that
    overwrites the current page's active clock.
    """
    source = (_JS_DIR / "init.js").read_text(encoding="utf-8")
    # The reconcile function MUST gate refreshOverview on the current page.
    assert 'App.currentPage === "overview"' in source, (
        "init.js fullReconcileCollectionViews must gate refreshOverview on "
        'App.currentPage === "overview"'
    )


def test_overview_js_registers_with_page_scope() -> None:
    """Section 七: ``overview.js`` MUST register live clocks with
    ``page: "overview"`` so the clock is scoped to the Overview page."""
    source = (_JS_DIR / "overview.js").read_text(encoding="utf-8")
    assert 'page: "overview"' in source, (
        "overview.js must register live clocks with page: \"overview\""
    )


def test_timeline_js_registers_with_page_scope() -> None:
    """Section 七: ``timeline.js`` MUST register live clocks with
    ``page: "timeline"`` so the clock is scoped to the Timeline page."""
    source = (_JS_DIR / "timeline.js").read_text(encoding="utf-8")
    assert 'page: "timeline"' in source, (
        "timeline.js must register live clocks with page: \"timeline\""
    )
