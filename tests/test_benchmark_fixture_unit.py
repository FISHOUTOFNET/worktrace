"""Unit and integration tests for the shared HEAD-owned benchmark fixture builder.

Covers the connection/transaction contract, scenario isolation, fixture hash
stability, and the sharing contract between product and WebView drivers.

The fixture builder lives in ``scripts/ci/benchmark_fixture.py`` and is
imported by both ``scripts/ci/product_benchmark_driver.py`` and
``scripts/webview_render_perf.py`` so both drivers construct identical
synthetic datasets with identical connection/transaction semantics.

Connection / transaction contract
--------------------------------
Each ``build_*`` function must:
  * acquire the connection O(1) times (one ``get_connection()`` call),
  * commit in fixed-size chunks of ``chunk_size`` rows,
  * never open a per-activity connection,
  * never commit per activity,
  * record the actual ``connection_count`` and ``commit_count`` in the
    returned ``BenchmarkFixtureResult``.

These tests verify the contract by monkeypatching ``get_connection`` with
a counting wrapper and asserting the counts are bounded by constants, not
by the activity count N.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.db, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "scripts" / "ci" / "benchmark_fixture.py"


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fixture_module():
    """Load scripts/ci/benchmark_fixture.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "benchmark_fixture_under_test", FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_fixture_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("benchmark_fixture_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Spec and hash tests (pure functions, no DB needed)
# ---------------------------------------------------------------------------

class TestFixtureSpec:
    """Tests for the BenchmarkFixtureSpec dataclass and hash stability."""

    def test_spec_is_frozen(self, fixture_module) -> None:
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
        )
        with pytest.raises(Exception):
            spec.activity_count = 999  # type: ignore[misc]

    def test_spec_default_chunk_size(self, fixture_module) -> None:
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
        )
        assert spec.chunk_size == fixture_module.DEFAULT_CHUNK_SIZE
        assert spec.seed == 0

    def test_fixture_hash_is_deterministic(self, fixture_module) -> None:
        """The same spec must always produce the same hash."""
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=20000,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="20k_activities",
        )
        h1 = fixture_module.fixture_hash(spec)
        h2 = fixture_module.fixture_hash(spec)
        assert h1 == h2

    def test_fixture_hash_is_sha256_hex(self, fixture_module) -> None:
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
        )
        h = fixture_module.fixture_hash(spec)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_fixture_hash_changes_with_activity_count(self, fixture_module) -> None:
        """Different activity counts must produce different hashes so
        smoke (200) and full (20000) fixtures cannot be confused."""
        spec_a = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
        )
        spec_b = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=20000,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
        )
        assert fixture_module.fixture_hash(spec_a) != fixture_module.fixture_hash(spec_b)

    def test_fixture_hash_changes_with_chunk_size(self, fixture_module) -> None:
        """Different chunk sizes must produce different hashes so silent
        strategy drift between revisions is impossible."""
        spec_a = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
            chunk_size=500,
        )
        spec_b = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
            chunk_size=1000,
        )
        assert fixture_module.fixture_hash(spec_a) != fixture_module.fixture_hash(spec_b)

    def test_fixture_hash_changes_with_scenario(self, fixture_module) -> None:
        spec_a = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="20k_activities",
        )
        spec_b = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="10k_contributions",
        )
        assert fixture_module.fixture_hash(spec_a) != fixture_module.fixture_hash(spec_b)

    def test_build_20k_activity_spec_uses_canonical_constants(
        self, fixture_module
    ) -> None:
        spec = fixture_module.build_20k_activity_spec(activity_count=20000)
        assert spec.scenario == "20k_activities"
        assert spec.report_date == fixture_module.DEFAULT_REPORT_DATE
        assert spec.day_start_seconds == fixture_module.DEFAULT_DAY_START_SECONDS
        assert spec.span_seconds == fixture_module.DEFAULT_SPAN_SECONDS
        assert spec.activity_count == 20000

    def test_build_10k_contribution_spec_uses_canonical_constants(
        self, fixture_module
    ) -> None:
        spec = fixture_module.build_10k_contribution_spec(contribution_count=10000)
        assert spec.scenario == "10k_contributions"
        assert spec.report_date == fixture_module.DEFAULT_REPORT_DATE
        assert spec.day_start_seconds == fixture_module.DEFAULT_DAY_START_SECONDS
        assert spec.span_seconds == fixture_module.DEFAULT_SPAN_SECONDS
        assert spec.activity_count == 10000


