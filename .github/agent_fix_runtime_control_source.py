from pathlib import Path

path = Path(__file__).with_name("agent_apply_runtime_control.py")
text = path.read_text(encoding="utf-8")

replacements = {
    '''    )
    replace_between(
        path,
        "    def start_collector(\n",
''': '''    )
    start_collector = textwrap.indent(start_collector, "    ")
    replace_between(
        path,
        "    def start_collector(\n",
''',
    '''    )
    replace_once(
        path,
        "    @contextmanager\n    def acquire(\n",
''': '''    )
    helper = textwrap.indent(helper, "    ")
    replace_once(
        path,
        "    @contextmanager\n    def acquire(\n",
''',
}

for old, new in replacements.items():
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"expected one ownership patch target, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8", newline="\n")
