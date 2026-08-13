from __future__ import annotations

import argparse
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = "tests/fixtures/webview/typography_acceptance.html"
REPORT_RE = re.compile(r'<pre id="typography-report"[^>]*>(.*?)</pre>', re.DOTALL)


def _edge_path() -> Path:
    candidates: list[Path] = []
    found = shutil.which("msedge") or shutil.which("msedge.exe")
    if found:
        candidates.append(Path(found))
    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Microsoft Edge executable was not found")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        del args


@contextmanager
def _local_server():
    handler = partial(_QuietHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/{FIXTURE}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _edge_command(edge: Path, *, profile: Path, width: int, height: int, scale: float) -> list[str]:
    return [
        str(edge),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        f"--force-device-scale-factor={scale}",
        "--virtual-time-budget=2500",
    ]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Edge headless render failed\n"
            + "command: " + " ".join(command) + "\n"
            + "stdout:\n" + result.stdout[-4000:] + "\n"
            + "stderr:\n" + result.stderr[-4000:]
        )
    return result


def _parse_report(dom: str) -> dict[str, object]:
    match = REPORT_RE.search(dom)
    if not match:
        raise RuntimeError("typography report was not emitted by the rendered page")
    payload = html.unescape(match.group(1)).strip()
    if not payload:
        raise RuntimeError("typography report was empty")
    return json.loads(payload)


def _render_profile(
    edge: Path,
    url: str,
    output_dir: Path,
    *,
    name: str,
    width: int,
    height: int,
    scale: float,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="worktrace-typography-edge-") as profile_dir:
        profile = Path(profile_dir)
        base = _edge_command(edge, profile=profile, width=width, height=height, scale=scale)
        dump = _run(base + ["--dump-dom", url])
        report = _parse_report(dump.stdout)
        screenshot = output_dir / f"typography-{name}.png"
        _run(base + [f"--screenshot={screenshot}", url])

    if not screenshot.is_file() or screenshot.stat().st_size < 5000:
        raise RuntimeError(f"render screenshot was not produced correctly: {screenshot}")
    if report.get("pass") is not True:
        raise RuntimeError(
            f"typography acceptance failed for {name}: "
            + json.dumps(report, ensure_ascii=False, indent=2)
        )
    report["screenshot"] = screenshot.name
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render WorkTrace typography with Windows Microsoft Edge.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test-results" / "typography",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if os.name != "nt":
        raise RuntimeError("typography acceptance must run on Windows so Microsoft YaHei UI is real")

    edge = _edge_path()
    profiles = (
        ("desktop", 1080, 720, 1.0),
        ("compact-150", 800, 540, 1.5),
    )
    reports: dict[str, object] = {
        "edge": str(edge),
        "profiles": {},
    }
    with _local_server() as url:
        for name, width, height, scale in profiles:
            reports["profiles"][name] = _render_profile(
                edge,
                url,
                output_dir,
                name=name,
                width=width,
                height=height,
                scale=scale,
            )

    report_path = output_dir / "typography-report.json"
    report_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
