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
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Fixed deterministic fixture parameters — no RNG, so the fixture is
# identical across revisions and runs.  These mirror the historical
# constants in the now-removed inline builders.
DEFAULT_REPORT_DATE = "2026-07-15"
DEFAULT_DAY_START_SECONDS = 9 * 3600   # 09:00:00
DEFAULT_SPAN_SECONDS = 13 * 3600      # 09:00:00 -> 22:00:00
DEFAULT_CHUNK_SIZE = 500

_BUILDER_VERSION = "1.1"
_DISTRIBUTION_VERSION = "realistic-heavy-session-v4"

# Heavy-session marker constants (synthetic, benchmark-only).  The heavy
# session's resource identity key and display name are fixed so both
# baseline and HEAD can identify the heavy session via the public Timeline
# payload without relying on HEAD-private projection fields.
HEAVY_SESSION_MARKER = "BenchHeavySession"
HEAVY_SESSION_RESOURCE_IDENTITY_KEY = "benchmark:heavy-session"
DEFAULT_HEAVY_SESSION_ACTIVITY_COUNT = 80
# Window title includes ``.md`` so ``extract_anchor_file_name`` recognises it
# as an anchor file, making the marker appear in the Timeline payload's
# ``display_description`` for deterministic heavy-session selection.
HEAVY_SESSION_WINDOW_TITLE = HEAVY_SESSION_MARKER + ".md"


@dataclass(frozen=True)
class BenchmarkFixtureSpec:
    """Deterministic parameters for one benchmark fixture build.

    The spec is fully deterministic (no RNG): the same spec produces the
    same rows in the same order on every revision.  ``scenario`` is
    informational; it is recorded in the result so the comparison layer
    can verify the driver actually ran the requested scenario.

    ``heavy_session_activity_count`` controls the explicit heavy session
    in the ``realistic_heavy_day`` scenario.  When 0, no heavy session is
    constructed (used by non-realistic scenarios).
    """

    report_date: str
    activity_count: int
    day_start_seconds: int
    span_seconds: int
    scenario: str
    seed: int = 0
    chunk_size: int = DEFAULT_CHUNK_SIZE
    heavy_session_activity_count: int = 0


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
    planned_session_count: int = 0
    planned_heavy_session_activity_count: int = 0
    heavy_session_marker: str = ""
    heavy_session_app_name: str = ""
    heavy_session_project_kind: str = ""

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
            "planned_session_count": self.planned_session_count,
            "planned_heavy_session_activity_count": (
                self.planned_heavy_session_activity_count
            ),
            "heavy_session_marker": self.heavy_session_marker,
            "heavy_session_app_name": self.heavy_session_app_name,
            "heavy_session_project_kind": self.heavy_session_project_kind,
        }


def fixture_hash(spec: BenchmarkFixtureSpec) -> str:
    """Compute a deterministic SHA-256 hash of the fixture parameters.

    The hash encodes every parameter that affects row identity or row
    count: report date, day start, span, scenario, seed, chunk size,
    heavy-session count, and distribution version.  Both baseline and
    HEAD must produce the same hash, which the comparison layer
    cross-checks.  Changing any parameter changes the hash so silent
    strategy drift between revisions is impossible.
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
            "heavy_session_activity_count": spec.heavy_session_activity_count,
            "builder_version": _BUILDER_VERSION,
            "distribution_version": _DISTRIBUTION_VERSION,
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
    chunk_callback: Callable[[int, int], None] | None = None,
) -> BenchmarkFixtureResult:
    """Insert ``spec.activity_count`` synthetic facts on ``spec.report_date``.

    Distribution mirrors the historical inline builder: continuous uncategorized
    normal activities (majority), multi-project alternation via sparse manual
    anchors, short 10s sessions interleaved with longer ones, sparse context
    anchors so attribution walks neighbours, and one paused standalone status row.

    Connection/transaction contract: one ``get_connection()`` call, commit every
    ``spec.chunk_size`` rows, one final commit for the remainder.

    ``chunk_callback`` (optional, benchmark-only): invoked after every chunk
    commit with ``(chunk_index, inserted_so_far)`` so a driver can persist
    ``fixture_chunk_committed`` checkpoints.  Production callers leave ``None``.
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
    chunk_index = -1

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
                chunk_index += 1
                if chunk_callback is not None:
                    chunk_callback(chunk_index, len(activity_ids))

        # Final commit for any remainder rows.
        conn.commit()
        commit_count += 1
        if chunk_callback is not None and (
            spec.activity_count % spec.chunk_size != 0
        ):
            chunk_index += 1
            chunk_callback(chunk_index, len(activity_ids))

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
    chunk_callback: Callable[[int, int], None] | None = None,
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

    ``chunk_callback`` (optional, benchmark-only): invoked after every
    chunk commit with ``(chunk_index, inserted_so_far)``.
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
    chunk_index = -1

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
                chunk_index += 1
                if chunk_callback is not None:
                    chunk_callback(chunk_index, len(activity_ids))

        conn.commit()
        commit_count += 1
        if chunk_callback is not None and (
            spec.activity_count % spec.chunk_size != 0
        ):
            chunk_index += 1
            chunk_callback(chunk_index, len(activity_ids))

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


