#!/usr/bin/env python3
"""Deterministic comment hygiene gate for WorkTrace."""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
POLICY_FILE = "comment_policy.json"


@dataclass(frozen=True)
class CommentRecord:
    start_line: int
    end_line: int
    text: str
    inline: bool = False
    docstring: bool = False
    module_docstring: bool = False


@dataclass
class FileScan:
    path: str
    code_lines: int = 0
    ordinary_comment_lines: int = 0
    docstring_lines: int = 0
    empty_lines: int = 0
    inline_comments: int = 0
    max_contiguous_ordinary_comment_block: int = 0
    applied_ratio_threshold: float = 0.0
    threshold_source: str = "default"
    violations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ordinary_comment_ratio(self) -> float:
        denominator = self.code_lines + self.ordinary_comment_lines
        if denominator == 0:
            return 0.0
        return self.ordinary_comment_lines / denominator


def load_policy(repo_root: Path) -> dict[str, Any]:
    with (repo_root / POLICY_FILE).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _is_excluded(rel_path: str, exclude_paths: Iterable[str]) -> bool:
    parts = rel_path.split("/")
    for raw in exclude_paths:
        ex = raw.strip("/").replace("\\", "/")
        if not ex:
            continue
        if rel_path == ex or rel_path.startswith(ex + "/"):
            return True
        if "/" not in ex and ex in parts:
            return True
    return False


def iter_scan_files(repo_root: Path, policy: dict[str, Any]) -> list[Path]:
    scan = policy["scan"]
    include_exts = set(scan["include_extensions"])
    exclude_paths = scan["exclude_paths"]
    files: list[Path] = []
    for include in scan["include_paths"]:
        target = repo_root / include
        if not target.exists():
            continue
        candidates = [target] if target.is_file() else target.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            rel_path = _rel(path, repo_root)
            if _is_excluded(rel_path, exclude_paths):
                continue
            if path.suffix in include_exts:
                files.append(path)
    return sorted(files, key=lambda p: _rel(p, repo_root))


def _line_count(text: str) -> int:
    return max(1, len(text.splitlines()))


def _docstring_records(tree: ast.AST) -> list[CommentRecord]:
    records: list[CommentRecord] = []

    def visit(node: ast.AST, module_level: bool = False) -> None:
        body = getattr(node, "body", None)
        if body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                start = first.lineno
                end = getattr(first, "end_lineno", start)
                records.append(
                    CommentRecord(
                        start_line=start,
                        end_line=end,
                        text=first.value.value,
                        docstring=True,
                        module_docstring=module_level,
                    )
                )
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, False)
            elif isinstance(child, ast.Module):
                visit(child, True)

    visit(tree, isinstance(tree, ast.Module))
    return records


def _scan_python(text: str) -> tuple[set[int], set[int], list[CommentRecord]]:
    lines = text.splitlines()
    comment_lines: set[int] = set()
    inline_lines: set[int] = set()
    records: list[CommentRecord] = []
    reader = io.StringIO(text).readline
    try:
        tokens = tokenize.generate_tokens(reader)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            line_no, col = token.start
            prefix = lines[line_no - 1][:col] if line_no - 1 < len(lines) else ""
            inline = bool(prefix.strip())
            comment_lines.add(line_no)
            if inline:
                inline_lines.add(line_no)
            records.append(
                CommentRecord(
                    start_line=line_no,
                    end_line=line_no,
                    text=token.string.lstrip("#").strip(),
                    inline=inline,
                )
            )
    except tokenize.TokenError:
        return comment_lines, inline_lines, records
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return comment_lines, inline_lines, records
    records.extend(_docstring_records(tree))
    return comment_lines, inline_lines, records


