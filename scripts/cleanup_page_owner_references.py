from __future__ import annotations

from pathlib import Path
import subprocess
import traceback

SELF = Path("scripts/cleanup_page_owner_references.py")
WORKFLOW = Path(".github/workflows/cleanup-page-owner-references.yml")
DIAGNOSTIC = Path("diagnostics/page-owner-reference-cleanup-error.txt")
OLD_NAMES = (
    "overview_view_model_service",
    "timeline_view_model_service",
    "session_detail_view_model_service",
)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match for {old!r}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def main() -> None:
    test_path = Path("tests/test_architecture_hardening_regressions.py")
    replace_once(
        test_path,
        "    overview_view_model_service,\n",
        "    view_model_service,\n",
    )
    replace_once(
        test_path,
        "overview_view_model_service.get_overview_view_model(DATE)",
        "view_model_service.get_overview_view_model(DATE)",
    )

    docs = Path("docs/current-state.md")
    text = docs.read_text(encoding="utf-8")
    text = text.replace(
        "overview/timeline/session_detail_view_model_service (page DTO owners)",
        "view_model_service (single Overview / Timeline / Details DTO owner)",
    )
    text = text.replace(
        "Page-specific ViewModel services own their public DTOs and share the same\n"
        "  structural revision and canonical projection snapshot contracts.",
        "`view_model_service` owns all public page DTOs and shares the same\n"
        "  structural revision and canonical projection snapshot contracts.",
    )
    docs.write_text(text, encoding="utf-8", newline="\n")

    offenders: list[str] = []
    for root in (Path("worktrace"), Path("tests"), Path("docs")):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md", ".js"}:
                continue
            source = path.read_text(encoding="utf-8")
            for old_name in OLD_NAMES:
                if old_name in source:
                    offenders.append(f"{path}:{old_name}")
    if offenders:
        raise RuntimeError("legacy page owner references remain: " + ", ".join(offenders))

    DIAGNOSTIC.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)
    SELF.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        failure = traceback.format_exc()
        subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
        DIAGNOSTIC.parent.mkdir(exist_ok=True)
        DIAGNOSTIC.write_text(failure, encoding="utf-8")
        WORKFLOW.unlink(missing_ok=True)