# ---------------------------------------------------------------------------
# Realistic heavy-day fixture
# ---------------------------------------------------------------------------

# Synthetic heavy-day load (seeded RNG, fully deterministic).  Target:
# ~2000 activities, ~300 sessions, ~2000 contributions, one explicit
# heavy session of ~80 activities, 13h span (09:00->22:00).

_REALISTIC_APPS = ["IDE", "Browser", "Terminal", "Editor", "Mail", "Docs"]
_REALISTIC_PROCESS_NAMES = {
    "IDE": "ide.exe",
    "Browser": "browser.exe",
    "Terminal": "terminal.exe",
    "Editor": "editor.exe",
    "Mail": "mail.exe",
    "Docs": "docs.exe",
}

# Session merge threshold (seconds).  The fixture sets
# ``unrecorded_gap_boundary_seconds`` to 60 (the builder's min clamp) so
# inter-session gaps of 61-70s correctly split sessions; the production
# default of 900 would merge all planned sessions together.
_SESSION_MERGE_GAP_THRESHOLD = 60

# Conservative average duration per activity (seconds).  Used only for time
# budget estimation in ``_generate_session_plan`` so the plan fits within
# ``span_seconds``.  Actual durations are drawn from ``randint(3, 10)``.
_AVG_ACTIVITY_DURATION_ESTIMATE = 8


@dataclass(frozen=True)
class _PlannedSession:
    """One planned session in the realistic fixture.

    Within a planned session, all grouping fields (app, process, resource
    identity, status, project) are fixed so the session builder merges
    all member activities into exactly one session.  ``is_heavy`` marks
    the explicit heavy session so the builder can use the marker resource.
    """

    length: int
    gap_before: int
    app_name: str
    process_name: str
    status: str
    project_kind: str  # "anchor" | "other" | "uncategorized"
    resource_index: int
    is_heavy: bool = False