def _hash_comment_index(line: str) -> int | None:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" or char == "`":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return index
    return None


def _scan_hash_comments(text: str) -> tuple[set[int], set[int], list[CommentRecord]]:
    comment_lines: set[int] = set()
    inline_lines: set[int] = set()
    records: list[CommentRecord] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        index = _hash_comment_index(line)
        if index is None:
            continue
        inline = bool(line[:index].strip())
        comment_lines.add(line_no)
        if inline:
            inline_lines.add(line_no)
        records.append(
            CommentRecord(
                start_line=line_no,
                end_line=line_no,
                text=line[index + 1 :].strip(),
                inline=inline,
            )
        )
    return comment_lines, inline_lines, records


def _scan_c_style_comments(text: str) -> tuple[set[int], set[int], list[CommentRecord]]:
    lines = text.splitlines()
    comment_lines: set[int] = set()
    inline_lines: set[int] = set()
    records: list[CommentRecord] = []
    in_block = False
    block_start = 0
    block_text: list[str] = []
    quote: str | None = None
    template_depth = 0
    escape = False

    for line_no, line in enumerate(lines, start=1):
        i = 0
        before_comment = ""
        while i < len(line):
            two = line[i : i + 2]
            char = line[i]
            if in_block:
                end = line.find("*/", i)
                if end == -1:
                    comment_lines.add(line_no)
                    block_text.append(line[i:])
                    break
                comment_lines.add(line_no)
                block_text.append(line[i:end])
                after = line[end + 2 :]
                inline = bool(before_comment.strip() or after.strip())
                if inline:
                    for block_line in range(block_start, line_no + 1):
                        inline_lines.add(block_line)
                records.append(
                    CommentRecord(
                        start_line=block_start,
                        end_line=line_no,
                        text="\n".join(block_text).strip(),
                        inline=inline,
                    )
                )
                in_block = False
                block_text = []
                i = end + 2
                continue
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote and not (quote == "`" and template_depth > 0):
                    quote = None
                elif quote == "`" and two == "${":
                    template_depth += 1
                    i += 1
                elif quote == "`" and char == "}" and template_depth:
                    template_depth -= 1
                i += 1
                continue
            if char in ("'", '"', "`"):
                quote = char
                i += 1
                continue
            if two == "//":
                if i > 0 and line[i - 1] == ":":
                    i += 2
                    continue
                inline = bool(before_comment.strip())
                comment_lines.add(line_no)
                if inline:
                    inline_lines.add(line_no)
                records.append(
                    CommentRecord(
                        start_line=line_no,
                        end_line=line_no,
                        text=line[i + 2 :].strip(),
                        inline=inline,
                    )
                )
                break
            if two == "/*":
                before_comment = line[:i]
                end = line.find("*/", i + 2)
                if end == -1:
                    in_block = True
                    block_start = line_no
                    block_text = [line[i + 2 :]]
                    comment_lines.add(line_no)
                    if before_comment.strip():
                        inline_lines.add(line_no)
                    break
                comment_lines.add(line_no)
                after = line[end + 2 :]
                inline = bool(before_comment.strip() or after.strip())
                if inline:
                    inline_lines.add(line_no)
                records.append(
                    CommentRecord(
                        start_line=line_no,
                        end_line=line_no,
                        text=line[i + 2 : end].strip(),
                        inline=inline,
                    )
                )
                i = end + 2
                continue
            before_comment += char
            i += 1

    if in_block:
        records.append(
            CommentRecord(
                start_line=block_start,
                end_line=len(lines),
                text="\n".join(block_text).strip(),
            )
        )
    return comment_lines, inline_lines, records


def _scan_html_comments(text: str) -> tuple[set[int], set[int], list[CommentRecord]]:
    comment_lines: set[int] = set()
    inline_lines: set[int] = set()
    records: list[CommentRecord] = []
    line_starts = [0]
    for match in re.finditer(r"\n", text):
        line_starts.append(match.end())

    def line_for_offset(offset: int) -> int:
        line = 1
        for idx, start in enumerate(line_starts, start=1):
            if start > offset:
                break
            line = idx
        return line

    for match in re.finditer(r"<!--(.*?)-->", text, re.DOTALL):
        start_line = line_for_offset(match.start())
        end_line = line_for_offset(match.end())
        for line_no in range(start_line, end_line + 1):
            comment_lines.add(line_no)
        records.append(
            CommentRecord(
                start_line=start_line,
                end_line=end_line,
                text=match.group(1).strip(),
            )
        )
        start_prefix = text[line_starts[start_line - 1] : match.start()]
        end_suffix_end = text.find("\n", match.end())
        if end_suffix_end == -1:
            end_suffix_end = len(text)
        end_suffix = text[match.end() : end_suffix_end]
        if start_prefix.strip() or end_suffix.strip():
            for line_no in range(start_line, end_line + 1):
                inline_lines.add(line_no)
    return comment_lines, inline_lines, records


