"""Subprocess probe for compact vs expanded projection peak-memory comparison.

Runs in a fresh subprocess so tracemalloc sees only the target object graph.
Invoked by ``test_peak_memory_compact_vs_expanded`` with::

    python tests/support/peak_memory_probe.py --mode compact --size 5000
    python tests/support/peak_memory_probe.py --mode expanded --size 5000

Outputs a single JSON line on stdout with:
    mode, size, entry_count, contribution_count, duplicated_contribution_count,
    current_bytes, peak_bytes, object_count

The expanded reference model duplicates every contribution object (one copy
in the main collection, one copy inline per entry) to simulate the old
pre-compact storage shape.  It is test-only and never imported by production.
"""

from __future__ import annotations

import argparse
import copy
import gc
import json
import sys
import tracemalloc
from pathlib import Path

# Ensure the repo root is importable when run as a standalone script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from worktrace.services.report_projection_builder import ProjectionComputation  # noqa: E402
from worktrace.services.report_projection_model import OperationDiagnostic, freeze_value  # noqa: E402
from worktrace.services.report_projection_provider import (  # noqa: E402
    FrozenDict,
    materialize_day_projection,
)
from worktrace.services.report_revision_service import ProjectionSourceVersion  # noqa: E402

DATE = "2026-07-15"


def _make_entry(key: str, index: int) -> dict:
    return {
        "row_kind": "project_session",
        "report_date": DATE,
        "projection_instance_key": key,
        "projection_revision": f"rev-{index}",
        "project_id": 1,
        "project_name": "P",
        "start_time": f"2026-07-15 09:0{index % 10}:00",
        "end_time": "2026-07-15 09:30:00",
        "duration_seconds": 1800,
        "status": "normal",
        "activity_ids": [index],
        "member_slices": [
            {"report_date": DATE, "activity_id": index, "slice_start_time": "2026-07-15 09:00:00"}
        ],
    }


def _make_contribution(key: str, index: int) -> dict:
    return {
        "projection_instance_key": key,
        "report_date": DATE,
        "activity_id": index,
        "slice_start_time": "2026-07-15 09:00:00",
        "duration_seconds": 1800,
        "status": "normal",
        "activity_display_name": f"Doc{index}",
        "app_name": "App",
        "process_name": "app.exe",
        "window_title": f"Doc{index}",
        "resource_is_anchor": True,
    }


def _build_computation(size: int) -> ProjectionComputation:
    entries = [_make_entry(f"k{i}", i) for i in range(size)]
    contributions = [_make_contribution(f"k{i}", i) for i in range(size)]
    return ProjectionComputation(
        start_date=DATE,
        end_date=DATE,
        base_sessions=[],
        final_entries=entries,
        final_sessions=entries,
        standalone_status_entries=[],
        final_contributions=contributions,
        operation_diagnostics=[],
        snapshot_revision="rev",
        activity_count=size,
    )


def _source_version() -> ProjectionSourceVersion:
    return ProjectionSourceVersion(
        database_key="probe",
        report_date=DATE,
        report_structure_generation=0,
        database_replacement_epoch=0,
        projection_schema_version=1,
    )


def _run_compact(size: int) -> dict:
    """Build the compact DayProjection and measure peak memory."""
    comp = _build_computation(size)
    gc.collect()
    tracemalloc.start()
    projection = materialize_day_projection(comp, _source_version())
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Count duplicated contribution objects: every contribution in
    # contributions_by_key must be the SAME object as one in the main
    # contributions tuple.  duplicated_count == 0 for compact.
    main_ids = {id(c) for c in projection.contributions}
    duplicated = 0
    for indexed_tuple in projection.contributions_by_key.values():
        for indexed in indexed_tuple:
            if id(indexed) not in main_ids:
                duplicated += 1

    return {
        "mode": "compact",
        "size": size,
        "entry_count": len(projection.entries),
        "contribution_count": len(projection.contributions),
        "duplicated_contribution_count": duplicated,
        "current_bytes": current,
        "peak_bytes": peak,
    }


def _run_expanded(size: int) -> dict:
    """Build the expanded reference model and measure peak memory.

    The expanded model duplicates every contribution: one frozen copy in
    the main contributions collection, and a SEPARATE frozen copy inlined
    into each entry's ``_projection_contributions`` field.  This simulates
    the pre-compact storage shape and is test-only — production never
    builds this structure.
    """
    comp = _build_computation(size)
    gc.collect()
    tracemalloc.start()

    # Expanded: freeze contributions for the main collection.
    main_contributions = tuple(
        freeze_value(c) for c in comp.final_contributions
    )
    # Expanded: build entries with inline _projection_contributions holding
    # SEPARATELY frozen copies (duplicate storage).
    expanded_entries = []
    contributions_by_key: dict[str, list] = {}
    for raw_entry in comp.final_entries:
        item = dict(raw_entry)
        key = str(item.get("projection_instance_key") or "")
        inline = []
        for c in comp.final_contributions:
            if str(c.get("projection_instance_key") or "") == key:
                # Deep copy = separate frozen object (duplicate storage).
                inline.append(freeze_value(copy.deepcopy(c)))
        item["_projection_contributions"] = inline
        expanded_entries.append(freeze_value(item))
        if key:
            contributions_by_key.setdefault(key, []).extend(inline)
    # Also keep the main collection (like the old snapshot did).
    expanded_contributions_by_key = FrozenDict(
        {k: tuple(v) for k, v in contributions_by_key.items()}
    )
    expanded_entry_by_key = FrozenDict(
        {
            str(e.get("projection_instance_key") or ""): e
            for e in expanded_entries
            if str(e.get("projection_instance_key") or "")
        }
    )

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Count duplicated contribution objects: inline copies are NOT the same
    # objects as the main collection.  duplicated_count > 0 for expanded.
    main_ids = {id(c) for c in main_contributions}
    duplicated = 0
    for indexed_tuple in expanded_contributions_by_key.values():
        for indexed in indexed_tuple:
            if id(indexed) not in main_ids:
                duplicated += 1

    return {
        "mode": "expanded",
        "size": size,
        "entry_count": len(expanded_entries),
        "contribution_count": len(main_contributions),
        "duplicated_contribution_count": duplicated,
        "current_bytes": current,
        "peak_bytes": peak,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["compact", "expanded"], required=True)
    parser.add_argument("--size", type=int, default=5000)
    args = parser.parse_args()

    if args.mode == "compact":
        result = _run_compact(args.size)
    else:
        result = _run_expanded(args.size)

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