def _generate_session_plan(
    rng: random.Random,
    *,
    target_activities: int,
    span_seconds: int,
    heavy_session_activity_count: int,
) -> list[_PlannedSession]:
    """Plan session lengths, gaps, and fixed grouping fields.

    Returns :class:`_PlannedSession` entries with a realistic distribution:
    most sessions short (1-8), few medium (10-30), one explicit heavy
    session (``heavy_session_activity_count``) placed LAST at a stable
    position.  Inter-session gaps (61-70s) exceed the merge threshold so
    sessions never accidentally merge; durations (3-10s) keep 2000
    activities within the 13h span.

    Time budget tracking stops creating new sessions when the remaining
    span is insufficient; remaining activities are dumped into the current
    session so all ``target_activities`` are always placed without
    overflowing the day.  Deterministic given the same RNG and parameters.
    """

    plan: list[_PlannedSession] = []
    if heavy_session_activity_count > 0:
        remaining = target_activities - heavy_session_activity_count
    else:
        remaining = target_activities

    # Reserve time for the heavy session so it is always placed.
    heavy_time = heavy_session_activity_count * _AVG_ACTIVITY_DURATION_ESTIMATE
    heavy_gap = 61 if heavy_session_activity_count > 0 else 0
    available_for_non_heavy = span_seconds - heavy_time - heavy_gap

    consumed_span = 0
    resource_counter = 0

    while remaining > 0:
        # 90% short sessions (1-8), 10% medium sessions (10-30).
        if rng.random() < 0.90:
            length = rng.randint(1, 8)
        else:
            length = rng.randint(10, 30)
        length = min(length, remaining)

        # Gap strictly above merge threshold so sessions don't merge.
        # Keep gaps small (61-70s) to fit within the 13h span.
        gap = rng.randint(61, 70) if plan else 0
        session_time = length * _AVG_ACTIVITY_DURATION_ESTIMATE + gap

        if consumed_span + session_time > available_for_non_heavy:
            # Span is nearly full.  Dump all remaining activities into
            # this session with a minimal gap so all activities fit
            # within the day without reducing the total count.
            length = remaining
            gap = 61 if plan else 0
            session_time = length * _AVG_ACTIVITY_DURATION_ESTIMATE + gap

        consumed_span += session_time

        app_name = rng.choice(_REALISTIC_APPS)
        process_name = _REALISTIC_PROCESS_NAMES[app_name]
        # Status: 75% normal, 10% idle, 10% excluded, 5% paused.
        roll = rng.random()
        if roll < 0.75:
            status = "normal"
        elif roll < 0.85:
            status = "idle"
        elif roll < 0.95:
            status = "excluded"
        else:
            status = "paused"
        # Project: 40% uncategorized, 35% anchor, 25% other.
        proj_roll = rng.random()
        if proj_roll < 0.40:
            project_kind = "uncategorized"
        elif proj_roll < 0.75:
            project_kind = "anchor"
        else:
            project_kind = "other"
        if status == "paused":
            project_kind = "uncategorized"

        plan.append(_PlannedSession(
            length=length,
            gap_before=gap,
            app_name=app_name,
            process_name=process_name,
            status=status,
            project_kind=project_kind,
            resource_index=resource_counter,
            is_heavy=False,
        ))
        resource_counter += 1
        remaining -= length

    # Append the explicit heavy session LAST.
    if heavy_session_activity_count > 0:
        gap = rng.randint(61, 70) if plan else 0
        plan.append(_PlannedSession(
            length=heavy_session_activity_count,
            gap_before=gap,
            app_name=HEAVY_SESSION_MARKER,
            process_name="bench.exe",
            status="normal",
            project_kind="anchor",
            resource_index=resource_counter,
            is_heavy=True,
        ))

    return plan


def _build_heavy_session_resource() -> Any:
    """Build the fixed synthetic resource for the heavy session.

    All activities in the heavy session share this single resource so
    the session is stable and identifiable via the marker.  The
    ``app_name`` is set to ``HEAVY_SESSION_MARKER`` so the Timeline
    entry's ``display_description`` (derived from ``_contribution_label``
    which falls back to ``app_name``) contains the marker for
    deterministic selection by the WebView harness.
    """

    from worktrace.resources.types import DetectedResource

    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=HEAVY_SESSION_MARKER,
        identity_key=HEAVY_SESSION_RESOURCE_IDENTITY_KEY,
        is_anchor=True,
        confidence=80,
        source="auto",
        app_name=HEAVY_SESSION_MARKER,
        process_name="bench.exe",
        window_title=HEAVY_SESSION_WINDOW_TITLE,
        path_hint="D:\\Bench\\BenchHeavySession.txt",
        path_key="path:bench:heavy-session",
        uri_scheme="",
        uri_host="",
        uri_hint="",
        metadata_json="",
    )