def _longest_contiguous_block(
    lines: set[int], inline_lines: set[int]
) -> tuple[int, int | None, int | None]:
    full_line_comments = sorted(lines - inline_lines)
    best = 0
    best_start: int | None = None
    best_end: int | None = None
    current = 0
    current_start: int | None = None
    previous = None
    for line_no in full_line_comments:
        if previous is None or line_no == previous + 1:
            if current_start is None:
                current_start = line_no
            current += 1
        else:
            if current > best:
                best = current
                best_start = current_start
                best_end = previous
            current_start = line_no
            current = 1
        previous = line_no
    if current > best:
        best = current
        best_start = current_start
        best_end = previous
    return best, best_start, best_end


def _commented_out_code(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned or len(cleaned.split()) > 16:
        return False
    patterns = [
        r"^(async\s+)?def\s+\w+\s*\(",
        r"^class\s+[A-Za-z_]\w*(\(|:|$)",
        r"^(from\s+[A-Za-z_][\w.]*\s+import\s+\S+|import\s+[A-Za-z_]\w*(\s*,\s*\w+)*)\s*$",
        r"^return\s+(None|True|False|\d+|[\"']|[A-Za-z_][\w.]*\(.*\))\s*$",
        r"^(if|for|while|with)\s+.+:\s*$",
        r"^(try|else|finally):\s*$",
        r"^except(\s|:|\(|$)",
    ]
    return any(re.search(pattern, cleaned) for pattern in patterns)


def _compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in patterns]


def _violation(
    path: str,
    kind: str,
    message: str,
    evidence: str,
    required_action: str,
    line: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    applied_threshold: float | None = None,
    threshold_source: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": path,
        "kind": kind,
        "message": message,
        "evidence": evidence,
        "required_action": required_action,
    }
    if line is not None:
        item["line"] = line
    if start_line is not None:
        item["start_line"] = start_line
    if end_line is not None:
        item["end_line"] = end_line
    if applied_threshold is not None:
        item["applied_threshold"] = round(applied_threshold, 6)
    if threshold_source is not None:
        item["threshold_source"] = threshold_source
    return item


def resolve_file_ratio_override(
    rel_path: str, policy: dict[str, Any]
) -> tuple[float | None, str]:
    """Resolve the per-file ordinary comment ratio override for a path.

    Exact file path match takes priority over directory prefix match. Returns
    (override_ratio, source) where source is "override:<path>" or "default" when
    no override applies. Directory prefix matches require the override path to
    end with "/" so the match boundary is auditable.
    """
    overrides = policy.get("path_threshold_overrides", []) or []
    for entry in overrides:
        if entry.get("path") == rel_path:
            return entry.get("file_ordinary_comment_ratio_max"), f"override:{entry['path']}"
    for entry in overrides:
        op = entry.get("path", "")
        if op.endswith("/") and rel_path.startswith(op):
            return entry.get("file_ordinary_comment_ratio_max"), f"override:{entry['path']}"
    return None, "default"


def validate_overrides(policy: dict[str, Any]) -> list[str]:
    """Return a list of human-readable override configuration errors."""
    errors: list[str] = []
    overrides = policy.get("path_threshold_overrides", []) or []
    max_ratio = policy.get("override_max_ratio", 0.18)
    allowed_categories = set(
        policy.get("override_allowed_categories", []) or []
    )
    seen: set[str] = set()
    for entry in overrides:
        path = entry.get("path")
        if not path:
            errors.append("override entry missing 'path'")
            continue
        if path in seen:
            errors.append(f"duplicate override path: {path}")
        seen.add(path)
        if any(ch in path for ch in ("*", "?", "[")):
            errors.append(f"override path must not use glob wildcards: {path}")
        ratio = entry.get("file_ordinary_comment_ratio_max")
        if ratio is None:
            errors.append(f"override {path} missing 'file_ordinary_comment_ratio_max'")
        elif ratio > max_ratio + 1e-9:
            errors.append(
                f"override {path} ratio {ratio} exceeds override_max_ratio {max_ratio}"
            )
        if not entry.get("reason"):
            errors.append(f"override {path} missing 'reason'")
        category = entry.get("category")
        if not category:
            errors.append(f"override {path} missing 'category'")
        elif allowed_categories and category not in allowed_categories:
            errors.append(
                f"override {path} category '{category}' not in override_allowed_categories"
            )
    return errors