# ---------------------------------------------------------------------------
# Audit dict tests (pure function, no DB needed)
# ---------------------------------------------------------------------------

class TestAuditDict:
    """Tests for BenchmarkFixtureResult.to_audit_dict()."""

    def test_audit_dict_omits_activity_ids(self, fixture_module) -> None:
        """activity_ids can be huge and are not needed by the comparison
        layer, so they must be omitted from the audit dict."""
        result = fixture_module.BenchmarkFixtureResult(
            report_date="2026-07-15",
            scenario="test",
            requested_count=10,
            inserted_count=10,
            preexisting_activity_count=0,
            activity_ids=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        )
        audit = result.to_audit_dict()
        assert "activity_ids" not in audit

    def test_audit_dict_includes_contract_fields(self, fixture_module) -> None:
        result = fixture_module.BenchmarkFixtureResult(
            report_date="2026-07-15",
            scenario="test",
            requested_count=10,
            inserted_count=10,
            preexisting_activity_count=0,
            connection_count=1,
            commit_count=3,
            chunk_size=500,
        )
        audit = result.to_audit_dict()
        assert audit["scenario"] == "test"
        assert audit["requested_count"] == 10
        assert audit["inserted_count"] == 10
        assert audit["preexisting_activity_count"] == 0
        assert audit["connection_count"] == 1
        assert audit["commit_count"] == 3
        assert audit["chunk_size"] == 500
        assert "fixture_build_seconds" in audit
        assert "builder_version" in audit
        assert "report_date" in audit


# ---------------------------------------------------------------------------
# Connection / transaction contract (integration with real DB)
# ---------------------------------------------------------------------------

class TestConnectionTransactionContract:
    """Integration tests verifying the O(1) connection and O(N/chunk)
    commit contract using a real isolated temp database.

    These tests monkeypatch ``worktrace.db.get_connection`` with a counting
    wrapper so the actual call count is verified, not just the recorded
    value.
    """

    def test_activity_fixture_uses_o1_connections(
        self, fixture_module, temp_db, monkeypatch
    ) -> None:
        """build_activity_fixture must call get_connection exactly once
        regardless of activity_count — O(1), not O(N)."""
        import worktrace.db as db_module

        original_get_connection = db_module.get_connection
        call_count = {"value": 0}

        def counting_get_connection(*args, **kwargs):
            call_count["value"] += 1
            return original_get_connection(*args, **kwargs)

        monkeypatch.setattr(db_module, "get_connection", counting_get_connection)

        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=50,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test_o1_connections",
            chunk_size=500,
        )
        result = fixture_module.build_activity_fixture(spec=spec)

        # The contract: exactly 1 get_connection call, not N.
        assert call_count["value"] == 1, (
            f"build_activity_fixture called get_connection "
            f"{call_count['value']} times for {spec.activity_count} activities; "
            f"expected exactly 1 (O(1) contract)"
        )
        assert result.connection_count == 1

    def test_contribution_fixture_uses_o1_connections(
        self, fixture_module, temp_db, monkeypatch
    ) -> None:
        """build_contribution_fixture must call get_connection exactly once
        regardless of activity_count — O(1), not O(N)."""
        import worktrace.db as db_module

        original_get_connection = db_module.get_connection
        call_count = {"value": 0}

        def counting_get_connection(*args, **kwargs):
            call_count["value"] += 1
            return original_get_connection(*args, **kwargs)

        monkeypatch.setattr(db_module, "get_connection", counting_get_connection)

        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=50,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test_o1_connections_contrib",
            chunk_size=500,
        )
        result = fixture_module.build_contribution_fixture(spec=spec)

        assert call_count["value"] == 1, (
            f"build_contribution_fixture called get_connection "
            f"{call_count['value']} times for {spec.activity_count} activities; "
            f"expected exactly 1 (O(1) contract)"
        )
        assert result.connection_count == 1

    def test_activity_fixture_commit_count_bounded(
        self, fixture_module, temp_db, monkeypatch
    ) -> None:
        """commit_count must be bounded by ceil(N / chunk_size) + 1
        (one per chunk + one final commit for the remainder)."""
        import worktrace.db as db_module

        original_get_connection = db_module.get_connection
        commit_count = {"value": 0}

        def counting_get_connection(*args, **kwargs):
            conn = original_get_connection(*args, **kwargs)
            original_commit = conn.commit

            def counting_commit():
                commit_count["value"] += 1
                return original_commit()

            conn.commit = counting_commit  # type: ignore[method-assign]
            return conn

        monkeypatch.setattr(db_module, "get_connection", counting_get_connection)

        chunk_size = 10
        activity_count = 55
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=activity_count,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test_commit_bounds",
            chunk_size=chunk_size,
        )
        result = fixture_module.build_activity_fixture(spec=spec)

        expected_max_commits = math.ceil(activity_count / chunk_size) + 1
        assert result.commit_count <= expected_max_commits, (
            f"commit_count={result.commit_count} exceeds expected max "
            f"{expected_max_commits} (ceil({activity_count}/{chunk_size})+1)"
        )
        assert result.commit_count >= 1
        # The monkeypatched counter should match the recorded count.
        assert commit_count["value"] == result.commit_count

    def test_no_per_activity_connection_in_activity_fixture(
        self, fixture_module, temp_db, monkeypatch
    ) -> None:
        """The activity fixture source must not call get_connection inside
        the per-activity loop.  Verified by monkeypatch + count: the count
        must be 1 even for 100 activities."""
        import worktrace.db as db_module

        original_get_connection = db_module.get_connection
        call_count = {"value": 0}

        def counting_get_connection(*args, **kwargs):
            call_count["value"] += 1
            return original_get_connection(*args, **kwargs)

        monkeypatch.setattr(db_module, "get_connection", counting_get_connection)

        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=100,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test_no_per_activity",
            chunk_size=500,
        )
        fixture_module.build_activity_fixture(spec=spec)

        assert call_count["value"] == 1, (
            f"get_connection was called {call_count['value']} times for "
            f"100 activities — the builder is opening per-activity connections "
            f"(O(N) violation)"
        )