def _build_session_resource(index: int, app_name: str, process_name: str) -> Any:
    """Build a synthetic resource fixed for one planned session.

    All activities within a planned session share this resource so the
    session builder does not split them.  Different sessions use
    different resources so they remain distinct.
    """

    from worktrace.resources.types import DetectedResource

    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=f"Doc{index}",
        identity_key=f"resource:doc:{index}",
        is_anchor=(index % 17 == 0),
        confidence=80,
        source="auto",
        app_name=app_name,
        process_name=process_name,
        window_title=f"Doc{index}",
        path_hint=f"D:\\Bench\\Doc{index}.txt",
        path_key=f"path:doc:{index}",
        uri_scheme="",
        uri_host="",
        uri_hint="",
        metadata_json="",
    )


def build_realistic_heavy_day_fixture(
    *,
    spec: BenchmarkFixtureSpec,
    chunk_callback: Callable[[int, int], None] | None = None,
) -> BenchmarkFixtureResult:
    """Insert a realistic heavy-day workload on ``spec.report_date``.

    Distribution: ~300 sessions (most short, few medium); one explicit
    heavy session (default 80 activities) with a fixed marker resource;
    ~2000 activities with 3-20s durations; 6 app/resource identities;
    normal (~75%), idle (~10%), excluded (~10%), paused (~5%); ~40%
    uncategorized, ~35% anchor, ~25% other project.  Inter-session gaps
    exceed the merge threshold; within each session all grouping fields
    are fixed so the builder merges members into exactly one session.
    Deterministic seeded RNG (``spec.seed``).

    All activities are closed; ``paused`` is a classification, not an
    open-state (``uq_activity_log_single_open`` prohibits concurrent opens).
    """

    from worktrace.constants import (
        SOURCE_AUTO,
        STATUS_EXCLUDED,
        STATUS_IDLE,
        STATUS_NORMAL,
        STATUS_PAUSED,
    )
    from worktrace.db import get_connection, now_str
    from worktrace.services import activity_fact_repository
    from worktrace.services.report_fact_query_service import (
        get_uncategorized_project_id,
    )

    if spec.activity_count < 1:
        raise ValueError("activity_count must be >= 1")

    heavy_count = spec.heavy_session_activity_count
    rng = random.Random(spec.seed)
    session_plan = _generate_session_plan(
        rng,
        target_activities=spec.activity_count,
        span_seconds=spec.span_seconds,
        heavy_session_activity_count=heavy_count,
    )

    _STATUS_MAP = {
        "normal": STATUS_NORMAL,
        "idle": STATUS_IDLE,
        "excluded": STATUS_EXCLUDED,
        "paused": STATUS_PAUSED,
    }

    activity_ids: list[int] = []
    started = time.perf_counter()
    connection_count = 0
    commit_count = 0
    preexisting_activity_count = 0
    uncategorized_id = 0
    chunk_index = -1
    heavy_session_app_name = ""
    heavy_session_project_kind = ""

    with get_connection() as conn:
        connection_count += 1
        activity_fact_repository.close_all_open_activities(conn, now_str())
        preexisting_activity_count = _count_existing_activities(
            conn, spec.report_date
        )
        uncategorized_id = get_uncategorized_project_id(conn)
        projects = _ensure_benchmark_projects(conn)
        anchor_project = projects["anchor"]
        other_project = projects["other"]

        # Override the session merge threshold to 60s (the builder's min
        # clamp) so 61-120s inter-session gaps split planned sessions.
        # Benchmark-only override on the temp DB; production default (900s)
        # would merge all sessions into one.
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                "unrecorded_gap_boundary_seconds",
                str(_SESSION_MERGE_GAP_THRESHOLD),
                now_str(),
            ),
        )
        conn.commit()

        current_offset = spec.day_start_seconds

        for session_idx, planned in enumerate(session_plan):
            current_offset += planned.gap_before

            # Pick the project ID for this session (fixed for all members).
            if planned.project_kind == "anchor":
                project_id: int | None = anchor_project
            elif planned.project_kind == "other":
                project_id = other_project
            else:
                project_id = None

            # Paused activities are standalone (no project).
            if planned.status == "paused":
                project_id = None

            # Build ONE fixed resource for the entire session.
            if planned.is_heavy:
                resource = _build_heavy_session_resource()
                heavy_session_app_name = planned.app_name
                heavy_session_project_kind = planned.project_kind
            else:
                resource = _build_session_resource(
                    planned.resource_index,
                    planned.app_name,
                    planned.process_name,
                )

            status_const = _STATUS_MAP[planned.status]
            max_offset = spec.day_start_seconds + spec.span_seconds

            for _ in range(planned.length):
                if len(activity_ids) >= spec.activity_count:
                    break

                # Activity duration: 3-10s.  Kept short so 2000 activities
                # fit within the 13h span alongside inter-session gaps.
                duration = rng.randint(3, 10)

                start_offset = current_offset
                end_offset = start_offset + duration

                # Clamp to span.
                if end_offset > max_offset:
                    end_offset = max_offset
                    if start_offset >= max_offset:
                        break

                start_time = format_time(spec.report_date, start_offset)
                end_time = format_time(spec.report_date, end_offset)

                window_title = (
                    HEAVY_SESSION_WINDOW_TITLE if planned.is_heavy
                    else f"Doc{planned.resource_index}"
                )

                prepared = _prepare_activity(
                    app_name=planned.app_name,
                    process_name=planned.process_name,
                    window_title=window_title,
                    start_time=start_time,
                    status=status_const,
                    source=SOURCE_AUTO,
                    project_id=project_id,
                    resource=resource,
                )
                activity_id = activity_fact_repository.insert_open_activity(
                    conn, prepared
                )
                # All activities are closed regardless of status — the
                # uq_activity_log_single_open index allows only ONE open
                # activity globally, and this is a historical fixture.
                activity_fact_repository.close_activity(
                    conn, activity_id, end_time
                )
                activity_ids.append(activity_id)

                current_offset = end_offset

                # Chunk commit strategy.
                if len(activity_ids) % spec.chunk_size == 0:
                    conn.commit()
                    commit_count += 1
                    chunk_index += 1
                    if chunk_callback is not None:
                        chunk_callback(chunk_index, len(activity_ids))

        # Final commit for remainder.
        conn.commit()
        commit_count += 1
        if chunk_callback is not None and (
            len(activity_ids) % spec.chunk_size != 0
        ):
            chunk_index += 1
            chunk_callback(chunk_index, len(activity_ids))

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
        planned_session_count=len(session_plan),
        planned_heavy_session_activity_count=heavy_count,
        heavy_session_marker=HEAVY_SESSION_MARKER if heavy_count > 0 else "",
        heavy_session_app_name=heavy_session_app_name,
        heavy_session_project_kind=heavy_session_project_kind,
    )


def build_realistic_heavy_day_spec(
    *,
    activity_count: int = 2000,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    heavy_session_activity_count: int = DEFAULT_HEAVY_SESSION_ACTIVITY_COUNT,
) -> BenchmarkFixtureSpec:
    """Build the canonical ``realistic_heavy_day`` spec.

    Uses a fixed seed (42) so baseline and HEAD produce identical fixtures.
    The seed is encoded in the fixture hash, so any change invalidates
    cross-revision comparisons.  ``heavy_session_activity_count`` is also
    encoded in the hash so a change to the heavy session size invalidates
    cross-revision comparisons.
    """

    return BenchmarkFixtureSpec(
        report_date=DEFAULT_REPORT_DATE,
        activity_count=activity_count,
        day_start_seconds=DEFAULT_DAY_START_SECONDS,
        span_seconds=DEFAULT_SPAN_SECONDS,
        scenario="realistic_heavy_day",
        seed=42,
        chunk_size=chunk_size,
        heavy_session_activity_count=heavy_session_activity_count,
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
    "build_realistic_heavy_day_fixture",
    "build_realistic_heavy_day_spec",
    "fixture_hash",
    "format_time",
]
