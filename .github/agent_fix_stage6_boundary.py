from pathlib import Path

path = Path(__file__).with_name("agent_apply_stage6_contracts.py")
text = path.read_text(encoding="utf-8")
old_test = '''                source = "\\n".join(path.read_text(encoding="utf-8") for path in packaged)
                assert "App.callBridge" not in source
                assert "window.pywebview.api" not in source
                assert "App.liveRuntime =" not in source
                assert "set: function (value)" not in source
                assert "App.liveRuntimeStore.acceptEnvelope" in source
'''
new_test = '''                sources = {
                    path.name: path.read_text(encoding="utf-8") for path in packaged
                }
                source = "\\n".join(sources.values())
                assert "App.callBridge" not in source
                assert "App.liveRuntime =" not in source
                assert "set: function (value)" not in source
                assert "App.liveRuntimeStore.acceptEnvelope" in source
                assert "window.pywebview.api" in sources["init.js"]
                assert "function invokeBridge" in sources["init.js"]
                for name, module_source in sources.items():
                    if name != "init.js":
                        assert "window.pywebview.api" not in module_source
'''
old_verify = '''    all_js = "\\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "worktrace/webview_ui/js").glob("*.js"))
    )
    if "App.callBridge" in all_js or "window.pywebview.api" in all_js:
        raise AssertionError("dynamic bridge access remains in shipping JavaScript")
'''
new_verify = '''    js_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "worktrace/webview_ui/js").glob("*.js"))
    }
    all_js = "\\n".join(js_sources.values())
    if "App.callBridge" in all_js:
        raise AssertionError("dynamic bridge dispatch remains in shipping JavaScript")
    offenders = [
        name for name, source in js_sources.items()
        if name != "init.js" and "window.pywebview.api" in source
    ]
    if offenders:
        raise AssertionError(f"direct pywebview access outside fixed client: {offenders}")
    if "window.pywebview.api" not in js_sources.get("init.js", ""):
        raise AssertionError("fixed bridge client boundary is missing")
'''
for old, new in ((old_test, new_test), (old_verify, new_verify)):
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"stage6 boundary patch target count: {count}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8", newline="\n")
