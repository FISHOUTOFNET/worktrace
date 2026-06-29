"""Boundary tests enforcing the UI <-> backend API contract.

The UI layer must talk to the backend exclusively through ``worktrace.api``.
Direct imports of ``worktrace.services``, ``worktrace.db``,
``worktrace.collector``, or ``worktrace.security`` from any module under
``worktrace/ui`` are forbidden.

The same boundary applies to the WebView UI package
``worktrace/webview_ui`` (the default and only shipping UI as of Phase 1).
In addition, the WebView bridge (``bridge.py``) must not import
``worktrace.runtime`` or ``worktrace.config`` either: it may only reach the
backend through ``worktrace.api``. The WebView entry point
(``worktrace/webview_main.py``) is allowed to import ``AppRuntime``,
``config``, and ``db`` initialization helpers, mirroring ``worktrace/main.py``,
but still must not import ``services``, ``collector``, or ``security``.

The legacy ``worktrace/ui`` (Tkinter / CustomTkinter) package is retained in
the source tree as legacy code pending removal, not as a supported runtime
path. Its boundary rules are still enforced so it cannot become a backdoor
into the backend while it remains in the tree.

Allowed UI / WebView dependencies:
- ``worktrace.api`` (the facade layer)
- ``worktrace.formatters`` / ``worktrace.constants`` (pure helpers)
- other modules inside ``worktrace.ui`` / ``worktrace.webview_ui`` itself
- third-party and stdlib modules
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1] / "worktrace" / "ui"

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


def _collect_ui_files() -> list[Path]:
    return sorted(UI_DIR.glob("*.py"))


@pytest.fixture(scope="module")
def ui_files() -> list[Path]:
    files = _collect_ui_files()
    assert files, "expected to find UI source files under worktrace/ui"
    return files


def test_ui_directory_exists(ui_files: list[Path]) -> None:
    assert ui_files, "worktrace/ui should contain python source files"


@pytest.mark.parametrize("ui_file", _collect_ui_files(), ids=lambda p: p.name)
def test_ui_file_has_no_forbidden_backend_imports(ui_file: Path) -> None:
    source = ui_file.read_text(encoding="utf-8")
    violations: list[str] = []
    for pattern, label in zip(FORBIDDEN_PATTERNS, FORBIDDEN_LABELS):
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            violations.append(f"{ui_file.name}:{line_no}: {label}")
    assert not violations, (
        "UI layer must not import backend modules directly. Found forbidden imports:\n"
        + "\n".join(violations)
        + "\nUse worktrace.api.* facades instead."
    )


def test_ui_files_use_api_layer_for_backend_access(ui_files: list[Path]) -> None:
    """At least one UI file should reference the api package, otherwise the
    boundary is vacuous. This guards against the api package being silently
    removed while UI files still compile."""
    api_references = 0
    for path in ui_files:
        source = path.read_text(encoding="utf-8")
        if "worktrace.api" in source or "from ..api" in source or "from .api" in source:
            api_references += 1
    # app.py plus at least one view should talk to the api layer.
    assert api_references >= 2, (
        f"expected multiple UI files to import worktrace.api, found {api_references}"
    )


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


def test_webview_ui_directory_exists() -> None:
    assert WEBVIEW_UI_DIR.is_dir(), (
        "worktrace/webview_ui directory must exist (Phase 1 default UI package)"
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

    As of the Phase M3 split, the Project Rules bridge methods live in
    ``bridge_rules.py`` (mixed into ``WebViewBridge`` via
    ``ProjectRulesBridgeMixin``). Both ``bridge.py`` and ``bridge_rules.py``
    must obey the same strict boundary: no ``runtime``, ``config``,
    ``services``, ``db``, ``collector``, or ``security`` imports.
    """
    bridge_modules = ["bridge.py", "bridge_rules.py"]
    # bridge.py is the primary bridge module and must always exist.
    assert (WEBVIEW_UI_DIR / "bridge.py").is_file(), "bridge.py must exist (Phase 1)"
    violations: list[str] = []
    for name in bridge_modules:
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
        pytest.skip("static/ resource directory not created yet (Phase 1)")
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
# Phase 5I.1 hardening: lock the four Project Rules batch / automatic-rules
# bridge methods on the composed ``WebViewBridge`` class. The methods are
# defined on ``ProjectRulesBridgeMixin`` (in ``bridge_rules.py``) and inherited
# by ``WebViewBridge``. Without this lock, a future refactor that drops the
# mixin from ``WebViewBridge``'s bases would silently remove the 5I surface
# from the only shipping bridge class without any test failing.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_phase_5i_batch_and_automatic_methods() -> None:
    """``WebViewBridge`` must expose the four Phase 5I methods.

    The methods are defined on ``ProjectRulesBridgeMixin`` and inherited by
    ``WebViewBridge``. Phase 5I.1 hardens this composition so a refactor
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
            f"WebViewBridge must expose Phase 5I bridge method {name!r} "
            "(inherited from ProjectRulesBridgeMixin)"
        )


# ---------------------------------------------------------------------------
# Phase 6B: Settings / Privacy clipboard capture toggle bridge method.
# The new ``set_clipboard_capture_enabled`` method is defined directly on
# ``WebViewBridge`` (no mixin), so a rename or removal would silently drop
# the Phase 6B write surface from the only shipping bridge. This lock also
# confirms the error payload carries no sensitive tokens (no path / no
# clipboard content / no passphrase / no SQL / no traceback / no raw
# exception) so the bridge boundary stays leak-free.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_phase_6b_clipboard_toggle_method() -> None:
    """``WebViewBridge`` must expose the Phase 6B ``set_clipboard_capture_enabled``
    method with a single required ``enabled`` parameter (no optional args,
    no loose ``*args``)."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "set_clipboard_capture_enabled", None)
    assert callable(method), (
        "WebViewBridge must expose Phase 6B bridge method "
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
    """Phase 6B: the bridge ``set_clipboard_capture_enabled`` error payload
    must collapse to a stable Chinese message and must not leak path /
    clipboard content / passphrase / SQL / traceback / raw exception text.

    This is a static source-level check so it runs without a live database
    or collector: it reads ``bridge.py`` and confirms the error string is
    the only payload on failure and no ``traceback`` / ``str(exc)`` /
    ``repr`` expression appears in the executable code (the docstring is
    skipped because it legitimately mentions these words to document what
    the method does NOT leak).
    """
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def set_clipboard_capture_enabled")
    assert pos != -1, (
        "bridge.py must define set_clipboard_capture_enabled for Phase 6B"
    )
    # Extract the method body for inspection. Bound the slice at the next
    # method definition so Phase 6C methods that follow (which legitimately
    # use ``passphrase`` as a parameter name) don't trigger false positives.
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 2500]
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
# Phase 6C: Settings / Privacy encrypted backup export + manifest preview
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


