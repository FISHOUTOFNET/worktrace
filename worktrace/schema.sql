CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    language TEXT NOT NULL DEFAULT '中文',
    is_archived INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT 'user' CHECK (
        created_by IN ('system', 'user')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_seconds INTEGER,
    app_name TEXT NOT NULL,
    process_name TEXT NOT NULL,
    window_title TEXT NOT NULL,
    file_path_hint TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('normal', 'idle', 'paused', 'excluded', 'error')
    ),
    source TEXT NOT NULL CHECK (
        source IN ('auto', 'manual', 'system')
    ),
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_boundary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS folder_project_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL,
    normalized_folder_key TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL,
    recursive INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id)
);

CREATE TABLE IF NOT EXISTS folder_rule_index_state (
    folder_rule_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'indexing', 'ready', 'stale', 'error')
    ),
    valid_from TEXT,
    active_generation INTEGER,
    building_generation INTEGER,
    build_status TEXT CHECK (
        build_status IS NULL OR build_status IN ('pending', 'indexing', 'ready', 'stale', 'error')
    ),
    last_error TEXT,
    last_indexed_at TEXT,
    last_checked_at TEXT,
    file_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    refresh_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (folder_rule_id) REFERENCES folder_project_rule(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS folder_rule_file_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_rule_id INTEGER NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    file_name TEXT NOT NULL,
    normalized_file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    normalized_path_key TEXT NOT NULL,
    mtime REAL,
    size INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (folder_rule_id) REFERENCES folder_project_rule(id) ON DELETE CASCADE,
    UNIQUE(folder_rule_id, generation, normalized_path_key)
);

CREATE TABLE IF NOT EXISTS project_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL CHECK (
        rule_type IN ('keyword')
    ),
    pattern TEXT NOT NULL,
    normalized_pattern TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT 'user' CHECK (
        created_by IN ('system', 'user')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id)
);

CREATE TABLE IF NOT EXISTS history_mutation_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (
        kind IN ('rule_backfill', 'rule_remove', 'rule_delete')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
    ),
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    cutoff_activity_id INTEGER NOT NULL DEFAULT 0,
    cursor_activity_id INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history_mutation_job_rule (
    job_id INTEGER NOT NULL,
    rule_type TEXT NOT NULL CHECK(rule_type IN ('folder', 'keyword')),
    rule_id INTEGER NOT NULL,
    rule_version TEXT NOT NULL,
    PRIMARY KEY(job_id, rule_type, rule_id),
    FOREIGN KEY(job_id) REFERENCES history_mutation_job(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS activity_project_assignment (
    activity_id INTEGER PRIMARY KEY,
    project_id INTEGER,
    confidence INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL CHECK (
        source IN (
            'manual',
            'keyword_rule',
            'folder_rule',
            'midnight_anchor',
            'suggested_project_name',
            'uncategorized'
        )
    ),
    is_manual INTEGER NOT NULL DEFAULT 0,
    suggested_project_name TEXT,
    source_rule_type TEXT NULL CHECK (
        source_rule_type IS NULL OR source_rule_type IN ('folder', 'keyword')
    ),
    source_rule_id INTEGER NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activity_log(id),
    FOREIGN KEY (project_id) REFERENCES project(id)
);

CREATE TABLE IF NOT EXISTS report_session_operation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('edit_session', 'hide_session', 'merge_sessions', 'copy_session', 'hide_activity', 'split_session')),
    source_instance_key TEXT NOT NULL,
    source_expected_revision TEXT NOT NULL,
    target_instance_key TEXT,
    target_expected_revision TEXT,
    direction TEXT CHECK(direction IS NULL OR direction IN ('previous', 'next')),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    undo_of_operation_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    created_at TEXT NOT NULL,
    UNIQUE(report_date, sequence),
    UNIQUE(undo_of_operation_id),
    CHECK(
        (operation_type = 'merge_sessions'
         AND target_instance_key IS NOT NULL
         AND target_expected_revision IS NOT NULL
         AND direction IS NOT NULL
         AND undo_of_operation_id IS NULL)
        OR
        (operation_type = 'split_session'
         AND target_instance_key IS NULL
         AND target_expected_revision IS NULL
         AND direction IS NULL
         AND undo_of_operation_id IS NOT NULL)
        OR
        (operation_type NOT IN ('merge_sessions', 'split_session')
         AND target_instance_key IS NULL
         AND target_expected_revision IS NULL
         AND direction IS NULL
         AND undo_of_operation_id IS NULL)
    ),
    CHECK(undo_of_operation_id IS NULL OR undo_of_operation_id <> id),
    FOREIGN KEY(undo_of_operation_id) REFERENCES report_session_operation(id)
);

