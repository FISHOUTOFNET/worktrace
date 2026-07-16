"""Code/comment hygiene locks for current WorkTrace semantics."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_TARGETS = (
    REPO_ROOT / "worktrace",
    REPO_ROOT / "tests",
    REPO_ROOT / "scripts",
    REPO_ROOT / "WorkTrace.spec",
)


def _token(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN_REGEXES = (
    re.compile(_token("Ph", "ase")),
    re.compile(_token("ph", "ase_")),
    re.compile(_token("ph", "ase1")),
    re.compile(r"_[0-9]+[a-z]\b"),
    re.compile(_token("3", "B") + r"\."),
    re.compile(r"\b" + _token("3", "C") + r"\b"),
    re.compile(r"\b" + _token("4", "A") + r"\b"),
    re.compile(r"\b" + _token("4", "B") + r"\b"),
    re.compile(r"\b" + _token("5", "H") + r"\b"),
    re.compile(r"\b6[A-I]\b"),
    re.compile(r"\b" + _token("M", "C2") + r"\b"),
    re.compile(r"\b" + _token("M", "4") + r"\b"),
    re.compile(_token("Ph", "ase R[23]")),
    re.compile(r'"' + _token("ph", "ase") + r'"\s*:'),
)

FORBIDDEN_TEXT = (
    _token("app", ".js is split"),
    _token("old app", ".js"),
    _token("current ", "phase scope"),
    _token("later ", "phase"),
    _token("Behavior is ", "unchanged"),
    _token("tests see no API-surface ", "change"),
    _token("duplicated inline checks were ", "replaced"),
    "migration invariants",
    _token("the supported automatic-rules contract and ships ", "regression locks"),
    _token("rule overwrites ", "it."),
    _token("facade. The automatic ", "path"),
    _token("is ", "invented."),
    _token(
        "the Overview / Settings / Statistics / Timeline ",
        "bridge methods live",
    ),
)

# These are current domain identifiers, not historical delivery-stage labels.
CURRENT_DOMAIN_IDENTIFIERS = (
    "RuntimePhase",
)

ALLOWED_FILE_NAMES = {
    "test_code_comment_hygiene.py",
}


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for target in SCAN_TARGETS:
        if target.is_file():
            files.append(target)
            continue
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if path.name in ALLOWED_FILE_NAMES:
                continue
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _without_current_domain_identifiers(line: str) -> str:
    normalized = line
    for identifier in CURRENT_DOMAIN_IDENTIFIERS:
        normalized = normalized.replace(identifier, "")
    return normalized


def test_code_comments_do_not_reintroduce_history_stage_residue() -> None:
    failures: list[str] = []
    for path in _iter_scan_files():
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(_read_text(path).splitlines(), start=1):
            stage_scan_line = _without_current_domain_identifiers(line)
            for regex in FORBIDDEN_REGEXES:
                if regex.search(stage_scan_line):
                    failures.append(f"{rel}:{lineno}: {line.strip()}")
                    break
            else:
                if any(text in line for text in FORBIDDEN_TEXT):
                    failures.append(f"{rel}:{lineno}: {line.strip()}")
    assert not failures, "Historical stage/comment residue found:\n" + "\n".join(
        failures
    )
