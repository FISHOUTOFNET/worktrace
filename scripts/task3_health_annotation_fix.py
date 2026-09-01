from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "worktrace/services/folder_index_runtime_service.py"
source = path.read_text(encoding="utf-8")

old_import = "from ..worker_health import degraded_failure\n"
new_import = "from ..worker_health import WorkerHealthReporter, degraded_failure\n"
if source.count(old_import) != 1:
    raise RuntimeError(f"expected one worker_health import, found {source.count(old_import)}")
source = source.replace(old_import, new_import, 1)

old_signature = "    health,\n) -> None:\n"
new_signature = "    health: WorkerHealthReporter,\n) -> None:\n"
if source.count(old_signature) != 1:
    raise RuntimeError(f"expected one folder worker health parameter, found {source.count(old_signature)}")
source = source.replace(old_signature, new_signature, 1)

path.write_text(source, encoding="utf-8")