CREATE TABLE IF NOT EXISTS report_mutation_request (
    request_id TEXT PRIMARY KEY,
    input_signature TEXT NOT NULL,
    outcome_type TEXT NOT NULL CHECK(outcome_type IN ('operation_committed', 'no_op')),
    operation_id INTEGER,
    result_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(result_json)),
    created_at TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    CHECK(
        (outcome_type = 'operation_committed' AND operation_id IS NOT NULL)
        OR (outcome_type = 'no_op' AND operation_id IS NULL)
    ),
    FOREIGN KEY(operation_id) REFERENCES report_session_operation(id)
);

CREATE TABLE IF NOT EXISTS report_session_operation_member (
    operation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('source', 'target', 'affected')),
    activity_id INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    slice_start_time TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(operation_id, role, activity_id, report_date, slice_start_time),
    FOREIGN KEY(operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE,
    FOREIGN KEY(activity_id) REFERENCES activity_log(id)
);

CREATE TRIGGER IF NOT EXISTS validate_report_split_operation
BEFORE INSERT ON report_session_operation
WHEN NEW.operation_type = 'split_session'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM report_session_operation original
        WHERE original.id = NEW.undo_of_operation_id
          AND original.operation_type = 'merge_sessions'
          AND original.report_date = NEW.report_date
          AND original.sequence < NEW.sequence
    ) THEN RAISE(ABORT, 'invalid_split_operation') END;
END;

CREATE TRIGGER IF NOT EXISTS validate_report_operation_receipt_members
BEFORE INSERT ON report_mutation_request
WHEN NEW.outcome_type = 'operation_committed'
BEGIN
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM report_session_operation_member
        WHERE operation_id = NEW.operation_id AND role = 'source'
    ) = 0 THEN RAISE(ABORT, 'missing_source_members') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM report_session_operation operation
        WHERE operation.id = NEW.operation_id
          AND (
              (operation.operation_type = 'merge_sessions' AND (
                  (SELECT COUNT(*) FROM report_session_operation_member
                   WHERE operation_id = NEW.operation_id AND role = 'target') = 0
                  OR (SELECT COUNT(*) FROM report_session_operation_member
                      WHERE operation_id = NEW.operation_id AND role = 'affected') <> 0
              ))
              OR
              (operation.operation_type = 'hide_activity' AND (
                  (SELECT COUNT(*) FROM report_session_operation_member
                   WHERE operation_id = NEW.operation_id AND role = 'affected') = 0
                  OR (SELECT COUNT(*) FROM report_session_operation_member
                      WHERE operation_id = NEW.operation_id AND role = 'target') <> 0
              ))
              OR
              (operation.operation_type NOT IN ('merge_sessions', 'hide_activity') AND (
                  (SELECT COUNT(*) FROM report_session_operation_member
                   WHERE operation_id = NEW.operation_id AND role IN ('target', 'affected')) <> 0
              ))
          )
    ) THEN RAISE(ABORT, 'invalid_operation_member_cardinality') END;
END;

CREATE TABLE IF NOT EXISTS activity_clipboard_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    copied_at TEXT NOT NULL,
    app_name TEXT NOT NULL,
    process_name TEXT NOT NULL,
    window_title TEXT NOT NULL,
    file_path_hint TEXT,
    copied_text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    text_length INTEGER NOT NULL DEFAULT 0,
    clipboard_sequence INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activity_log(id)
);

CREATE TABLE IF NOT EXISTS activity_resource (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    resource_kind TEXT NOT NULL CHECK (
        resource_kind IN (
            'local_file',
            'office_document',
            'email',
            'browser_tab',
            'ide_file',
            'app',
            'system',
            'unknown'
        )
    ),
    resource_subtype TEXT NOT NULL,
    display_name TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    is_anchor INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    app_name TEXT NOT NULL,
    process_name TEXT NOT NULL,
    window_title TEXT NOT NULL,
    path_hint TEXT,
    path_key TEXT,
    uri_scheme TEXT,
    uri_host TEXT,
    uri_hint TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activity_log(id) ON DELETE CASCADE
);
