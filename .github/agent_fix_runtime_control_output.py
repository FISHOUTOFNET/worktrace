from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def indent_block(path: str, start: str, end: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    start_index = text.find(start)
    end_index = text.find(end, start_index + len(start))
    if start_index < 0 or end_index < 0:
        raise AssertionError(f"ownership block not found: {path}: {start!r} -> {end!r}")
    block = text[start_index:end_index]
    if block.startswith("\n"):
        prefix = "\n"
        block = block[1:]
    else:
        prefix = ""
    indented = "\n".join(("    " + line) if line else line for line in block.split("\n"))
    target.write_text(text[:start_index] + prefix + indented + text[end_index:], encoding="utf-8", newline="\n")


indent_block(
    "worktrace/runtime/app_runtime.py",
    "\ndef start_collector(",
    "\n    def _register_maintenance_handlers",
)
indent_block(
    "worktrace/services/secure_backup_service.py",
    "\ndef _require_command_ack(",
    "\n    @contextmanager",
)
