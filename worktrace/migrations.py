from __future__ import annotations

import sqlite3

from .constants import UNCATEGORIZED_PROJECT
from .resource_patterns import infer_resource_identity


def ensure_schema(conn: sqlite3.Connection, now: str) -> None:
    _ensure_activity_resource_column(conn)
    _ensure_new_tables(conn)
    _ensure_indexes(conn)
    _migrate_legacy_rules(conn, now)


def backfill_legacy_data(conn: sqlite3.Connection, now: str) -> None:
    _ensure_browser_resource(conn, now)
    _backfill_activity_resources(conn, now)
    _backfill_assignments(conn, now)


def _ensure_activity_resource_column(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
    if "resource_id" not in columns:
        conn.execute("ALTER TABLE activity_log ADD COLUMN resource_id INTEGER REFERENCES resource(id)")


def _ensure_new_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS resource (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_role TEXT NOT NULL CHECK (
                resource_role IN ('anchor', 'auxiliary')
            ),
            resource_type TEXT NOT NULL CHECK (
                resource_type IN ('file', 'web', 'communication', 'meeting', 'app', 'unknown')
            ),
            display_name TEXT NOT NULL,
            canonical_key TEXT NOT NULL UNIQUE,
            app_name TEXT,
            process_name TEXT,
            title_hint TEXT,
            default_project_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (default_project_id) REFERENCES project(id)
        );

        CREATE TABLE IF NOT EXISTS project_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL CHECK (
                rule_type IN ('keyword')
            ),
            pattern TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'user' CHECK (
                created_by IN ('system', 'user')
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES project(id)
        );

        CREATE TABLE IF NOT EXISTS activity_project_assignment (
            activity_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            confidence INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL CHECK (
                source IN (
                    'manual',
                    'anchor_resource_default',
                    'anchor_keyword',
                    'anchor_context',
                    'uncategorized'
                )
            ),
            is_manual INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (activity_id) REFERENCES activity_log(id),
            FOREIGN KEY (project_id) REFERENCES project(id)
        );
        """
    )


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_resource
        ON activity_log(resource_id);

        CREATE INDEX IF NOT EXISTS idx_resource_key
        ON resource(canonical_key);

        CREATE INDEX IF NOT EXISTS idx_resource_role_type
        ON resource(resource_role, resource_type);

        CREATE INDEX IF NOT EXISTS idx_resource_default_project
        ON resource(default_project_id);

        CREATE INDEX IF NOT EXISTS idx_assignment_project
        ON activity_project_assignment(project_id);

        CREATE INDEX IF NOT EXISTS idx_assignment_source_manual
        ON activity_project_assignment(source, is_manual);

        CREATE INDEX IF NOT EXISTS idx_project_rule_pattern
        ON project_rule(pattern);
        """
    )


def _migrate_legacy_rules(conn: sqlite3.Connection, now: str) -> None:
    rows = conn.execute(
        """
        SELECT keyword, project_id, enabled, created_at, updated_at
        FROM rule
        """
    ).fetchall()
    for row in rows:
        pattern = (row["keyword"] or "").strip()
        if not pattern:
            continue
        exists = conn.execute(
            """
            SELECT 1
            FROM project_rule
            WHERE rule_type = 'keyword' AND pattern = ? AND project_id = ?
            LIMIT 1
            """,
            (pattern, row["project_id"]),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO project_rule(project_id, rule_type, pattern, enabled, created_by, created_at, updated_at)
            VALUES (?, 'keyword', ?, ?, 'user', ?, ?)
            """,
            (
                row["project_id"],
                pattern,
                int(row["enabled"]),
                row["created_at"] or now,
                row["updated_at"] or now,
            ),
        )


def _ensure_browser_resource(conn: sqlite3.Connection, now: str) -> int:
    return _ensure_resource(
        conn,
        now,
        {
            "resource_role": "auxiliary",
            "resource_type": "web",
            "display_name": "浏览器 / 检索网页",
            "canonical_key": "web:browser",
            "app_name": None,
            "process_name": None,
            "title_hint": None,
        },
    )


def _backfill_activity_resources(conn: sqlite3.Connection, now: str) -> None:
    rows = conn.execute(
        """
        SELECT id, app_name, process_name, window_title
        FROM activity_log
        WHERE resource_id IS NULL
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        identity = infer_resource_identity(row["app_name"], row["process_name"], row["window_title"])
        resource_id = _ensure_resource(conn, now, identity.__dict__)
        conn.execute(
            "UPDATE activity_log SET resource_id = ?, updated_at = ? WHERE id = ? AND resource_id IS NULL",
            (resource_id, now, row["id"]),
        )


def _backfill_assignments(conn: sqlite3.Connection, now: str) -> None:
    uncategorized_id = _get_uncategorized_project_id(conn)
    rows = conn.execute(
        """
        SELECT a.id, a.project_id, a.manual_override, r.resource_role
        FROM activity_log a
        LEFT JOIN resource r ON r.id = a.resource_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM activity_project_assignment apa
            WHERE apa.activity_id = a.id
        )
        ORDER BY a.id
        """
    ).fetchall()
    for row in rows:
        project_id = row["project_id"] if row["project_id"] is not None else uncategorized_id
        is_manual = int(row["manual_override"] or 0)
        if is_manual:
            source = "manual"
        elif project_id == uncategorized_id:
            source = "uncategorized"
        elif row["resource_role"] == "anchor":
            source = "anchor_keyword"
        else:
            source = "anchor_context"
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], project_id, 100 if is_manual else 50, source, is_manual, now, now),
        )


def _ensure_resource(conn: sqlite3.Connection, now: str, identity: dict) -> int:
    row = conn.execute(
        "SELECT id FROM resource WHERE canonical_key = ?",
        (identity["canonical_key"],),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        """
        INSERT INTO resource(
            resource_role, resource_type, display_name, canonical_key,
            app_name, process_name, title_hint, default_project_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            identity["resource_role"],
            identity["resource_type"],
            identity["display_name"],
            identity["canonical_key"],
            identity.get("app_name"),
            identity.get("process_name"),
            identity.get("title_hint"),
            now,
            now,
        ),
    )
    return int(cur.lastrowid)


def _get_uncategorized_project_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
    if row:
        return int(row["id"])
    now = conn.execute("SELECT datetime('now', 'localtime') AS ts").fetchone()["ts"]
    cur = conn.execute(
        """
        INSERT INTO project(name, description, default_billable, is_archived, created_at, updated_at)
        VALUES (?, '', 1, 0, ?, ?)
        """,
        (UNCATEGORIZED_PROJECT, now, now),
    )
    return int(cur.lastrowid)
