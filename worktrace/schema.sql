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
    file_name TEXT NOT NULL,
    normalized_file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    normalized_path_key TEXT NOT NULL,
    mtime REAL,
    size INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (folder_rule_id) REFERENCES folder_project_rule(id) ON DELETE CASCADE,
    UNIQUE(folder_rule_id, normalized_path_key)
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
            'keyword_rule',
            'anchor_context',
            'same_project_context',
            'clipboard_transition_context',
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
    base_instance_key TEXT NOT NULL,
    base_expected_revision TEXT NOT NULL,
    target_instance_key TEXT,
    target_expected_revision TEXT,
    direction TEXT CHECK(direction IS NULL OR direction IN ('previous', 'next')),
    replay_order INTEGER NOT NULL,
    match_state TEXT NOT NULL DEFAULT 'active' CHECK(match_state IN ('active', 'conflict', 'orphaned', 'superseded')),
    reverts_operation_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(report_date, replay_order),
    FOREIGN KEY(reverts_operation_id) REFERENCES report_session_operation(id)
);

CREATE TABLE IF NOT EXISTS report_mutation_request (
    request_id TEXT PRIMARY KEY,
    input_signature TEXT NOT NULL,
    outcome_type TEXT NOT NULL CHECK(outcome_type IN ('operation_committed', 'no_op')),
    operation_id INTEGER,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    committed_at TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS report_session_operation_dependency (
    parent_operation_id INTEGER NOT NULL,
    child_operation_id INTEGER NOT NULL,
    PRIMARY KEY(parent_operation_id, child_operation_id),
    FOREIGN KEY(parent_operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE,
    FOREIGN KEY(child_operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_session_operation_supersession (
    superseded_operation_id INTEGER NOT NULL,
    superseding_operation_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(superseded_operation_id, superseding_operation_id),
    CHECK(superseded_operation_id <> superseding_operation_id),
    FOREIGN KEY(superseded_operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE,
    FOREIGN KEY(superseding_operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE
);

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
