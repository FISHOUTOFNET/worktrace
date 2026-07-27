"""HEAD-owned deterministic fixture builder shared by product and WebView drivers.

Benchmark-only: constructs synthetic activity facts mirroring the dataset
shape embedded in ``product_benchmark_driver.py`` and
``webview_render_perf.py``.  Responsible only for deterministic fixture
construction — not measurement, threshold judgement, workflow
orchestration, WebView startup, or revision comparison.

Privacy: facts use synthetic ``AppN``/``DocN`` names and opaque resource
identity keys.  No real titles, paths, or hosts are recorded.

Connection / transaction contract
--------------------------------
Each ``build_*`` function:

* acquires the connection O(1) times (one ``get_connection()`` call),
* commits in fixed-size chunks of ``chunk_size`` rows (transaction
  boundary bounded by ``ceil(N / chunk_size) + O(1)``),
* never opens a per-activity connection or commits per activity,
* records actual ``connection_count`` and ``commit_count`` in
  ``BenchmarkFixtureResult`` for audit,
* uses the public API (``insert_open_activity`` / ``close_activity``)
  so rows are semantically identical to production-prepared rows.

The chunk strategy is fixed (never varies by revision); the chunk size is
embedded in the fixture hash so any change invalidates cross-revision
comparisons.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

# Fixed deterministic fixture parameters — no RNG, so the fixture is
# identical across revisions and runs.  These mirror the historical
# constants in the now-removed inline builders.
DEFAULT_REPORT_DATE = "2026-07-15"
DEFAULT_DAY_START_SECONDS = 9 * 3600   # 09:00:00
DEFAULT_SPAN_SECONDS = 13 * 3600      # 09:00:00 -> 22:00:00
DEFAULT_CHUNK_SIZE = 500

_BUILDER_VERSION = "1.0"


@dataclass(frozen=True)
class BenchmarkFixtureSpec:
    """Deterministic parameters for one benchmark fixture build.

    The spec is fully deterministic (no RNG): the same spec produces the
    same rows in the same order on every revision.  ``scenario`` is
    informational; it is recorded in the result so the comparison layer
    can verify the driver actually ran the requested scenario.
    """

    report_date: str
    activity_count: int
    day_start_seconds: int
    span_seconds: int
    scenario: str
    seed: int = 0
    chunk_size: int = DEFAULT_CHUNK_SIZE


@dataclass
class BenchmarkFixtureResult:
    """Outcome of one fixture build, including audit data."""

    report_date: str
    scenario: str
    requested_count: int
    inserted_count: int
    preexisting_activity_count: int
    activity_ids: list[int] = field(default_factory=list)
    anchor_project_id: int = 0
    other_project_id: int = 0
    uncategorized_project_id: int = 0
    fixture_build_seconds: float = 0.0
    connection_count: int = 0
    commit_count: int = 0
    chunk_size: int = DEFAULT_CHUNK_SIZE
    builder_version: str = _BUILDER_VERSION

    def to_audit_dict(self) -> dict[str, Any]:
        """Return the audit subset written into driver artifacts.

        ``activity_ids`` are intentionally omitted — they can be huge and
        are not needed by the comparison layer.  The audit fields are
        sufficient to prove the build met the scenario-isolation and
        connection/transaction contracts.
        """

        return {
            "scenario": self.scenario,
            "requested_count": self.requested_count,
            "inserted_count": self.inserted_count,
            "preexisting_activity_count": self.preexisting_activity_count,
            "fixture_build_seconds": round(self.fixture_build_seconds, 6),
            "connection_count": self.connection_count,
            "commit_count": self.commit_count,
            "chunk_size": self.chunk_size,
            "builder_version": self.builder_version,
            "report_date": self.report_date,
        }


def fixture_hash(spec: BenchmarkFixtureSpec) -> str:
    """Compute a deterministic SHA-256 hash of the fixture parameters.

    The hash encodes every parameter that affects row identity or row
    count: report date, day start, span, scenario, seed, and chunk size.
    Both baseline and HEAD must produce the same hash, which the
    comparison layer cross-checks.  Changing ``chunk_size`` changes the
    hash so silent strategy drift between revisions is impossible.
    """

    payload = json.dumps(
        {
            "report_date": spec.report_date,
            "activity_count": spec.activity_count,
            "day_start_seconds": spec.day_start_seconds,
            "span_seconds": spec.span_seconds,
            "scenario": spec.scenario,
            "seed": spec.seed,
            "chunk_size": spec.chunk_size,
            "builder_version": _BUILDER_VERSION,
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def format_time(day: str, seconds_into_day: int) -> str:
    """Format ``seconds_into_day`` as ``YYYY-MM-DD HH:MM:SS`` on ``day``."""

    hours, rem = divmod(int(seconds_into_day), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{day} {hours:02d}:{minutes:02d}:{secs:02d}"


def _build_resource(index: int) -> Any:
    """Build a synthetic DetectedResource using the target revision's type."""

    from worktrace.resources.types import DetectedResource

    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=f"Doc{index}",
        identity_key=f"resource:doc:{index}",
        is_anchor=(index % 17 == 0),
        confidence=80,
        source="auto",
        app_name="App",
        process_name="app.exe",
        window_title=f"Doc{index}",
        path_hint=f"D:\\Bench\\Doc{index}.txt",
        path_key=f"path:doc:{index}",
        uri_scheme="",
        uri_host="",
        uri_hint="",
        metadata_json="",
    )


