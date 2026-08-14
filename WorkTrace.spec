# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)

datas = [
    (str(root / 'worktrace' / 'schema.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'schema_internal.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'schema_indexes.sql'), 'worktrace'),
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
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_delete_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'statistics.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'settings.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_render.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_create_panel_v5.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_rule_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_delete_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'init_fd_work_v5.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'ui_composition.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'assets' / 'worktrace.ico'), 'worktrace/assets'),
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Trace',
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
    icon=str(root / 'worktrace' / 'assets' / 'worktrace.ico'),
)