def test_webview_bridge_exposes_phase_6c_export_method() -> None:
    """``WebViewBridge`` must expose the Phase 6C ``export_encrypted_backup``
    method with exactly two required parameters (``passphrase`` and
    ``confirm_passphrase``); no optional args, no ``*args``, no ``**kwargs``."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "export_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose Phase 6C bridge method "
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


def test_webview_bridge_exposes_phase_6c_manifest_preview_method() -> None:
    """``WebViewBridge`` must expose the Phase 6C
    ``preview_encrypted_backup_manifest`` method with zero parameters."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "preview_encrypted_backup_manifest", None)
    assert callable(method), (
        "WebViewBridge must expose Phase 6C bridge method "
        "'preview_encrypted_backup_manifest'"
    )
    sig = inspect.signature(method)
    params = list(sig.parameters.values())
    assert len(params) == 0, (
        "preview_encrypted_backup_manifest must accept zero parameters, "
        f"got {len(params)}"
    )


def test_webview_bridge_export_error_payload_has_no_sensitive_tokens() -> None:
    """Phase 6C: the bridge ``export_encrypted_backup`` error payload must
    collapse to stable Chinese messages and must not leak traceback /
    str(exc) / repr / format_exc / exc_info / .message / raw_exception /
    clipboard_content.

    ``passphrase`` IS allowed as a parameter name, local variable, and
    pass-through argument to ``settings_api.export_encrypted_backup_for_webview``;
    it is NOT in the forbidden list here. The runtime tests in
    ``test_settings_privacy_status`` verify the returned payload never
    carries the passphrase value.
    """
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def export_encrypted_backup")
    assert pos != -1, (
        "bridge.py must define export_encrypted_backup for Phase 6C"
    )
    body = bridge_source[pos:pos + 3000]
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
    """Phase 6C: the bridge ``preview_encrypted_backup_manifest`` error
    payload must collapse to stable Chinese messages and must not leak
    traceback / str(exc) / repr / format_exc / exc_info / .message /
    raw_exception / clipboard_content / passphrase.

    Unlike ``export_encrypted_backup``, ``passphrase`` IS forbidden here
    because the manifest preview method never accepts or references a
    passphrase.
    """
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def preview_encrypted_backup_manifest")
    assert pos != -1, (
        "bridge.py must define preview_encrypted_backup_manifest for Phase 6C"
    )
    # Slice to the next ``def`` at the same indent so the body covers only
    # this method (a fixed 3000-char window would bleed into the next
    # method ``import_encrypted_backup`` whose signature references
    # ``passphrase``, falsely failing the forbidden-token check below).
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 4000]
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
    """Phase 6C: ``export_encrypted_backup`` must pass ``passphrase`` and
    ``confirm_passphrase`` through to
    ``settings_api.export_encrypted_backup_for_webview``. This is a static
    source-level check confirming the passphrase is used as a pass-through
    argument (not logged, not returned, not persisted)."""
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def export_encrypted_backup")
    assert pos != -1
    body = bridge_source[pos:pos + 3000]
    # The method must call the API facade with both passphrase arguments.
    assert "settings_api.export_encrypted_backup_for_webview" in body
    assert "passphrase" in body
    assert "confirm_passphrase" in body


