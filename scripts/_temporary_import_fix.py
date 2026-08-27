from pathlib import Path

path = Path(__file__).resolve().parents[1] / "worktrace/services/folder_index_service.py"
text = path.read_text(encoding="utf-8")
old = '''from ..resources.title_parsing import normalize_file_name\nfrom ..write_gate import DATABASE_WRITE_GATE\nfrom . import (\n    folder_index_maintenance_service,\n    folder_index_state_repository,\n    privacy_gate_service,\n)\n\nif TYPE_CHECKING:\n    from ..retry_state import RetryEpisode\nfrom ..worker_health import WorkerHealthReporter\n'''
new = '''from ..resources.title_parsing import normalize_file_name\nfrom ..retry_state import RetryEpisode\nfrom ..write_gate import DATABASE_WRITE_GATE\nfrom . import (\n    folder_index_maintenance_service,\n    folder_index_state_repository,\n    privacy_gate_service,\n)\n\nif TYPE_CHECKING:\n    from ..worker_health import WorkerHealthReporter\n'''
if text.count(old) != 1:
    raise RuntimeError(f"unexpected folder-index import shape: {text.count(old)} matches")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