# ---------------------------------------------------------------------------
# Scenario isolation contract (integration with real DB)
# ---------------------------------------------------------------------------

class TestScenarioIsolation:
    """Integration tests verifying scenario isolation via the
    preexisting_activity_count contract."""

    def test_activity_fixture_reports_zero_preexisting_on_clean_db(
        self, fixture_module, temp_db
    ) -> None:
        """On a fresh database, preexisting_activity_count must be 0."""
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=20,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="isolation_clean",
            chunk_size=500,
        )
        result = fixture_module.build_activity_fixture(spec=spec)
        assert result.preexisting_activity_count == 0
        assert result.inserted_count == spec.activity_count
        assert result.requested_count == spec.activity_count

    def test_contribution_fixture_reports_zero_preexisting_on_clean_db(
        self, fixture_module, temp_db
    ) -> None:
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=20,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="isolation_clean_contrib",
            chunk_size=500,
        )
        result = fixture_module.build_contribution_fixture(spec=spec)
        assert result.preexisting_activity_count == 0
        assert result.inserted_count == spec.activity_count

    def test_activity_fixture_detects_preexisting_on_same_date(
        self, fixture_module, temp_db
    ) -> None:
        """If activities already exist on the report_date, the builder
        must report a non-zero preexisting_activity_count so the driver
        can fail-closed on scenario isolation violation."""
        spec_first = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=10,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="first_run",
            chunk_size=500,
        )
        fixture_module.build_activity_fixture(spec=spec_first)

        spec_second = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=10,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="second_run_same_date",
            chunk_size=500,
        )
        result = fixture_module.build_activity_fixture(spec=spec_second)
        assert result.preexisting_activity_count == 10, (
            f"expected 10 preexisting activities from first run, got "
            f"{result.preexisting_activity_count}"
        )

    def test_activity_fixture_ignores_preexisting_on_different_date(
        self, fixture_module, temp_db
    ) -> None:
        """preexisting_activity_count is scoped to the report date so a
        prior scenario on a different date does not pollute the count."""
        spec_first = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-14",
            activity_count=10,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="first_run_different_date",
            chunk_size=500,
        )
        fixture_module.build_activity_fixture(spec=spec_first)

        spec_second = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=10,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="second_run_new_date",
            chunk_size=500,
        )
        result = fixture_module.build_activity_fixture(spec=spec_second)
        assert result.preexisting_activity_count == 0

    def test_inserted_count_equals_requested_count(
        self, fixture_module, temp_db
    ) -> None:
        """The builder must insert exactly the requested number of activities."""
        for count in (1, 5, 25, 100):
            spec = fixture_module.BenchmarkFixtureSpec(
                report_date=f"2026-07-{15 + count % 10}",
                activity_count=count,
                day_start_seconds=32400,
                span_seconds=46800,
                scenario=f"count_test_{count}",
                chunk_size=10,
            )
            result = fixture_module.build_activity_fixture(spec=spec)
            assert result.inserted_count == count, (
                f"requested {count} activities but inserted "
                f"{result.inserted_count}"
            )
            assert result.requested_count == count