def test_webview_bridge_backup_methods_do_not_call_import_or_clear() -> None:
    """Phase 6C: neither ``export_encrypted_backup`` nor
    ``preview_encrypted_backup_manifest`` may call
    ``import_encrypted_backup``, ``clear_all_local_data``, or
    ``set_setting_value``. This is a static source-level check on the
    bridge module."""
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    # Check the export method body.
    export_pos = bridge_source.find("def export_encrypted_backup")
    assert export_pos != -1
    # Find the next method definition to bound the export body.
    next_pos = bridge_source.find("\n    def ", export_pos + 1)
    export_body = bridge_source[export_pos:next_pos if next_pos != -1 else export_pos + 3000]
    for forbidden in (
        "import_encrypted_backup",
        "clear_all_local_data",
        "set_setting_value",
    ):
        assert forbidden not in export_body, (
            "export_encrypted_backup must not call: " + forbidden
        )
    # Check the manifest preview method body.
    manifest_pos = bridge_source.find("def preview_encrypted_backup_manifest")
    assert manifest_pos != -1
    next_pos = bridge_source.find("\n    def ", manifest_pos + 1)
    manifest_body = bridge_source[manifest_pos:next_pos if next_pos != -1 else manifest_pos + 3000]
    for forbidden in (
        "import_encrypted_backup",
        "clear_all_local_data",
        "set_setting_value",
    ):
        assert forbidden not in manifest_body, (
            "preview_encrypted_backup_manifest must not call: " + forbidden
        )


# ---------------------------------------------------------------------------
# Phase 6D: Settings / Privacy encrypted backup import + clear-all-local-data
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
# sliced at the next ``\n    def `` so the next method's passphrase
# reference does not trigger false positives.
# ---------------------------------------------------------------------------