def _scan_file(path: Path, repo_root: Path, policy: dict[str, Any]) -> FileScan:
    rel_path = _rel(path, repo_root)
    text = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()
    if suffix == ".py":
        comment_lines, inline_lines, records = _scan_python(text)
    elif suffix in {".js", ".css"}:
        comment_lines, inline_lines, records = _scan_c_style_comments(text)
    elif suffix == ".html":
        comment_lines, inline_lines, records = _scan_html_comments(text)
    else:
        comment_lines, inline_lines, records = _scan_hash_comments(text)

    docstring_lines: set[int] = set()
    for record in records:
        if record.docstring:
            docstring_lines.update(range(record.start_line, record.end_line + 1))

    lines = text.splitlines()
    empty_lines = {idx for idx, line in enumerate(lines, start=1) if not line.strip()}
    full_line_comment_lines = comment_lines - inline_lines
    code_lines = (
        set(range(1, len(lines) + 1))
        - empty_lines
        - full_line_comment_lines
        - docstring_lines
    )
    longest_block, block_start, block_end = _longest_contiguous_block(
        comment_lines, inline_lines
    )
    thresholds = policy["thresholds"]
    override_ratio, threshold_source = resolve_file_ratio_override(rel_path, policy)
    effective_ratio_threshold = (
        override_ratio
        if override_ratio is not None
        else thresholds["file_ordinary_comment_ratio_max"]
    )
    scan = FileScan(
        path=rel_path,
        code_lines=len(code_lines),
        ordinary_comment_lines=len(comment_lines),
        docstring_lines=len(docstring_lines),
        empty_lines=len(empty_lines),
        inline_comments=len(inline_lines),
        max_contiguous_ordinary_comment_block=longest_block,
        applied_ratio_threshold=effective_ratio_threshold,
        threshold_source=threshold_source,
    )

    stale_patterns = _compile_patterns(policy["stale_markers"]["fail_patterns"])
    todo_patterns = _compile_patterns(policy["stale_markers"]["todo_patterns"])

    if scan.ordinary_comment_ratio > effective_ratio_threshold:
        scan.violations.append(
            _violation(
                rel_path,
                "file_comment_ratio",
                "File ordinary comment ratio exceeds policy threshold.",
                f"{scan.ordinary_comment_ratio:.4f}",
                "Delete or condense ordinary comments that do not express current constraints.",
                line=1,
                applied_threshold=effective_ratio_threshold,
                threshold_source=threshold_source,
            )
        )
    if (
        scan.max_contiguous_ordinary_comment_block
        > thresholds["max_contiguous_ordinary_comment_block"]
    ):
        scan.violations.append(
            _violation(
                rel_path,
                "long_comment_block",
                "Contiguous ordinary comment block exceeds policy threshold.",
                str(scan.max_contiguous_ordinary_comment_block),
                "Condense the block to the shortest current invariant or delete it.",
                start_line=block_start,
                end_line=block_end,
            )
        )
    if scan.inline_comments > thresholds["max_inline_comments_per_file"]:
        scan.violations.append(
            _violation(
                rel_path,
                "too_many_inline_comments",
                "File has too many inline comments.",
                str(scan.inline_comments),
                "Remove inline comments that restate nearby code.",
                line=1,
            )
        )

    for record in records:
        limit = (
            thresholds["max_module_docstring_lines"]
            if record.module_docstring
            else thresholds["max_docstring_lines_default"]
        )
        if record.docstring and _line_count(record.text) > limit:
            scan.violations.append(
                _violation(
                    rel_path,
                    "docstring_too_long",
                    "Docstring exceeds policy threshold.",
                    f"{_line_count(record.text)} lines",
                    "Condense the docstring to the current public contract.",
                    start_line=record.start_line,
                    end_line=record.end_line,
                )
            )
        for pattern in stale_patterns:
            if pattern.search(record.text):
                scan.violations.append(
                    _violation(
                        rel_path,
                        "stale_marker",
                        "Comment contains a stale history or architecture marker.",
                        pattern.pattern,
                        "Delete stale narrative or rewrite as a current enforced contract.",
                        start_line=record.start_line,
                        end_line=record.end_line,
                    )
                )
                break
        for pattern in todo_patterns:
            if pattern.search(record.text):
                scan.violations.append(
                    _violation(
                        rel_path,
                        "todo_marker",
                        "Comment contains an untracked TODO/FIXME/XXX marker.",
                        pattern.pattern,
                        "Remove the marker or move the work to a tracked test/backlog item.",
                        start_line=record.start_line,
                        end_line=record.end_line,
                    )
                )
                break
        if not record.docstring and _commented_out_code(record.text):
            scan.violations.append(
                _violation(
                    rel_path,
                    "commented_out_code",
                    "Comment looks like disabled source code.",
                    record.text,
                    "Delete commented-out code.",
                    start_line=record.start_line,
                    end_line=record.end_line,
                )
            )
    return scan


