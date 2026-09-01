from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

core_path = ROOT / "worktrace/services/folder_index_service.py"
core = core_path.read_text(encoding="utf-8")
old = '''    except Exception as exc:\n        logging.warning(\n            "folder index build failed rule=%s exception=%s",\n            int(rule_id),\n            type(exc).__name__,\n        )\n        _fail_generation(rule_id, generation, "folder_index_build_failed")\n        return False\n'''
new = '''    except Exception as exc:\n        database_failure = classify_database_failure(exc)\n        if database_failure is not None:\n            logging.warning(\n                "folder index build interrupted rule=%s code=%s",\n                int(rule_id),\n                database_failure.value,\n            )\n            raise\n        logging.warning(\n            "folder index build failed rule=%s exception=%s",\n            int(rule_id),\n            type(exc).__name__,\n        )\n        _fail_generation(rule_id, generation, "folder_index_build_failed")\n        return False\n'''
if core.count(old) != 1:
    raise RuntimeError(f"folder core expected one build block, found {core.count(old)}")
core = core.replace(
    "from ..constants import EXCLUDED_PROJECT\n",
    "from ..constants import EXCLUDED_PROJECT\nfrom ..database_failure_policy import classify_database_failure\n",
    1,
)
core_path.write_text(core.replace(old, new, 1), encoding="utf-8")

patch_path = ROOT / "scripts/task3_patch.py"
patch = patch_path.read_text(encoding="utf-8")
start_marker = "# Folder core: infrastructure contention must not become a durable index error.\n"
end_marker = "# Folder reconciliation: keep old integer API and add truthful result API for runtime.\n"
start = patch.index(start_marker)
end = patch.index(end_marker)
patch = patch[:start] + "# Folder core patched by task3_patch_fix.py.\n\n" + patch[end:]
patch_path.write_text(patch, encoding="utf-8")