def test_webview_bridge_exposes_phase_6d_import_method() -> None:
    """``WebViewBridge`` must expose the Phase 6D ``import_encrypted_backup``
    method with exactly two required parameters (``passphrase`` and
    ``confirm_text``); no optional args, no ``*args``, no ``**kwargs``."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "import_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose Phase 6D bridge method "
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


def test_webview_bridge_exposes_phase_6d_clear_method() -> None:
    """``WebViewBridge`` must expose the Phase 6D ``clear_all_local_data``
    method with exactly one required parameter (``confirm_text``); no
    optional args, no ``*args``, no ``**kwargs``."""
    import inspect

    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    method = getattr(bridge, "clear_all_local_data", None)
    assert callable(method), (
        "WebViewBridge must expose Phase 6D bridge method "
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
    """Phase 6D: the bridge ``import_encrypted_backup`` error payload must
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
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def import_encrypted_backup")
    assert pos != -1, (
        "bridge.py must define import_encrypted_backup for Phase 6D"
    )
    # Slice at the next method definition so the clear_all_local_data
    # method body (which legitimately references ``confirm_text``) is not
    # accidentally included in this check.
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 3000]
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
    """Phase 6D: the bridge ``clear_all_local_data`` error payload must
    collapse to stable Chinese messages and must not leak traceback /
    str(exc) / repr / format_exc / exc_info / .message / raw_exception /
    clipboard_content / passphrase.

    Unlike ``import_encrypted_backup``, ``passphrase`` IS forbidden here
    because the clear-all method never accepts or references a passphrase.
    The method body is sliced at the next ``\\n    def `` so the following
    module-level helper (if any) does not trigger false positives.
    """
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def clear_all_local_data")
    assert pos != -1, (
        "bridge.py must define clear_all_local_data for Phase 6D"
    )
    # Slice at the next method definition so any following helper is not
    # accidentally included.
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 3000]
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
    """Phase 6D: ``import_encrypted_backup`` must pass ``passphrase`` and
    ``confirm_text`` through to
    ``settings_api.import_encrypted_backup_for_webview``. This is a static
    source-level check confirming the passphrase is used as a pass-through
    argument (not logged, not returned, not persisted)."""
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def import_encrypted_backup")
    assert pos != -1
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 3000]
    # The method must call the API facade with both arguments.
    assert "settings_api.import_encrypted_backup_for_webview" in body
    assert "passphrase" in body
    assert "confirm_text" in body


def test_webview_bridge_clear_calls_api_facade() -> None:
    """Phase 6D: ``clear_all_local_data`` must call
    ``settings_api.clear_all_local_data_for_webview`` with
    ``confirm_text``. This is a static source-level check confirming the
    bridge does not touch the DB / service directly."""
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def clear_all_local_data")
    assert pos != -1
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 3000]
    assert "settings_api.clear_all_local_data_for_webview" in body
    assert "confirm_text" in body


def test_webview_bridge_import_does_not_call_export_or_manifest_or_set() -> None:
    """Phase 6D: ``import_encrypted_backup`` must not call
    ``export_encrypted_backup``, ``preview_encrypted_backup_manifest``,
    ``clear_all_local_data``, or ``set_setting_value``. This is a static
    source-level check on the bridge module."""
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def import_encrypted_backup")
    assert pos != -1
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 3000]
    for forbidden in (
        "export_encrypted_backup",
        "preview_encrypted_backup_manifest",
        "set_setting_value",
    ):
        assert forbidden not in body, (
            "import_encrypted_backup must not call: " + forbidden
        )


def test_webview_bridge_clear_does_not_call_backup_actions_or_set() -> None:
    """Phase 6D: ``clear_all_local_data`` must not call
    ``export_encrypted_backup``, ``preview_encrypted_backup_manifest``,
    ``import_encrypted_backup``, or ``set_setting_value``. This is a
    static source-level check on the bridge module."""
    bridge_source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = bridge_source.find("def clear_all_local_data")
    assert pos != -1
    next_def = bridge_source.find("\n    def ", pos + 1)
    body = bridge_source[pos:next_def if next_def != -1 else pos + 3000]
    for forbidden in (
        "export_encrypted_backup",
        "preview_encrypted_backup_manifest",
        "import_encrypted_backup",
        "set_setting_value",
    ):
        assert forbidden not in body, (
            "clear_all_local_data must not call: " + forbidden
        )
