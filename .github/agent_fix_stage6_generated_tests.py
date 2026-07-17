from pathlib import Path

path = Path(__file__).with_name("agent_apply_stage6_contracts.py")
text = path.read_text(encoding="utf-8")
replacements = {
    r'''            assert "App.refreshAll = function" in source
            assert "App.callBridge" not in source
            assert "window.pywebview.api" not in source
            all_decls = re.findall(r'\n    function \w+\s*\(', source)
''': r'''            assert "App.refreshAll = function" in source
            assert "App.callBridge" not in source
            assert "function invokeBridge" in source
            all_decls = re.findall(r'\\n    function \\w+\\s*\\(', source)
''',
    r'''                source = "\n".join(sources.values())
''': r'''                source = "\\n".join(sources.values())
''',
}
for old, new in replacements.items():
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"generated test patch target count: {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8", newline="\n")