# ---------------------------------------------------------------------------
# Sharing contract between product and WebView drivers
# ---------------------------------------------------------------------------

class TestSharedBuilderContract:
    """Verify that product and WebView drivers use the same fixture builder
    module, eliminating the duplicate inline builders."""

    def test_product_driver_imports_shared_fixture_module(self) -> None:
        """product_benchmark_driver.py must import from
        scripts.ci.benchmark_fixture, not define its own inline builder."""
        driver_path = ROOT / "scripts" / "ci" / "product_benchmark_driver.py"
        source = driver_path.read_text(encoding="utf-8")
        assert "from scripts.ci.benchmark_fixture import" in source
        assert "build_activity_fixture" in source
        assert "build_contribution_fixture" in source

    def test_webview_driver_imports_shared_fixture_module(self) -> None:
        """webview_render_perf.py must import from
        scripts.ci.benchmark_fixture, not define its own inline builder."""
        driver_path = ROOT / "scripts" / "webview_render_perf.py"
        source = driver_path.read_text(encoding="utf-8")
        assert "from scripts.ci.benchmark_fixture import" in source
        assert "build_activity_fixture" in source

    def test_neither_driver_defines_inline_build_activity_loop(self) -> None:
        """Neither driver should contain a duplicate inline fixture
        construction loop that calls insert_open_activity directly."""
        for driver_rel in (
            "scripts/ci/product_benchmark_driver.py",
            "scripts/webview_render_perf.py",
        ):
            source = (ROOT / driver_rel).read_text(encoding="utf-8")
            # The drivers may call insert_open_activity only via the shared
            # builder, not their own inline loops; assert no local definition.
            assert "def build_activity_fixture" not in source, (
                f"{driver_rel} defines its own build_activity_fixture — "
                f"should use the shared scripts.ci.benchmark_fixture module"
            )
            assert "def build_contribution_fixture" not in source, (
                f"{driver_rel} defines its own build_contribution_fixture — "
                f"should use the shared scripts.ci.benchmark_fixture module"
            )

    def test_shared_module_is_the_single_source_of_fixture_construction(
        self, fixture_module
    ) -> None:
        """benchmark_fixture.py must export the canonical builder functions."""
        assert hasattr(fixture_module, "build_activity_fixture")
        assert hasattr(fixture_module, "build_contribution_fixture")
        assert hasattr(fixture_module, "BenchmarkFixtureSpec")
        assert hasattr(fixture_module, "BenchmarkFixtureResult")
        assert hasattr(fixture_module, "fixture_hash")
        assert callable(fixture_module.build_activity_fixture)
        assert callable(fixture_module.build_contribution_fixture)


# ---------------------------------------------------------------------------
# Chunk strategy contract
# ---------------------------------------------------------------------------

class TestChunkStrategy:
    """Verify the chunk strategy is fixed and identical across revisions."""

    def test_default_chunk_size_is_fixed(self, fixture_module) -> None:
        """DEFAULT_CHUNK_SIZE must be a positive integer constant."""
        assert isinstance(fixture_module.DEFAULT_CHUNK_SIZE, int)
        assert fixture_module.DEFAULT_CHUNK_SIZE > 0

    def test_chunk_size_recorded_in_result(self, fixture_module, temp_db) -> None:
        """The result must record the chunk_size used so the comparison
        layer can verify baseline and HEAD used the same strategy."""
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=10,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="chunk_record",
            chunk_size=3,
        )
        result = fixture_module.build_activity_fixture(spec=spec)
        assert result.chunk_size == 3
        audit = result.to_audit_dict()
        assert audit["chunk_size"] == 3

    def test_chunk_size_in_fixture_hash(self, fixture_module) -> None:
        """chunk_size must be encoded in the fixture hash so changing it
        invalidates cross-revision comparisons."""
        spec_a = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
            chunk_size=500,
        )
        spec_b = fixture_module.BenchmarkFixtureSpec(
            report_date="2026-07-15",
            activity_count=200,
            day_start_seconds=32400,
            span_seconds=46800,
            scenario="test",
            chunk_size=1000,
        )
        assert fixture_module.fixture_hash(spec_a) != fixture_module.fixture_hash(spec_b)


