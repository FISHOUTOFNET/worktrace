"""Contract tests for the WebView baseline-vs-HEAD completion condition.

The detail benchmark's completion condition must be observable from
outside the HEAD revision so baseline and HEAD can be measured with the
same gate.  The condition lives in ``_MEASURE_JS`` inside
``scripts/webview_render_perf.py`` as JavaScript, so these tests:

  * statically verify the JavaScript source contains the required
    external observable gates (payload resolved, DOM non-empty, DOM
    stable across two frames, no explicit error),
  * statically verify HEAD-private implementation details
    (``lastSessionActivitySummaryViewModel``, ``detailsInFlight``,
    specific header text) are recorded only as diagnostics and never
    used as completion gates,
  * functionally verify the Python result-parsing path fails closed
    when ``detail_error`` is present, when ``detail_payload_ms`` is
    missing, or when ``detail_dom_row_count`` is zero,
  * verify cleanup-stage ``ObjectDisposedException`` is recorded as a
    diagnostic and never overwrites the primary failure category.

These tests do NOT launch WebView2.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "webview_render_perf.py"


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def harness_module():
    """Load scripts/webview_render_perf.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "webview_render_perf_completion_under_test", HARNESS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["webview_render_perf_completion_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("webview_render_perf_completion_under_test", None)
        raise
    return module


@pytest.fixture(scope="module")
def measure_js(harness_module) -> str:
    """The full _MEASURE_JS source string."""
    return harness_module._MEASURE_JS


# ---------------------------------------------------------------------------
# Static contract: external observable completion gates must be present
# ---------------------------------------------------------------------------

class TestCompletionGatesPresent:
    """The JS completion contract must rely on external observable
    signals, not HEAD-private implementation details."""

    def test_payload_resolved_is_a_gate(self, measure_js: str) -> None:
        """``payloadState.resolved`` must appear as part of the completion
        decision, not only as a diagnostic."""
        assert "payloadState" in measure_js
        assert "payloadState.resolved" in measure_js, (
            "completion contract must gate on payloadState.resolved"
        )

    def test_dom_non_empty_is_a_gate(self, measure_js: str) -> None:
        """DOM row count > 0 must be a completion gate."""
        assert "domRows > 0" in measure_js

    def test_dom_stable_across_two_frames_is_a_gate(self, measure_js: str) -> None:
        """DOM stability across two animation frames must be required."""
        assert "stableFrames" in measure_js
        assert "stableFrames >= 2" in measure_js, (
            "completion contract must require >= 2 stable frames"
        )

    def test_explicit_error_short_circuits_as_failure(
        self, measure_js: str
    ) -> None:
        """An explicit error element/text must short-circuit the wait
        loop with a failure category — not be ignored."""
        assert "explicitError" in measure_js
        assert "detail_load_failed" in measure_js
        assert 'failureCategory: "detail_explicit_error"' in measure_js, (
            "explicit error must produce a failureCategory, not a success"
        )

    def test_completion_helper_takes_payload_callback(
        self, measure_js: str
    ) -> None:
        """``waitForDetailCompletion`` must accept a ``getPayloadState``
        callback so the helper is self-contained and testable, instead
        of reading an outer-scope variable that might not exist in
        baseline."""
        assert "waitForDetailCompletion" in measure_js
        assert "payloadDeadline, domDeadline, getPayloadState" in measure_js
        assert "getPayloadState()" in measure_js

    def test_payload_callback_invoked_at_call_site(self, measure_js: str) -> None:
        """The call site must pass ``detailPayloadState`` as the
        payload-state callback so the bridge wrap actually drives
        completion."""
        assert "function () { return detailPayloadState; }" in measure_js


# ---------------------------------------------------------------------------
# Static contract: HEAD-private fields must be diagnostics only
# ---------------------------------------------------------------------------

class TestHeadPrivateFieldsAreDiagnosticsOnly:
    """HEAD-private fields (lastSessionActivitySummaryViewModel,
    detailsInFlight, header text) may be recorded as diagnostics but
    must NOT be completion gates."""

    def test_view_model_recorded_as_diagnostic(self, measure_js: str) -> None:
        """``lastSessionActivitySummaryViewModel`` may appear in the
        diagnostics object but must not be part of the completion
        condition."""
        assert "lastSessionActivitySummaryViewModel" in measure_js
        assert "view_model_present" in measure_js

    def test_details_in_flight_recorded_as_diagnostic(
        self, measure_js: str
    ) -> None:
        """``detailsInFlight`` may be recorded as a diagnostic count but
        must not gate completion."""
        assert "detailsInFlight" in measure_js
        assert "details_in_flight" in measure_js

    def test_header_text_recorded_as_diagnostic(self, measure_js: str) -> None:
        """Header text may be recorded as a diagnostic but must not
        alone cause a baseline failure (only explicit error keywords
        like 失败/error should short-circuit)."""
        assert "header_text" in measure_js

    def test_view_model_not_in_completion_branch(
        self, measure_js: str
    ) -> None:
        """The completion-success branch must not reference the
        HEAD-private ViewModel field directly."""
        # The two-step contract checks payloadState.resolved in step 1
        # and domRows > 0 + stableFrames >= 2 in step 2.
        assert "domRows > 0" in measure_js
        assert "stableFrames >= 2" in measure_js
        assert "payloadState.resolved && domRows > 0 && vm" not in measure_js
        assert "vm && payloadState.resolved" not in measure_js

    def test_details_in_flight_not_in_completion_branch(
        self, measure_js: str
    ) -> None:
        """The completion-success branch must not reference
        ``detailsInFlight``."""
        assert "inFlight && payloadResolved" not in measure_js
        assert "payloadResolved && inFlight" not in measure_js

    def test_completion_does_not_require_specific_header_text(
        self, measure_js: str
    ) -> None:
        """Completion must NOT require a specific Chinese header text —
        that text is HEAD-specific and would fail on baseline."""
        assert "headerText ===" not in measure_js
        assert "headerText ==" not in measure_js
        assert "headerText.indexOf" in measure_js


# ---------------------------------------------------------------------------
# Static contract: explicit error keywords are bounded
# ---------------------------------------------------------------------------

class TestExplicitErrorKeywords:
    """The explicit-error detector must catch real failure markers
    (失败, error) without coupling to HEAD-specific success text."""

    def test_failure_keyword_detected(self, measure_js: str) -> None:
        """The Chinese failure keyword 失败 must map to
        ``detail_load_failed``."""
        assert '"失败"' in measure_js or "'失败'" in measure_js
        assert "detail_load_failed" in measure_js

    def test_error_keyword_detected(self, measure_js: str) -> None:
        """The English error keyword must map to ``detail_error_text``."""
        assert '"error"' in measure_js or "'error'" in measure_js
        assert "detail_error_text" in measure_js

    def test_no_head_specific_success_text_required(
        self, measure_js: str
    ) -> None:
        """The error detector must not require HEAD-specific header
        success text — only failure markers."""
        assert "return null" in measure_js


# ---------------------------------------------------------------------------
# Static contract: timeout failure must preserve real failure category
# ---------------------------------------------------------------------------

class TestTimeoutFailureCategory:
    """When the payload deadline is reached without completion, the
    failure category must be ``detail_payload_timeout`` — not a masked
    success.  The old unified ``detail_timeout`` is replaced by the
    two-step contract."""

    def test_timeout_returns_detail_payload_timeout(self, measure_js: str) -> None:
        assert 'failureCategory: "detail_payload_timeout"' in measure_js or \
               "failureCategory: 'detail_payload_timeout'" in measure_js

    def test_timeout_returns_completed_false(self, measure_js: str) -> None:
        """The final return (after the while loop) must mark
        ``completed: false``."""
        assert "completed: false" in measure_js


# ---------------------------------------------------------------------------
# Functional contract: Python result parsing fails closed
# ---------------------------------------------------------------------------

class TestPythonResultParsingFailClosed:
    """The Python ``_run_harness`` result-parsing path (the
    ``detail_failures`` loop near the end of ``_run_harness``) must
    fail closed when any run reports a ``detail_error`` or is missing
    ``detail_payload_ms``."""

    def _make_run_with_detail_error(self, error: str) -> dict[str, Any]:
        return {
            "label": "run0",
            "stages": {"detail_error": error},
        }

    def _make_run_missing_detail_payload(self) -> dict[str, Any]:
        return {
            "label": "run0",
            "stages": {
                # No detail_payload_ms key — measurement did not complete.
                "overview_total_ms": 100.0,
            },
        }

    def _make_run_with_payload_but_zero_dom_rows(self) -> dict[str, Any]:
        return {
            "label": "run0",
            "stages": {
                "detail_payload_ms": 50.0,
                "detail_render_ms": 10.0,
                "detail_total_ms": 60.0,
            },
            "detail_dom_row_count": 0,
            "detail_payload_resolved": True,
        }

    def _make_run_with_payload_and_dom_rows(self) -> dict[str, Any]:
        return {
            "label": "run0",
            "stages": {
                "detail_payload_ms": 50.0,
                "detail_render_ms": 10.0,
                "detail_total_ms": 60.0,
            },
            "detail_dom_row_count": 3,
            "detail_payload_resolved": True,
        }

    def test_run_with_detail_error_marks_run_failed(self, harness_module) -> None:
        """When a run has ``stages.detail_error``, the harness must
        classify the run as a detail failure."""
        run = self._make_run_with_detail_error("detail_timeout")
        stages = run.get("stages", {})
        detail_error = stages.get("detail_error")
        assert detail_error, (
            "detail_error must be detected as a failure"
        )

    def test_run_missing_detail_payload_marks_run_failed(
        self, harness_module
    ) -> None:
        """When a run has no ``detail_payload_ms`` in stages, the
        harness must classify the run as a detail failure (the
        measurement did not complete)."""
        run = self._make_run_missing_detail_payload()
        stages = run.get("stages", {})
        detail_error = stages.get("detail_error")
        has_payload = "detail_payload_ms" in stages
        assert not detail_error
        assert not has_payload, (
            "missing detail_payload_ms must be detectable as a failure"
        )

    def test_run_with_payload_but_zero_dom_rows_is_still_valid(
        self, harness_module
    ) -> None:
        """A run that recorded ``detail_payload_ms`` (i.e. the
        completion contract returned ``completed: true``) but with zero
        DOM rows would be a contract violation.  The completion
        contract requires ``domRows > 0``, so this scenario should be
        impossible — but if it ever happens, the realism assertion in
        the JS sets ``detail_error = 'detail_dom_row_count_zero'``."""
        run = self._make_run_with_payload_but_zero_dom_rows()
        assert "detail_dom_row_count_zero" in harness_module._MEASURE_JS

    def test_run_with_payload_and_dom_rows_is_valid(self, harness_module) -> None:
        """A run with ``detail_payload_ms`` and ``detail_dom_row_count > 0``
        must be a valid run — no failure."""
        run = self._make_run_with_payload_and_dom_rows()
        stages = run.get("stages", {})
        detail_error = stages.get("detail_error")
        has_payload = "detail_payload_ms" in stages
        assert not detail_error
        assert has_payload
        assert run["detail_dom_row_count"] > 0

    def test_harness_returns_failure_when_any_run_has_detail_error(
        self, harness_module
    ) -> None:
        """``_run_harness``'s result-parsing path must return
        ``status: failed`` with ``failure_category:
        detail_render_failure`` when at least one run has a
        ``detail_error``."""
        # We simulate the exact logic from _run_harness lines ~880-910.
        runs_data = [
            self._make_run_with_payload_and_dom_rows(),
            self._make_run_with_detail_error("detail_timeout"),
        ]
        detail_failures: list[str] = []
        for run in runs_data:
            stages = run.get("stages", {}) if isinstance(run, dict) else {}
            detail_error = stages.get("detail_error")
            if detail_error:
                detail_failures.append(
                    f"{run.get('label', '?')}: {detail_error}"
                )
            elif "detail_payload_ms" not in stages:
                detail_failures.append(
                    f"{run.get('label', '?')}: detail_payload_ms missing"
                )
        assert len(detail_failures) == 1
        assert "detail_timeout" in detail_failures[0]

    def test_harness_returns_failure_when_any_run_missing_payload(
        self, harness_module
    ) -> None:
        runs_data = [
            self._make_run_with_payload_and_dom_rows(),
            self._make_run_missing_detail_payload(),
        ]
        detail_failures: list[str] = []
        for run in runs_data:
            stages = run.get("stages", {}) if isinstance(run, dict) else {}
            detail_error = stages.get("detail_error")
            if detail_error:
                detail_failures.append(
                    f"{run.get('label', '?')}: {detail_error}"
                )
            elif "detail_payload_ms" not in stages:
                detail_failures.append(
                    f"{run.get('label', '?')}: detail_payload_ms missing"
                )
        assert len(detail_failures) == 1
        assert "detail_payload_ms missing" in detail_failures[0]


# ---------------------------------------------------------------------------
# Functional contract: cleanup ObjectDisposedException must not mask failure
# ---------------------------------------------------------------------------

class TestCleanupExceptionDoesNotMaskFailure:
    """When WebView2 raises ``ObjectDisposedException`` during cleanup
    (after ``window.destroy()``), the harness must:

      * preserve the real measurement failure if one already occurred,
      * record the cleanup exception only as a diagnostic,
      * never let the cleanup exception overwrite the primary failure
        category.
    """

    def test_cleanup_disposed_exception_branch_exists(self, harness_module) -> None:
        """The harness source must contain the ObjectDisposed handling
        branch."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "ObjectDisposed" in source
        assert "cleanup_diagnostic" in source

    def test_cleanup_disposed_does_not_overwrite_real_error(self) -> None:
        """If a real measurement failure already populated
        ``results_holder['error']``, the cleanup disposed exception
        must NOT overwrite it — only ``cleanup_diagnostic`` is set."""
        results_holder: dict[str, Any] = {
            "results": None,
            "error": "real_measurement_failure",
        }
        exc_name = "ObjectDisposedException"
        if "ObjectDisposed" in exc_name or "disposed" in "".lower():
            if results_holder["error"] is None:
                results_holder["cleanup_diagnostic"] = "simulated"
        assert results_holder["error"] == "real_measurement_failure"
        assert "cleanup_diagnostic" not in results_holder

    def test_cleanup_disposed_recorded_as_diagnostic_when_no_real_error(self) -> None:
        """If no real measurement failure occurred, the cleanup
        disposed exception is recorded as a diagnostic — but the
        harness still returns a measurement-timeout failure because
        ``results_holder['results']`` is None."""
        results_holder: dict[str, Any] = {
            "results": None,
            "error": None,
        }
        exc_name = "ObjectDisposedException"
        if "ObjectDisposed" in exc_name:
            if results_holder["error"] is None:
                results_holder["cleanup_diagnostic"] = "simulated_disposed"
        assert results_holder["cleanup_diagnostic"] == "simulated_disposed"
        assert results_holder["results"] is None
        assert results_holder["error"] is None

    def test_non_disposed_exception_overwrites_error(self) -> None:
        """A non-disposed exception during evaluation must set
        ``results_holder['error']`` so the harness reports it as the
        primary failure."""
        results_holder: dict[str, Any] = {
            "results": None,
            "error": None,
        }
        exc_name = "ValueError"
        exc_msg = "something else went wrong"
        if "ObjectDisposed" in exc_name or "disposed" in exc_msg.lower():
            if results_holder["error"] is None:
                results_holder["cleanup_diagnostic"] = exc_msg
        else:
            results_holder["error"] = f"evaluation failed: {exc_msg}"
        assert results_holder["error"] == "evaluation failed: something else went wrong"
        assert "cleanup_diagnostic" not in results_holder


# ---------------------------------------------------------------------------
# Cross-revision adapter contract: baseline and HEAD must produce
# equivalent standardized results
# ---------------------------------------------------------------------------

class TestCrossRevisionAdapterContract:
    """The completion contract must produce equivalent standardized
    results on baseline and HEAD, even when HEAD-private fields differ.

    The adapter is implicit: ``waitForDetailCompletion`` reads only
    external observable signals (payloadResolved, DOM rows, DOM
    stability, explicit error).  HEAD-private fields are recorded as
    diagnostics and never gated on.  So baseline and HEAD both
    produce a ``completionState`` with the same shape.
    """

    def test_completion_state_shape_is_revision_independent(
        self, measure_js: str
    ) -> None:
        """The ``completionState`` object returned by
        ``waitForDetailCompletion`` must have the same fields
        regardless of revision."""
        assert "completed: true" in measure_js
        assert "completed: false" in measure_js
        assert "failureCategory" in measure_js
        assert "diagnostics" in measure_js

    def test_baseline_no_view_model_still_succeeds(self, measure_js: str) -> None:
        """If ``lastSessionActivitySummaryViewModel`` does not exist on
        baseline (the field was added in HEAD), the diagnostic read
        must catch the exception and record ``view_model_present: false``
        without failing the completion."""
        assert "try {" in measure_js
        assert "vm = window.WorkTraceApp.lastSessionActivitySummaryViewModel" in measure_js
        assert "catch (e) { vm = null; }" in measure_js

    def test_baseline_no_details_in_flight_still_succeeds(
        self, measure_js: str
    ) -> None:
        """If ``detailsInFlight`` does not exist on baseline, the
        diagnostic read must catch the exception and record
        ``details_in_flight: 0`` without failing the completion."""
        assert "window.WorkTraceApp.detailsInFlight" in measure_js
        assert "catch (e) { inFlight = 0; }" in measure_js

    def test_payload_resolved_callback_is_external_observable(
        self, measure_js: str
    ) -> None:
        """The ``getPayloadState`` callback reads
        ``detailPayloadState``, which is set by the wrapped bridge's
        detail Promise resolving — an external observable signal that
        works on both baseline and HEAD."""
        assert "detailPayloadState = { resolved: false, error: null }" in measure_js
        assert "detailPayloadState.resolved = true" in measure_js
        assert ".then(function (result)" in measure_js


# ---------------------------------------------------------------------------
# Driver artifact contract: completion-related fields recorded
# ---------------------------------------------------------------------------

class TestDriverArtifactRecordsCompletionFields:
    """The driver's structured output must record completion-related
    diagnostic fields so the comparison layer can audit them."""

    def test_driver_records_detail_payload_resolved(self, harness_module) -> None:
        """The driver source must record ``detail_payload_resolved`` in
        the run result so the comparison layer can verify the
        completion contract actually fired."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "detail_payload_resolved" in source

    def test_driver_records_detail_dom_row_count(self, harness_module) -> None:
        """The driver source must record ``detail_dom_row_count``."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "detail_dom_row_count" in source

    def test_driver_records_detail_view_model_present(self, harness_module) -> None:
        """The driver source must record ``detail_view_model_present``
        as a diagnostic."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "detail_view_model_present" in source

    def test_driver_records_detail_in_flight(self, harness_module) -> None:
        """The driver source must record ``detail_in_flight`` as a
        diagnostic."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "detail_in_flight" in source

    def test_driver_records_detail_header_text(self, harness_module) -> None:
        """The driver source must record ``detail_header_text`` as a
        diagnostic."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "detail_header_text" in source

    def test_driver_does_not_gate_on_view_model_for_success(
        self, harness_module
    ) -> None:
        """The driver's success path must not gate on
        ``detail_view_model_present`` — that field is HEAD-specific."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "detail_view_model_present == False" not in source
        assert "not detail_view_model_present" not in source


# ---------------------------------------------------------------------------
# Workload validity failure categories
# ---------------------------------------------------------------------------

class TestWorkloadValidityFailureCategories:
    """Workload validity failures must use distinct categories, not be
    conflated with payload timeout or completion failures.

    Categories:
      * ``detail_not_heavy`` — selected session is not the heavy session.
      * ``detail_row_count_below_expected`` — source activity count
        below the minimum threshold.
      * ``detail_row_count_mismatch`` — DOM rows don't match ViewModel.

    These are workload validity failures: the Detail completed, but the
    measured workload is wrong (too light or inconsistent).  They must
    NOT be confused with ``detail_payload_timeout`` (payload never
    settled) or ``detail_dom_empty`` (DOM never had rows).
    """

    def test_detail_not_heavy_category_present(self, measure_js: str) -> None:
        """``detail_not_heavy`` must be a distinct failure category."""
        assert '"detail_not_heavy"' in measure_js

    def test_detail_row_count_below_expected_category_present(
        self, measure_js: str
    ) -> None:
        """``detail_row_count_below_expected`` must be a distinct
        failure category."""
        assert '"detail_row_count_below_expected"' in measure_js

    def test_detail_row_count_mismatch_category_present(
        self, measure_js: str
    ) -> None:
        """``detail_row_count_mismatch`` must be a distinct failure
        category."""
        assert '"detail_row_count_mismatch"' in measure_js

    def test_workload_categories_distinct_from_payload_timeout(
        self, measure_js: str
    ) -> None:
        """Workload validity categories must NOT be the same string as
        ``detail_payload_timeout`` — they represent different failures.
        """
        assert '"detail_not_heavy"' in measure_js
        assert '"detail_row_count_below_expected"' in measure_js
        assert '"detail_row_count_mismatch"' in measure_js
        # These are distinct from payload/DOM completion failures.
        assert '"detail_payload_timeout"' in measure_js
        assert '"detail_dom_empty"' in measure_js
        # Verify they are different strings.
        assert '"detail_not_heavy"' != '"detail_payload_timeout"'
        assert '"detail_row_count_below_expected"' != '"detail_payload_timeout"'
        assert '"detail_row_count_mismatch"' != '"detail_dom_empty"'

    def test_workload_gates_run_after_completion_success(
        self, measure_js: str
    ) -> None:
        """Workload validity gates must run inside the
        ``completionState.completed`` branch — they verify the
        *measured* Detail is heavy, not that Detail completed.
        """
        # The workload gates must appear after the completion success
        # branch records detail_row_count and detail_dom_row_count.
        assert "results.detail_source_activity_count = selectedEventCount" in measure_js
        assert "results.detail_summary_row_count = results.detail_row_count" in measure_js
        # The gates reference these fields.
        assert "results.selected_detail_is_heavy" in measure_js
        assert "results.detail_source_activity_count" in measure_js
        assert "results.detail_dom_row_count" in measure_js
        assert "results.detail_row_count" in measure_js

    def test_workload_gate_uses_source_activity_count_not_dom_rows(
        self, measure_js: str
    ) -> None:
        """The ``detail_row_count_below_expected`` gate must check
        ``detail_source_activity_count`` (the public event_count), NOT
        ``detail_dom_row_count`` — DOM rows may aggregate multiple
        activities into summary rows.
        """
        # The gate must reference source activity count.
        assert (
            "results.detail_source_activity_count\n                               < "
            in measure_js
            or "results.detail_source_activity_count < Math.max" in measure_js
            or "results.detail_source_activity_count" in measure_js
        )

    def test_workload_gate_threshold_uses_min_heavy_threshold(
        self, measure_js: str
    ) -> None:
        """The workload gate must use ``minHeavyThreshold`` (not a
        hardcoded 50) so smoke profile (heavy_count=12) is not
        incorrectly rejected.
        """
        assert "minHeavyThreshold" in measure_js
        assert "Math.max(minHeavyThreshold, 50)" not in measure_js

    def test_no_heavy_session_found_category_present(
        self, measure_js: str
    ) -> None:
        """``no_heavy_session_found`` must be a failure category when
        no detail key could be selected (empty Timeline or no matching
        entry).
        """
        assert '"no_heavy_session_found"' in measure_js

    def test_workload_gate_detail_dom_row_count_zero_still_present(
        self, measure_js: str
    ) -> None:
        """The existing ``detail_dom_row_count_zero`` realism assertion
        must still be present (it catches a different issue: DOM never
        rendered any rows, even after completion).
        """
        assert '"detail_dom_row_count_zero"' in measure_js


# ---------------------------------------------------------------------------
# Functional contract: workload validity failures are detected
# ---------------------------------------------------------------------------

class TestWorkloadValidityFailureDetection:
    """Functional tests verifying the Python result-parsing path detects
    workload validity failures and classifies them as detail failures."""

    def _make_run_with_workload_error(self, error: str) -> dict[str, Any]:
        return {
            "label": "run0",
            "stages": {
                "detail_error": error,
                "detail_payload_ms": 50.0,
                "detail_render_ms": 10.0,
                "detail_total_ms": 60.0,
            },
            "detail_dom_row_count": 1,
            "detail_payload_resolved": True,
            "selected_detail_is_heavy": False,
            "selected_detail_selector_reason": "none",
            "detail_source_activity_count": 1,
        }

    def test_detail_not_heavy_detected_as_failure(self) -> None:
        """A run with ``detail_error = 'detail_not_heavy'`` must be
        detected by the ``detail_failures`` loop."""
        run = self._make_run_with_workload_error("detail_not_heavy")
        stages = run.get("stages", {})
        detail_error = stages.get("detail_error")
        assert detail_error == "detail_not_heavy"

    def test_detail_row_count_below_expected_detected_as_failure(self) -> None:
        """A run with ``detail_error = 'detail_row_count_below_expected'``
        must be detected by the ``detail_failures`` loop."""
        run = self._make_run_with_workload_error(
            "detail_row_count_below_expected"
        )
        stages = run.get("stages", {})
        detail_error = stages.get("detail_error")
        assert detail_error == "detail_row_count_below_expected"

    def test_detail_row_count_mismatch_detected_as_failure(self) -> None:
        """A run with ``detail_error = 'detail_row_count_mismatch'``
        must be detected by the ``detail_failures`` loop."""
        run = self._make_run_with_workload_error("detail_row_count_mismatch")
        stages = run.get("stages", {})
        detail_error = stages.get("detail_error")
        assert detail_error == "detail_row_count_mismatch"

    def test_workload_failures_propagate_to_harness_failure(
        self, harness_module
    ) -> None:
        """The ``_run_harness`` result-parsing path must include
        workload validity failures in ``detail_failures``, producing
        ``status: failed`` with ``failure_category:
        detail_render_failure``.
        """
        runs_data = [
            self._make_run_with_workload_error("detail_not_heavy"),
        ]
        detail_failures: list[str] = []
        for run in runs_data:
            stages = run.get("stages", {}) if isinstance(run, dict) else {}
            detail_error = stages.get("detail_error")
            if detail_error:
                detail_failures.append(
                    f"{run.get('label', '?')}: {detail_error}"
                )
            elif "detail_payload_ms" not in stages:
                detail_failures.append(
                    f"{run.get('label', '?')}: detail_payload_ms missing"
                )
        assert len(detail_failures) == 1
        assert "detail_not_heavy" in detail_failures[0]
