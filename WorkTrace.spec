# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import runpy

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
brand_icon = root / 'build' / 'brand' / 'worktrace.ico'
paused_brand_icon = root / 'build' / 'brand' / 'worktrace-paused.ico'
icon_generator = runpy.run_path(str(root / 'scripts' / 'generate_brand_icon.py'))
icon_generator['generate_icon'](brand_icon)
icon_generator['generate_icon'](paused_brand_icon, grayscale=True)

datas = [
    (str(root / 'worktrace' / 'schema.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'schema_internal.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'schema_indexes.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'privacy_policy_zh-CN.txt'), 'worktrace'),
    (str(root / 'worktrace' / 'platforms' / 'windows_probe_helper.py'), 'worktrace/platforms'),
    (str(root / 'worktrace' / 'integrations' / 'fd_work' / 'fd_work_adapter.js'), 'worktrace/integrations/fd_work'),
    (str(root / 'worktrace' / 'integrations' / 'fd_work' / 'fd_work_picker_session.js'), 'worktrace/integrations/fd_work'),
    (str(root / 'worktrace' / 'webview_ui' / 'index_fd_work_v5.html'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'styles.css'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'ui_components.css'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'project_autocomplete.css'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'core.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'fd_work_v5.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'ui_components.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'project_catalog.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'project_autocomplete.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'overview.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_request_state.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_presentation.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_transient_ui.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_editor_state.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_fd_work.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_delete_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_action_presentation.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'statistics.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'settings.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_render.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_create_panel_v5.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_rule_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_delete_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'page_lifecycle.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'init_fd_work_v5.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'ui_composition.js'), 'worktrace/webview_ui/js'),
    (str(brand_icon), 'worktrace/assets'),
    (str(paused_brand_icon), 'worktrace/assets'),
]
binaries = []
hiddenimports = ['win32api', 'win32con', 'win32gui', 'win32timezone']
# pywebview is the WebView backend used by the default UI entry point.
# collect_all('webview') is a no-op if pywebview is not installed;
# pywebview==6.2.1 is declared in requirements.txt and is required for the app
# to start.
_wv_ret = collect_all('webview')
datas += _wv_ret[0]; binaries += _wv_ret[1]; hiddenimports += _wv_ret[2]


a = Analysis(
    [str(root / 'scripts' / 'pyinstaller_entry.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Portable distribution remains a single executable for users who explicitly
# need that form. The installed application is built from the same Analysis as
# one-dir so normal launches do not pay the one-file extraction cost.
portable_exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Trace-Portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(brand_icon),
)

installed_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Trace',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(brand_icon),
)

installed_app = COLLECT(
    installed_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Trace',
)
