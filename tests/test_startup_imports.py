import json
import subprocess
import sys
from pathlib import Path


def test_main_import_keeps_optional_heavy_dependencies_lazy():
    code = """
import json
import sys

import worktrace.main

print(json.dumps({
    "openpyxl": "openpyxl" in sys.modules,
    "psutil": "psutil" in sys.modules,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(result.stdout)

    assert loaded == {"openpyxl": False, "psutil": False}
