"""Process-internal UI-facing backend API boundary.

The ``worktrace.api`` package is the only layer the UI (``worktrace.ui``) is
allowed to import. It exposes thin facades over ``worktrace.services`` so the UI
never touches services, db, or collector modules directly.

Architecture (single process, multi thread)::

    UI thread  ──> worktrace.api ──> worktrace.services ──> worktrace.db
                                            │
    collector thread ──> worktrace.collector

No HTTP/FastAPI is introduced. The facades are plain Python functions.
"""

from __future__ import annotations
