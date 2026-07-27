"""Shared synthetic artifact builders for performance comparison tests.

Provides deterministic JSON payload builders for product and WebView
benchmark artifacts (``result.json``, ``progress.json``, ``failure.json``,
``webview-benchmark.json``), baseline/HEAD SHA constants, and
temporary-directory write helpers.

Comparison gate logic, assertions, and business rules live in the
individual test files — this module only constructs synthetic data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASELINE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON payload to an arbitrary path, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Product benchmark artifact builders (schema v3)
# ---------------------------------------------------------------------------

def make_product_fixture_audit(
    *,
    scenario: str = "20k_activities",
    requested_count: int = 20000,
    inserted_count: int | None = None,
    preexisting_activity_count: int = 0,
    connection_count: int = 1,
    commit_count: int = 41,
) -> dict[str, Any]:
    """Build a synthetic but contract-valid single-scenario fixture_audit."""
    return {
        "scenario": scenario,
        "requested_count": requested_count,
        "inserted_count": inserted_count if inserted_count is not None else requested_count,
        "preexisting_activity_count": preexisting_activity_count,
        "fixture_build_seconds": 1.0,
        "connection_count": connection_count,
        "commit_count": commit_count,
        "chunk_size": 500,
        "builder_version": "1.0",
        "report_date": "2026-07-15",
    }


def make_product_result(
    *,
    revision: str,
    scenario: str = "20k_activities",
    metrics: dict[str, Any] | None = None,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    python_version: str = "3.11.5",
    target_root: str = "/tmp/worktree",
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
    github_workflow_sha: str | None = None,
    runner_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a synthetic but schema-valid product benchmark driver result.

    Schema v3 records both ``requested_revision`` (from ``--revision``) and
    ``actual_target_revision`` (from ``git rev-parse HEAD`` on the target
    worktree).  Only the metric relevant to ``scenario`` is included by
    default (the memory metric lives in the compact_memory_driver now).
    """
    if scenario == "10k_contributions":
        default_metric_key = "projection_10k_contributions_seconds"
        default_requested_count = 10000
    else:
        default_metric_key = "projection_20k_total_seconds"
        default_requested_count = 20000
    if metrics is None:
        metrics = {
            default_metric_key: {
                "samples_seconds": [1.0, 1.05, 0.98],
                "median_seconds": 1.0,
                "consistency_hash": "hash_" + default_metric_key,
            },
        }
    if fixture_audit is None:
        fixture_audit = make_product_fixture_audit(
            scenario=scenario, requested_count=default_requested_count
        )
    return {
        "schema_version": 3,
        "requested_revision": revision,
        "actual_target_revision": actual_target_revision or revision,
        "github_workflow_sha": github_workflow_sha,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "python_version": python_version,
        "target_root": target_root,
        "fixture_audit": fixture_audit,
        "metrics": metrics,
        "runner_metadata": runner_metadata or {},
    }


def make_product_progress(
    *,
    revision: str,
    scenario: str = "20k_activities",
    phase: str = "projection",
    completed_samples: int = 2,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
) -> dict[str, Any]:
    """Build a synthetic progress.json payload."""
    if fixture_audit is None:
        fixture_audit = make_product_fixture_audit(scenario=scenario)
    return {
        "schema_version": 3,
        "phase": phase,
        "completed_samples": completed_samples,
        "requested_revision": revision,
        "actual_target_revision": actual_target_revision or revision,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "fixture_audit": fixture_audit,
    }


def make_product_failure(
    *,
    failure_category: str = "driver_error",
    failure_message: str = "boom",
) -> dict[str, Any]:
    """Build a synthetic failure.json payload."""
    return {
        "failure_category": failure_category,
        "failure_message": failure_message,
    }


def write_product_result(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Write a driver ``result.json`` into ``output_dir``."""
    return write_json(output_dir / "result.json", payload)


def make_product_side(
    module: Any,
    output_dir: Path,
    *,
    label: str = "baseline",
    expected_sha: str = BASELINE_SHA,
    scenario: str = "20k_activities",
    result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
) -> Any:
    """Write artifacts into ``output_dir`` and return a ``SideResult``.

    At least one of ``result`` or ``progress`` must be provided.
    """
    if result is not None:
        write_json(output_dir / "result.json", result)
    if progress is not None:
        write_json(output_dir / "progress.json", progress)
    if failure is not None:
        write_json(output_dir / "failure.json", failure)
    return module.SideResult(
        label=label,
        output_dir=output_dir,
        expected_sha=expected_sha,
        scenario=scenario,
    )


# ---------------------------------------------------------------------------
# WebView benchmark artifact builders (schema v2)
# ---------------------------------------------------------------------------

def make_webview_fixture_audit(
    *,
    requested_count: int = 20000,
    inserted_count: int | None = None,
    preexisting_activity_count: int = 0,
    connection_count: int = 1,
    commit_count: int = 41,
) -> dict[str, Any]:
    """Build a synthetic but contract-valid WebView fixture_audit entry."""
    return {
        "scenario": "webview_render",
        "requested_count": requested_count,
        "inserted_count": inserted_count if inserted_count is not None else requested_count,
        "preexisting_activity_count": preexisting_activity_count,
        "fixture_build_seconds": 1.0,
        "connection_count": connection_count,
        "commit_count": commit_count,
        "chunk_size": 500,
        "builder_version": "1.0",
        "report_date": "2026-07-15",
    }


def make_webview_result(
    *,
    revision: str,
    status: str = "ok",
    metrics: dict[str, Any] | None = None,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    python_version: str = "3.11.5",
    activity_count: int = 20000,
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
    github_workflow_sha: str | None = None,
    failure_category: str = "",
    failure_reason: str = "",
) -> dict[str, Any]:
    """Build a synthetic but schema-valid WebView driver result.

    Schema v2 records both ``requested_revision`` and
    ``actual_target_revision``.
    """
    if metrics is None:
        metrics = {
            "cold_timeline_seconds": {
                "samples_seconds": [1.0],
                "median_seconds": 1.0,
            },
            "warm_timeline_seconds": {
                "samples_seconds": [0.8, 0.9, 0.85],
                "median_seconds": 0.85,
            },
            "detail_payload_seconds": {
                "samples_seconds": [0.05, 0.06, 0.055],
                "median_seconds": 0.055,
            },
            "detail_total_seconds": {
                "samples_seconds": [0.2, 0.22, 0.21],
                "median_seconds": 0.21,
            },
        }
    if fixture_audit is None:
        fixture_audit = make_webview_fixture_audit(requested_count=activity_count)
    return {
        "schema_version": 2,
        "requested_revision": revision,
        "actual_target_revision": actual_target_revision or revision,
        "github_workflow_sha": github_workflow_sha,
        "status": status,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "python_version": python_version,
        "activity_count": activity_count,
        "fixture_audit": fixture_audit,
        "metrics": metrics,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
    }


def write_webview_result(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Write a driver result to ``webview-benchmark.json`` in ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "webview-benchmark.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def make_webview_side(
    comparison_module: Any,
    output_dir: Path,
    *,
    label: str,
    payload: dict[str, Any] | None,
    expected_sha: str,
) -> Any:
    """Create a ``SideResult`` by writing ``payload`` to disk (or leaving
    the artifact missing when ``payload is None``)."""
    if payload is not None:
        artifact_path = write_webview_result(output_dir, payload)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "webview-benchmark.json"
    return comparison_module.SideResult(
        label=label,
        artifact_path=artifact_path,
        expected_sha=expected_sha,
    )
