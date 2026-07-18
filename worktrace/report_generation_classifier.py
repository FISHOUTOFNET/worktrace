"""Report-generation fallback for low-level repair and migration writes.

Normal product mutations declare effects through ``DomainUnitOfWork``. This
classifier remains a narrow safety boundary for schema migration, data repair,
and tests that intentionally exercise SQLite below the command layer. Keeping
its domain table knowledge outside ``db.py`` prevents the connection primitive
from owning report policy.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from enum import IntEnum
from functools import lru_cache
from typing import Mapping

_CLASSIFIER_SCOPE_DEPTH: ContextVar[int] = ContextVar(
    "worktrace_report_structure_classifier_scope_depth",
    default=0,
)

_WRITE_TOKEN_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|REINDEX|ATTACH|DETACH)\b",
    re.IGNORECASE,
)
_REPORT_STRUCTURE_TABLES = {
    "ACTIVITY_LOG",
    "ACTIVITY_PROJECT_ASSIGNMENT",
    "ACTIVITY_RESOURCE",
    "ACTIVITY_CLIPBOARD_EVENT",
    "SESSION_BOUNDARY",
    "REPORT_SESSION_OPERATION",
    "REPORT_SESSION_OPERATION_MEMBER",
    "PROJECT",
}
_REPORT_STRUCTURE_SETTINGS = {
    "context_carry_minutes",
    "unrecorded_gap_boundary_seconds",
}
_ACTIVITY_LOG_UPDATE_RE = re.compile(
    r"\bUPDATE\s+(?:[A-Z0-9_]+\.)?ACTIVITY_LOG\s+SET\s+(.*?)(?:\s+WHERE\s+|$)",
    re.IGNORECASE | re.DOTALL,
)


class ReportStructureSqlClassification(IntEnum):
    NONE = 0
    ALWAYS = 1
    SETTINGS_PARAMETERS = 2


@contextmanager
def report_structure_classifier_scope():
    """Authorize SQL classification for migration, repair, or replacement code."""

    token = _CLASSIFIER_SCOPE_DEPTH.set(_CLASSIFIER_SCOPE_DEPTH.get() + 1)
    try:
        yield
    finally:
        _CLASSIFIER_SCOPE_DEPTH.reset(token)


def report_structure_classifier_enabled() -> bool:
    return _CLASSIFIER_SCOPE_DEPTH.get() > 0


def _parameter_values(parameters):
    if isinstance(parameters, Mapping):
        return parameters.values()
    if isinstance(parameters, (tuple, list)):
        return parameters
    return ()


def parameters_affect_report_structure(parameters) -> bool:
    found_string = False
    for value in _parameter_values(parameters):
        if not isinstance(value, str):
            continue
        found_string = True
        if value in _REPORT_STRUCTURE_SETTINGS:
            return True
    return not found_string


def _activity_log_update_changes_structure(sql: str) -> bool:
    match = _ACTIVITY_LOG_UPDATE_RE.search(sql)
    if match is None:
        return True
    columns: set[str] = set()
    for assignment in match.group(1).split(","):
        left = assignment.split("=", 1)[0].strip().rsplit(".", 1)[-1]
        left = left.strip('"`[] ').upper()
        if left:
            columns.add(left)
    if not columns:
        return True
    return not columns.issubset({"DURATION_SECONDS", "UPDATED_AT"})


@lru_cache(maxsize=1024)
def classify_report_structure_sql(sql: str) -> ReportStructureSqlClassification:
    text = str(sql or "").strip()
    if not text or not _WRITE_TOKEN_RE.search(text):
        return ReportStructureSqlClassification.NONE
    upper = " ".join(text.upper().split())

    if upper.startswith(("CREATE ", "DROP ", "ALTER ")):
        if "SETTINGS" in upper or any(
            re.search(rf"\b{table}\b", upper)
            for table in _REPORT_STRUCTURE_TABLES
        ):
            return ReportStructureSqlClassification.ALWAYS
        return ReportStructureSqlClassification.NONE

    if re.search(r"\bACTIVITY_LOG\b", upper):
        if upper.startswith("UPDATE") and not _activity_log_update_changes_structure(
            text
        ):
            return ReportStructureSqlClassification.NONE
        return ReportStructureSqlClassification.ALWAYS

    if re.search(r"\bSETTINGS\b", upper):
        if upper.startswith("DELETE"):
            return ReportStructureSqlClassification.ALWAYS
        return ReportStructureSqlClassification.SETTINGS_PARAMETERS

    if any(
        re.search(rf"\b{table}\b", upper)
        for table in _REPORT_STRUCTURE_TABLES
    ):
        return ReportStructureSqlClassification.ALWAYS
    return ReportStructureSqlClassification.NONE


def sql_affects_report_structure(sql: str, parameters=()) -> bool:
    classification = classify_report_structure_sql(str(sql))
    if classification is ReportStructureSqlClassification.ALWAYS:
        return True
    if classification is ReportStructureSqlClassification.SETTINGS_PARAMETERS:
        return parameters_affect_report_structure(parameters)
    return False


__all__ = [
    "ReportStructureSqlClassification",
    "classify_report_structure_sql",
    "parameters_affect_report_structure",
    "report_structure_classifier_enabled",
    "report_structure_classifier_scope",
    "sql_affects_report_structure",
]