# ---------------------------------------------------------------------------
# Realistic heavy-day fixture tests
# ---------------------------------------------------------------------------

class TestRealisticHeavyDayFixture:
    """Tests for the realistic heavy-day fixture's heavy session contract.

    Verifies that the explicit heavy session:
      * has the planned activity count (80 by default),
      * fixes all grouping fields (app, process, resource, status, project)
        so the session builder merges member activities into one session,
      * has contiguous activity times with no session-merge-threshold gaps,
      * is bounded by clear session boundaries (gap > threshold before/after),
      * is recorded in the fixture hash and audit metadata,
      * produces deterministic output for the same seed/spec.
    """

    def test_realistic_fixture_total_activity_count(
        self, fixture_module, temp_db
    ) -> None:
        """The realistic fixture must insert exactly 2000 activities."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        assert result.inserted_count == 2000, (
            f"expected 2000 activities, got {result.inserted_count}"
        )
        assert result.requested_count == 2000

    def test_realistic_fixture_heavy_session_planned_count(
        self, fixture_module, temp_db
    ) -> None:
        """The audit must record the planned heavy session activity count."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        assert result.planned_heavy_session_activity_count == 80
        audit = result.to_audit_dict()
        assert audit["planned_heavy_session_activity_count"] == 80

    def test_realistic_fixture_heavy_session_marker_recorded(
        self, fixture_module, temp_db
    ) -> None:
        """The audit must record the heavy session marker and app name."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        assert result.heavy_session_marker == fixture_module.HEAVY_SESSION_MARKER
        assert result.heavy_session_app_name == fixture_module.HEAVY_SESSION_MARKER
        assert result.heavy_session_project_kind == "anchor"
        audit = result.to_audit_dict()
        assert audit["heavy_session_marker"] == fixture_module.HEAVY_SESSION_MARKER
        assert audit["heavy_session_app_name"] == fixture_module.HEAVY_SESSION_MARKER

    def test_realistic_fixture_planned_session_count_recorded(
        self, fixture_module, temp_db
    ) -> None:
        """The audit must record the total planned session count."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        assert result.planned_session_count > 0
        audit = result.to_audit_dict()
        assert audit["planned_session_count"] == result.planned_session_count

    def test_heavy_session_hash_includes_heavy_count(
        self, fixture_module
    ) -> None:
        """The fixture hash must change when heavy_session_activity_count
        changes, so silent drift between revisions is impossible."""
        spec_a = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=80,
        )
        spec_b = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=50,
        )
        assert fixture_module.fixture_hash(spec_a) != fixture_module.fixture_hash(
            spec_b
        ), (
            "fixture hash must change when heavy_session_activity_count changes"
        )

    def test_realistic_fixture_deterministic_same_seed(
        self, fixture_module, temp_db
    ) -> None:
        """The same spec must produce identical activity IDs across runs."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=500,  # smaller for test speed
            heavy_session_activity_count=80,
        )
        result1 = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        # Wipe and rebuild to verify determinism.  Child tables
        # (activity_resource, activity_project_assignment) reference
        # activity_log via FK, so they must be deleted first.  The
        # sqlite_sequence must also be reset so autoincrement IDs match.
        import worktrace.db as db_module
        with db_module.get_connection() as conn:
            conn.execute("DELETE FROM activity_resource")
            conn.execute("DELETE FROM activity_project_assignment")
            conn.execute("DELETE FROM activity_log")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('activity_log', 'activity_resource', "
                "'activity_project_assignment')"
            )
            conn.commit()
        result2 = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        assert result1.activity_ids == result2.activity_ids, (
            "same spec must produce identical activity_ids (deterministic)"
        )
        assert result1.inserted_count == result2.inserted_count

    def test_heavy_session_grouping_fields_fixed(
        self, fixture_module, temp_db
    ) -> None:
        """All activities in the heavy session must share the same
        app_name, process_name, resource identity_key, status, and
        project_id so the session builder does not split them."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=500,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)

        import worktrace.db as db_module
        with db_module.get_connection() as conn:
            # The heavy session uses the marker window_title.  Resource
            # and project data live in activity_resource and
            # activity_project_assignment, not activity_log directly.
            rows = conn.execute(
                """
                SELECT al.app_name, al.process_name, al.status,
                       apa.project_id,
                       ar.identity_key AS resource_identity_key,
                       ar.display_name AS resource_display_name,
                       ar.path_key AS resource_path_key,
                       al.start_time, al.end_time
                FROM activity_log al
                LEFT JOIN activity_resource ar
                    ON ar.activity_id = al.id
                LEFT JOIN activity_project_assignment apa
                    ON apa.activity_id = al.id
                WHERE al.window_title = ?
                ORDER BY al.start_time
                """,
                (fixture_module.HEAVY_SESSION_WINDOW_TITLE,),
            ).fetchall()

        assert len(rows) == 80, (
            f"expected 80 heavy session activities, got {len(rows)}"
        )

        # All rows must share the same grouping fields.
        first = rows[0]
        for i, row in enumerate(rows):
            assert row["app_name"] == first["app_name"], (
                f"heavy session activity {i}: app_name mismatch "
                f"({row['app_name']} != {first['app_name']})"
            )
            assert row["process_name"] == first["process_name"], (
                f"heavy session activity {i}: process_name mismatch"
            )
            assert row["status"] == first["status"], (
                f"heavy session activity {i}: status mismatch"
            )
            assert row["project_id"] == first["project_id"], (
                f"heavy session activity {i}: project_id mismatch"
            )
            assert row["resource_identity_key"] == first["resource_identity_key"], (
                f"heavy session activity {i}: resource_identity_key mismatch"
            )
            assert row["resource_display_name"] == first["resource_display_name"], (
                f"heavy session activity {i}: resource_display_name mismatch"
            )
            assert row["resource_path_key"] == first["resource_path_key"], (
                f"heavy session activity {i}: resource_path_key mismatch"
            )

        # The heavy session must use the marker identity key.
        assert first["resource_identity_key"] == (
            fixture_module.HEAVY_SESSION_RESOURCE_IDENTITY_KEY
        )
        assert first["resource_display_name"] == fixture_module.HEAVY_SESSION_MARKER
        # Heavy session must use normal status.
        assert first["status"] == "normal"

    def test_heavy_session_times_contiguous(
        self, fixture_module, temp_db
    ) -> None:
        """Heavy session activities must have contiguous times with no
        gap exceeding the session merge threshold (60s).

        Each activity's start_time must equal or follow the previous
        activity's end_time, and the gap between end_time and the next
        start_time must be <= 60 seconds (the merge threshold).
        """
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=500,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)

        import worktrace.db as db_module
        from datetime import datetime

        with db_module.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT start_time, end_time
                FROM activity_log
                WHERE window_title = ?
                ORDER BY start_time
                """,
                (fixture_module.HEAVY_SESSION_WINDOW_TITLE,),
            ).fetchall()

        assert len(rows) == 80
        fmt = "%Y-%m-%d %H:%M:%S"
        prev_end = datetime.strptime(rows[0]["end_time"], fmt)
        for i in range(1, len(rows)):
            start = datetime.strptime(rows[i]["start_time"], fmt)
            end = datetime.strptime(rows[i]["end_time"], fmt)
            # start must be >= prev_end (no overlap/stacking).
            assert start >= prev_end, (
                f"heavy session activity {i}: start_time {start} < "
                f"prev end_time {prev_end} (stacked or out of order)"
            )
            # Gap between prev_end and start must be <= 60s (merge threshold).
            gap = (start - prev_end).total_seconds()
            assert gap <= 60, (
                f"heavy session activity {i}: gap {gap}s > 60s merge threshold "
                f"— session would split"
            )
            # start must be strictly after prev_start (no duplicate start
            # timestamps).  Back-to-back (start == prev_end) is valid and
            # does not constitute stacking.
            prev_start = datetime.strptime(rows[i - 1]["start_time"], fmt)
            assert start > prev_start, (
                f"heavy session activity {i}: start_time {start} <= "
                f"prev start_time {prev_start} (duplicate or reversed start)"
            )
            prev_end = end

    def test_heavy_session_boundary_before(
        self, fixture_module, temp_db
    ) -> None:
        """The gap between the heavy session and the previous session must
        exceed the merge threshold (60s) so they don't accidentally merge."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=500,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)

        import worktrace.db as db_module
        from datetime import datetime

        with db_module.get_connection() as conn:
            # Get the heavy session's first activity.
            heavy_first = conn.execute(
                """
                SELECT start_time
                FROM activity_log
                WHERE window_title = ?
                ORDER BY start_time
                LIMIT 1
                """,
                (fixture_module.HEAVY_SESSION_WINDOW_TITLE,),
            ).fetchone()
            assert heavy_first is not None
            heavy_start = datetime.strptime(heavy_first["start_time"], "%Y-%m-%d %H:%M:%S")

            # Get the activity immediately before the heavy session.
            prev = conn.execute(
                """
                SELECT end_time
                FROM activity_log
                WHERE window_title != ?
                  AND end_time <= ?
                ORDER BY end_time DESC
                LIMIT 1
                """,
                (
                    fixture_module.HEAVY_SESSION_WINDOW_TITLE,
                    heavy_first["start_time"],
                ),
            ).fetchone()

        if prev is not None:
            prev_end = datetime.strptime(prev["end_time"], "%Y-%m-%d %H:%M:%S")
            gap = (heavy_start - prev_end).total_seconds()
            assert gap > 60, (
                f"gap before heavy session = {gap}s <= 60s merge threshold "
                f"— sessions would merge"
            )

    def test_heavy_session_no_time_crosses_day(
        self, fixture_module, temp_db
    ) -> None:
        """All heavy session activities must be on the same report date
        (no crossing midnight)."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=2000,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)

        import worktrace.db as db_module
        with db_module.get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT DATE(start_time) as d FROM activity_log "
                "WHERE window_title = ?",
                (fixture_module.HEAVY_SESSION_WINDOW_TITLE,),
            ).fetchall()

        assert len(rows) == 1, (
            f"heavy session spans {len(rows)} dates; expected 1 "
            f"(no crossing midnight)"
        )
        assert rows[0]["d"] == spec.report_date

    def test_heavy_session_no_stacked_or_reversed_times(
        self, fixture_module, temp_db
    ) -> None:
        """All activities in the fixture (not just heavy session) must
        have monotonically non-decreasing start times — no stacking or
        reversed timestamps."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=500,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)

        import worktrace.db as db_module
        with db_module.get_connection() as conn:
            rows = conn.execute(
                "SELECT start_time FROM activity_log ORDER BY start_time"
            ).fetchall()

        # All start_times must be strictly increasing (no duplicates).
        start_times = [r["start_time"] for r in rows]
        for i in range(1, len(start_times)):
            assert start_times[i] > start_times[i - 1], (
                f"activity {i}: start_time {start_times[i]} <= "
                f"prev {start_times[i-1]} (stacked or reversed)"
            )

    def test_audit_includes_planned_heavy_metadata(
        self, fixture_module, temp_db
    ) -> None:
        """The audit dict must include all heavy session metadata fields."""
        spec = fixture_module.build_realistic_heavy_day_spec(
            activity_count=500,
            heavy_session_activity_count=80,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        audit = result.to_audit_dict()
        assert "planned_session_count" in audit
        assert "planned_heavy_session_activity_count" in audit
        assert "heavy_session_marker" in audit
        assert "heavy_session_app_name" in audit
        assert "heavy_session_project_kind" in audit
        assert audit["planned_heavy_session_activity_count"] == 80
        assert audit["heavy_session_marker"] == fixture_module.HEAVY_SESSION_MARKER

    def test_no_heavy_session_when_count_zero(
        self, fixture_module, temp_db
    ) -> None:
        """When heavy_session_activity_count is 0, no heavy session marker
        activities should exist."""
        spec = fixture_module.BenchmarkFixtureSpec(
            report_date=fixture_module.DEFAULT_REPORT_DATE,
            activity_count=200,
            day_start_seconds=fixture_module.DEFAULT_DAY_START_SECONDS,
            span_seconds=fixture_module.DEFAULT_SPAN_SECONDS,
            scenario="realistic_heavy_day",
            seed=42,
            chunk_size=fixture_module.DEFAULT_CHUNK_SIZE,
            heavy_session_activity_count=0,
        )
        result = fixture_module.build_realistic_heavy_day_fixture(spec=spec)
        assert result.planned_heavy_session_activity_count == 0
        assert result.heavy_session_marker == ""

        import worktrace.db as db_module
        with db_module.get_connection() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) as c FROM activity_log WHERE window_title = ?",
                (fixture_module.HEAVY_SESSION_WINDOW_TITLE,),
            ).fetchone()
        assert rows["c"] == 0
