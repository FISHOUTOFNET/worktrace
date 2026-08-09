from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
INDEX = UI_ROOT / "index_fd_work_v5.html"
_ASSET_RE = re.compile(
    r'(?P<prefix>(?:href|src)=")(?P<path>(?:styles\.css|js/[^"?]+\.js))(?:\?v=[0-9a-f]+)?(?P<suffix>")'
)


def content_revision(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def expected_index_source(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        relative = urlsplit(match.group("path")).path
        revision = content_revision(UI_ROOT / relative)
        return f'{match.group("prefix")}{relative}?v={revision}{match.group("suffix")}'

    return _ASSET_RE.sub(replace, source)


def sync(*, write: bool) -> bool:
    source = INDEX.read_text(encoding="utf-8")
    expected = expected_index_source(source)
    changed = source != expected
    if changed and write:
        INDEX.write_text(expected, encoding="utf-8", newline="\n")
    return not changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize WebView local asset content revisions.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Rewrite index asset revisions.")
    mode.add_argument("--check", action="store_true", help="Fail when index revisions are stale.")
    args = parser.parse_args()

    current = sync(write=args.write)
    if args.check and not current:
        print("WebView asset revisions are stale; run scripts/sync_webview_asset_revisions.py --write")
        return 1
    if args.write:
        print("WebView asset revisions synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