def _sort_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        violations,
        key=lambda v: (
            v.get("path", ""),
            v.get("line", v.get("start_line", 0)),
            v.get("kind", ""),
        ),
    )


def scan_repository(repo_root: Path, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    active_policy = policy if policy is not None else load_policy(root)
    override_errors = validate_overrides(active_policy)
    file_scans = [_scan_file(path, root, active_policy) for path in iter_scan_files(root, active_policy)]
    totals = {
        "files": len(file_scans),
        "code_lines": sum(item.code_lines for item in file_scans),
        "ordinary_comment_lines": sum(item.ordinary_comment_lines for item in file_scans),
        "docstring_lines": sum(item.docstring_lines for item in file_scans),
        "empty_lines": sum(item.empty_lines for item in file_scans),
        "inline_comments": sum(item.inline_comments for item in file_scans),
    }
    denominator = totals["code_lines"] + totals["ordinary_comment_lines"]
    totals["ordinary_comment_ratio"] = (
        totals["ordinary_comment_lines"] / denominator if denominator else 0.0
    )
    violations: list[dict[str, Any]] = []
    for error in override_errors:
        violations.append(
            _violation(
                "comment_policy.json",
                "override_config",
                "Invalid per-path threshold override configuration.",
                error,
                "Fix the override entry so it is auditable and within override_max_ratio.",
                line=1,
            )
        )
    for item in file_scans:
        violations.extend(item.violations)
    repo_limit = active_policy["thresholds"]["repo_ordinary_comment_ratio_max"]
    if totals["ordinary_comment_ratio"] > repo_limit:
        violations.append(
            _violation(
                ".",
                "repo_comment_ratio",
                "Repository ordinary comment ratio exceeds policy threshold.",
                f"{totals['ordinary_comment_ratio']:.4f}",
                "Delete or condense redundant ordinary comments across scanned code.",
                line=1,
                applied_threshold=repo_limit,
                threshold_source="default",
            )
        )
    violations = _sort_violations(violations)
    files = [
        {
            "path": item.path,
            "code_lines": item.code_lines,
            "ordinary_comment_lines": item.ordinary_comment_lines,
            "docstring_lines": item.docstring_lines,
            "empty_lines": item.empty_lines,
            "inline_comments": item.inline_comments,
            "ordinary_comment_ratio": round(item.ordinary_comment_ratio, 6),
            "max_contiguous_ordinary_comment_block": item.max_contiguous_ordinary_comment_block,
            "applied_ratio_threshold": round(item.applied_ratio_threshold, 6),
            "threshold_source": item.threshold_source,
            "violations": _sort_violations(item.violations),
        }
        for item in file_scans
    ]
    required_actions = sorted({item["required_action"] for item in violations})
    return {
        "ok": not violations,
        "policy_version": active_policy["version"],
        "repo_root": str(root),
        "totals": totals,
        "violations": violations,
        "files": files,
        "required_actions": required_actions,
    }


def print_summary(report: dict[str, Any]) -> None:
    totals = report["totals"]
    print("Comment hygiene summary")
    print(f"  ok: {report['ok']}")
    print(f"  files scanned: {totals['files']}")
    print(f"  code lines: {totals['code_lines']}")
    print(f"  ordinary comment lines: {totals['ordinary_comment_lines']}")
    print(f"  docstring lines: {totals['docstring_lines']}")
    print(f"  empty lines: {totals['empty_lines']}")
    print(f"  ordinary comment ratio: {totals['ordinary_comment_ratio']:.4f}")
    print(f"  violations: {len(report['violations'])}")
    for violation in report["violations"][:20]:
        line = violation.get("line", violation.get("start_line", 1))
        print(
            f"  - {violation['path']}:{line}: "
            f"{violation['kind']}: {violation['message']}"
        )
    if len(report["violations"]) > 20:
        print(f"  ... {len(report['violations']) - 20} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Exit non-zero on violations.")
    mode.add_argument("--json", action="store_true", help="Print stable JSON report.")
    mode.add_argument("--summary", action="store_true", help="Print human-readable summary.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root containing comment_policy.json.",
    )
    args = parser.parse_args(argv)

    report = scan_repository(args.repo_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_summary(report)
    if args.check:
        return 0 if report["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