def _prepare_activity(
    *,
    app_name: str,
    process_name: str,
    window_title: str,
    start_time: str,
    status: str,
    source: str,
    project_id: int | None,
    resource: Any,
) -> Any:
    from worktrace.services import activity_fact_repository

    return activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload={
            "app_name": app_name,
            "process_name": process_name,
            "window_title": window_title,
            "status": status,
            "project_id": project_id,
            "file_path_hint": None,
            "resource": resource,
        },
    )


def _ensure_benchmark_projects(conn: Any) -> dict[str, int]:
    """Create two benchmark projects if absent, returning their IDs.

    Uses the caller's connection so the O(1) connection contract holds.
    The INSERT mirrors ``project_service.create_project`` semantics
    (same columns, same defaults) without opening a separate connection
    or invoking the catalog UoW mark_changed path — the benchmark
    fixture operates on a fresh temp database where there is no cached
    data generation state to invalidate.
    """

    from worktrace.db import now_str

    def _ensure(name: str) -> int:
        row = conn.execute(
            "SELECT id FROM project WHERE name = ?",
            (name,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        timestamp = now_str()
        cursor = conn.execute(
            """
            INSERT INTO project(
                name, description, language, is_archived, enabled,
                created_by, created_at, updated_at
            ) VALUES (?, '', '中文', 0, 1, 'user', ?, ?)
            """,
            (name, timestamp, timestamp),
        )
        return int(cursor.lastrowid)

    return {
        "anchor": _ensure("BenchAnchor"),
        "other": _ensure("BenchOther"),
    }


def _count_existing_activities(conn: Any, report_date: str) -> int:
    """Count activities already present on ``report_date``.

    Used to assert ``preexisting_activity_count == 0`` for scenario
    isolation.  The query is intentionally scoped to the report date so a
    prior scenario on a different date does not pollute the count.
    """

    row = conn.execute(
        "SELECT COUNT(*) FROM activity_log WHERE DATE(start_time) = ?",
        (report_date,),
    ).fetchone()
    return int(row[0] if row else 0)


def build_activity_fixture(
    *,
    spec: BenchmarkFixtureSpec,
) -> BenchmarkFixtureResult:
    """Insert ``spec.activity_count`` synthetic facts on ``spec.report_date``.

    Distribution mirrors the historical inline builder:
      * continuous uncategorized normal activities (the majority);
      * multi-project alternation via sparse manual anchors;
      * short sessions (10s) interleaved with longer ones;
      * sparse context anchors so context attribution must walk neighbours;
      * one paused standalone status row.

    Connection / transaction contract:
      * one ``get_connection()`` call,
      * commit every ``spec.chunk_size`` rows,
      * one final commit for the remainder.
    """

    from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL, STATUS_PAUSED
    from worktrace.db import get_connection, now_str
    from worktrace.services import activity_fact_repository
    from worktrace.services.report_fact_query_service import (
        get_uncategorized_project_id,
    )

    if spec.activity_count < 1:
        raise ValueError("activity_count must be >= 1")

    step = max(5, spec.span_seconds // max(spec.activity_count, 1))
    activity_ids: list[int] = []

    started = time.perf_counter()
    connection_count = 0
    commit_count = 0
    preexisting_activity_count = 0
    uncategorized_id = 0

    with get_connection() as conn:
        connection_count += 1
        # Close any open activities left by a prior build so the
        # uq_activity_log_single_open unique index is not violated.
        # This is a pre-condition of the repository's insert_open_activity
        # contract, not a benchmark-only shortcut.
        activity_fact_repository.close_all_open_activities(conn, now_str())
        preexisting_activity_count = _count_existing_activities(
            conn, spec.report_date
        )
        uncategorized_id = get_uncategorized_project_id(conn)
        projects = _ensure_benchmark_projects(conn)
        anchor_project = projects["anchor"]
        other_project = projects["other"]

        for index in range(spec.activity_count):
            start_offset = spec.day_start_seconds + index * step
            if start_offset >= spec.day_start_seconds + spec.span_seconds:
                start_offset = (
                    spec.day_start_seconds + spec.span_seconds - step
                )
            if index % 5 == 0:
                duration = 10
            else:
                duration = max(5, step - (index % 7))
            end_offset = start_offset + duration
            start_time = format_time(spec.report_date, start_offset)
            end_time = format_time(spec.report_date, end_offset)

            status = STATUS_NORMAL
            project_id: int | None = None
            if index % 23 == 5 and index != 0:
                status = STATUS_NORMAL
                project_id = anchor_project
            elif index % 31 == 0 and index != 0:
                project_id = other_project
            elif index == max(0, spec.activity_count - 1):
                status = STATUS_PAUSED
                project_id = None

            resource = _build_resource(index)
            prepared = _prepare_activity(
                app_name=f"App{index % 4}",
                process_name="app.exe",
                window_title=f"Doc{index}",
                start_time=start_time,
                status=status,
                source=SOURCE_AUTO,
                project_id=project_id,
                resource=resource,
            )
            activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )
            if status != STATUS_PAUSED:
                activity_fact_repository.close_activity(
                    conn, activity_id, end_time
                )
            activity_ids.append(activity_id)

            # Fixed chunk commit strategy: commit every chunk_size rows so
            # the transaction boundary is bounded and identical across
            # baseline/HEAD.  The final commit below handles the remainder.
            if (index + 1) % spec.chunk_size == 0:
                conn.commit()
                commit_count += 1

        # Final commit for any remainder rows.
        conn.commit()
        commit_count += 1

    elapsed = time.perf_counter() - started
    return BenchmarkFixtureResult(
        report_date=spec.report_date,
        scenario=spec.scenario,
        requested_count=spec.activity_count,
        inserted_count=len(activity_ids),
        preexisting_activity_count=preexisting_activity_count,
        activity_ids=activity_ids,
        anchor_project_id=anchor_project,
        other_project_id=other_project,
        uncategorized_project_id=uncategorized_id,
        fixture_build_seconds=elapsed,
        connection_count=connection_count,
        commit_count=commit_count,
        chunk_size=spec.chunk_size,
        builder_version=_BUILDER_VERSION,
    )


def build_contribution_fixture(
    *,
    spec: BenchmarkFixtureSpec,
) -> BenchmarkFixtureResult:
    """Insert ``spec.activity_count`` back-to-back activities forming one session.

    All activities are contiguous (5s each, no gaps) in the uncategorized
    project, so the session builder merges them into a single session with
    ``spec.activity_count`` member contributions.  This stresses the O(N)
    contribution index build and the single-session contribution lookup.

    Connection / transaction contract:
      * one ``get_connection()`` call,
      * commit every ``spec.chunk_size`` rows,
      * one final commit for the remainder.
    """

    from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
    from worktrace.db import get_connection, now_str
    from worktrace.services import activity_fact_repository
    from worktrace.services.report_fact_query_service import (
        get_uncategorized_project_id,
    )

    if spec.activity_count < 1:
        raise ValueError("activity_count must be >= 1")

    duration = 5
    activity_ids: list[int] = []

    started = time.perf_counter()
    connection_count = 0
    commit_count = 0
    preexisting_activity_count = 0
    uncategorized_id = 0

    with get_connection() as conn:
        connection_count += 1
        # Close any open activities left by a prior build so the
        # uq_activity_log_single_open unique index is not violated.
        activity_fact_repository.close_all_open_activities(conn, now_str())
        preexisting_activity_count = _count_existing_activities(
            conn, spec.report_date
        )
        uncategorized_id = get_uncategorized_project_id(conn)
        projects = _ensure_benchmark_projects(conn)

        for index in range(spec.activity_count):
            start_offset = spec.day_start_seconds + index * duration
            end_offset = start_offset + duration
            start_time = format_time(spec.report_date, start_offset)
            end_time = format_time(spec.report_date, end_offset)

            resource = _build_resource(index)
            prepared = _prepare_activity(
                app_name=f"App{index % 4}",
                process_name="app.exe",
                window_title=f"Doc{index}",
                start_time=start_time,
                status=STATUS_NORMAL,
                source=SOURCE_AUTO,
                project_id=None,
                resource=resource,
            )
            activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )
            activity_fact_repository.close_activity(
                conn, activity_id, end_time
            )
            activity_ids.append(activity_id)

            if (index + 1) % spec.chunk_size == 0:
                conn.commit()
                commit_count += 1

        conn.commit()
        commit_count += 1

    elapsed = time.perf_counter() - started
    return BenchmarkFixtureResult(
        report_date=spec.report_date,
        scenario=spec.scenario,
        requested_count=spec.activity_count,
        inserted_count=len(activity_ids),
        preexisting_activity_count=preexisting_activity_count,
        activity_ids=activity_ids,
        anchor_project_id=projects["anchor"],
        other_project_id=projects["other"],
        uncategorized_project_id=uncategorized_id,
        fixture_build_seconds=elapsed,
        connection_count=connection_count,
        commit_count=commit_count,
        chunk_size=spec.chunk_size,
        builder_version=_BUILDER_VERSION,
    )


def build_20k_activity_spec(
    *,
    activity_count: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> BenchmarkFixtureSpec:
    """Build the canonical ``20k_activities`` spec.

    The scenario name is fixed so the comparison layer can verify the
    driver actually ran the requested scenario.
    """

    return BenchmarkFixtureSpec(
        report_date=DEFAULT_REPORT_DATE,
        activity_count=activity_count,
        day_start_seconds=DEFAULT_DAY_START_SECONDS,
        span_seconds=DEFAULT_SPAN_SECONDS,
        scenario="20k_activities",
        seed=0,
        chunk_size=chunk_size,
    )


def build_10k_contribution_spec(
    *,
    contribution_count: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> BenchmarkFixtureSpec:
    """Build the canonical ``10k_contributions`` spec."""

    return BenchmarkFixtureSpec(
        report_date=DEFAULT_REPORT_DATE,
        activity_count=contribution_count,
        day_start_seconds=DEFAULT_DAY_START_SECONDS,
        span_seconds=DEFAULT_SPAN_SECONDS,
        scenario="10k_contributions",
        seed=0,
        chunk_size=chunk_size,
    )


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_DAY_START_SECONDS",
    "DEFAULT_REPORT_DATE",
    "DEFAULT_SPAN_SECONDS",
    "BenchmarkFixtureResult",
    "BenchmarkFixtureSpec",
    "build_10k_contribution_spec",
    "build_20k_activity_spec",
    "build_activity_fixture",
    "build_contribution_fixture",
    "fixture_hash",
    "format_time",
]
