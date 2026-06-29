# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)

datas = [
    (str(root / 'worktrace' / 'schema.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'platforms' / 'open_files_helper.py'), 'worktrace/platforms'),
    (str(root / 'worktrace' / 'webview_ui' / 'index.html'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'styles.css'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'core.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'overview.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline_correction.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'statistics.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'settings.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_render.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_rule_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_keyword_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_folder_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'rules_project_actions.js'), 'worktrace/webview_ui/js'),
    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'init.js'), 'worktrace/webview_ui/js'),
]
binaries = []
hiddenimports = ['win32timezone']
# customtkinter is bundled because the legacy worktrace.ui package still
# ships in the source tree as legacy code pending removal. The default
# runtime path (WebView) does not import it.
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pywebview is the WebView backend used by the default UI entry point as of
# Phase 1. collect_all('webview') is a no-op if pywebview is not installed;
# pywebview>=5.0 is declared in requirements.txt and is required for WorkTrace
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
    name='WorkTrace',
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
)
