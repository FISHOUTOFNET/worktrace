"""Privacy-safe operator-assisted FD Work project acceptance on Windows."""

from __future__ import annotations

import argparse
import ctypes
from importlib.metadata import version
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from worktrace import config, db
from worktrace.api import project_api
from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.binding_service import FDWorkBindingService
from worktrace.integrations.fd_work.case_identity import case_label_hash
from worktrace.services import project_service


_SAFE_KEYS = (
    "exact_sha",
    "pywebview_version",
    "project_created",
    "binding_created",
    "binding_readback",
    "restart_readback",
    "helper_foreground_count",
    "elapsed_ms",
    "error_code",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("acceptance_state_invalid")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _safe_result(state: dict[str, Any], error_code: str | None) -> dict[str, Any]:
    elapsed = max(0, int((time.monotonic() - float(state["started_at"])) * 1000))
    payload = {
        "exact_sha": str(state.get("exact_sha") or ""),
        "pywebview_version": str(state.get("pywebview_version") or ""),
        "project_created": state.get("project_created") is True,
        "binding_created": state.get("binding_created") is True,
        "binding_readback": state.get("binding_readback") is True,
        "restart_readback": state.get("restart_readback") is True,
        "helper_foreground_count": int(state.get("helper_foreground_count") or 0),
        "elapsed_ms": elapsed,
        "error_code": error_code,
    }
    return {key: payload[key] for key in _SAFE_KEYS}


def _emit_failure(state: dict[str, Any], code: str) -> int:
    print(json.dumps(_safe_result(state, code), sort_keys=True))
    return 1


def _git_sha(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40:
        raise RuntimeError("revision_unavailable")
    return value


def _project_ids(database_path: Path) -> list[int]:
    if not database_path.is_file():
        return []
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id FROM project
            WHERE created_by = 'user' AND is_deleted = 0
            ORDER BY id
            """
        ).fetchall()
    return [int(row[0]) for row in rows]


def _candidate(state: dict[str, Any]) -> dict[str, Any] | None:
    database_path = Path(state["database_path"])
    sidecar_path = Path(state["sidecar_path"])
    if not database_path.is_file() or not sidecar_path.is_file():
        return None
    baseline = {int(value) for value in state.get("baseline_project_ids", [])}
    with sqlite3.connect(database_path) as main:
        main.row_factory = sqlite3.Row
        projects = main.execute(
            """
            SELECT id, name, created_at FROM project
            WHERE created_by = 'user' AND is_deleted = 0
            ORDER BY id
            """
        ).fetchall()
    repository = FDWorkBindingRepository(sidecar_path)
    matches: list[dict[str, Any]] = []
    for row in projects:
        project_id = int(row["id"])
        if project_id in baseline:
            continue
        binding = repository.get_binding(project_id)
        if binding is None:
            continue
        created_at = str(row["created_at"] or "")
        name_hash = case_label_hash(str(row["name"] or ""))
        if (
            binding.project_id == project_id
            and binding.project_created_at == created_at
            and binding.bound_name_hash == name_hash
        ):
            matches.append(
                {
                    "project_id": project_id,
                    "created_at": created_at,
                    "name_hash": name_hash,
                }
            )
    if len(matches) > 1:
        raise RuntimeError("multiple_candidates")
    return matches[0] if matches else None


def _foreground_title() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return str(buffer.value)


def begin(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    exact_sha = _git_sha(root)
    if args.expected_sha and exact_sha != args.expected_sha:
        return _emit_failure(
            {
                "exact_sha": exact_sha,
                "pywebview_version": version("pywebview"),
                "started_at": time.monotonic(),
            },
            "revision_mismatch",
        )
    paths = config.resolve_paths()
    state = {
        "exact_sha": exact_sha,
        "pywebview_version": version("pywebview"),
        "started_at": time.monotonic(),
        "database_path": str(paths.db_path),
        "sidecar_path": str(paths.base_dir / "plugins" / "fd_work" / "state.db"),
        "baseline_project_ids": _project_ids(paths.db_path),
        "project_created": False,
        "binding_created": False,
        "binding_readback": False,
        "restart_readback": False,
        "helper_foreground_count": 0,
    }
    _write_json(args.state, state)
    return 0


def monitor(args: argparse.Namespace) -> int:
    state = _read_json(args.state)
    deadline = time.monotonic() + args.timeout_seconds
    previous_helper = False
    try:
        while time.monotonic() <= deadline:
            helper = _foreground_title() == "FD Work"
            if helper and not previous_helper:
                state["helper_foreground_count"] = (
                    int(state.get("helper_foreground_count") or 0) + 1
                )
            previous_helper = helper
            candidate = _candidate(state)
            if candidate is not None:
                state.update(candidate)
                state["project_created"] = True
                state["binding_created"] = True
                state["binding_readback"] = True
                _write_json(args.state, state)
                return 0
            time.sleep(0.1)
    except Exception:
        state["monitor_error"] = "acceptance_state_unconfirmed"
        _write_json(args.state, state)
        return 1
    state["monitor_error"] = "acceptance_timeout"
    _write_json(args.state, state)
    return 1


def verify_restart(args: argparse.Namespace) -> int:
    state = _read_json(args.state)
    if state.get("monitor_error"):
        return _emit_failure(state, str(state["monitor_error"]))
    try:
        candidate = _candidate(state)
        if candidate is None:
            return _emit_failure(state, "restart_readback_failed")
        if (
            int(candidate["project_id"]) != int(state["project_id"])
            or candidate["created_at"] != state["created_at"]
            or candidate["name_hash"] != state["name_hash"]
        ):
            return _emit_failure(state, "restart_identity_mismatch")
        state["restart_readback"] = True
        if args.cleanup:
            database_path = Path(state["database_path"])
            sidecar_path = Path(state["sidecar_path"])
            db.configure_database(database_path)
            project_service.delete_project(int(state["project_id"]))
            binding_service = FDWorkBindingService(
                FDWorkBindingRepository(sidecar_path),
                project_reader=project_api.get_project,
                project_list_reader=project_service.list_user_project_identities,
            )
            binding_service.clear_binding(int(state["project_id"]))
            if binding_service.repository.get_binding(int(state["project_id"])):
                return _emit_failure(state, "cleanup_failed")
            if any(
                item.project_id == int(state["project_id"])
                for item in binding_service.repository.list_pending_operations()
            ):
                return _emit_failure(state, "cleanup_failed")
        _write_json(args.state, state)
        print(json.dumps(_safe_result(state, None), sort_keys=True))
        return 0
    except Exception:
        return _emit_failure(state, "acceptance_state_unconfirmed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--state", type=Path, required=True)
    begin_parser.add_argument("--expected-sha")
    begin_parser.set_defaults(action=begin)
    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--state", type=Path, required=True)
    monitor_parser.add_argument("--timeout-seconds", type=float, default=600.0)
    monitor_parser.set_defaults(action=monitor)
    restart_parser = subparsers.add_parser("verify-restart")
    restart_parser.add_argument("--state", type=Path, required=True)
    restart_parser.add_argument("--cleanup", action="store_true")
    restart_parser.set_defaults(action=verify_restart)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return int(args.action(args))
    except Exception:
        print(json.dumps({"error_code": "acceptance_environment_unavailable"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
