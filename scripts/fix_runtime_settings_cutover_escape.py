from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).with_name("cutover_runtime_settings.py")


def main() -> int:
    source = PATH.read_text(encoding="utf-8")
    old = '    assert not violations, "runtime settings calls remain:\\n" + "\\n".join(violations)\n'
    new = '    assert not violations, "runtime settings calls remain:\\\\n" + "\\\\n".join(violations)\n'
    if old not in source:
        raise RuntimeError("runtime settings contract escape target was not found")
    PATH.write_text(source.replace(old, new, 1), encoding="utf-8")
    print("Fixed generated runtime settings contract newline escaping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
