CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    language TEXT NOT NULL DEFAULT '中文',
    is_archived INTEGER NOT NULL DEFAULT 0,
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
    auto_classified INTEGER NOT NULL DEFAULT 0,
    manual_override INTEGER NOT NULL DEFAULT 0,
    project_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id)
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activity_log(id),
    FOREIGN KEY (project_id) REFERENCES project(id)
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

CREATE TABLE IF NOT EXISTS project_session_note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    first_activity_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    adjusted_duration_seconds INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (first_activity_id) REFERENCES activity_log(id),
    UNIQUE(report_date, first_activity_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_time
ON activity_log(start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_session_boundary_time
ON session_boundary(occurred_at);

CREATE INDEX IF NOT EXISTS idx_activity_status
ON activity_log(status);

CREATE INDEX IF NOT EXISTS idx_activity_project
ON activity_log(project_id);

CREATE INDEX IF NOT EXISTS idx_folder_project_rule_key
ON folder_project_rule(normalized_folder_key);

CREATE INDEX IF NOT EXISTS idx_folder_project_rule_project
ON folder_project_rule(project_id);

CREATE INDEX IF NOT EXISTS idx_folder_rule_index_status
ON folder_rule_index_state(status, refresh_requested);

CREATE INDEX IF NOT EXISTS idx_folder_rule_file_index_name
ON folder_rule_file_index(normalized_file_name);

CREATE INDEX IF NOT EXISTS idx_folder_rule_file_index_rule_name
ON folder_rule_file_index(folder_rule_id, normalized_file_name);

CREATE INDEX IF NOT EXISTS idx_folder_rule_file_index_path
ON folder_rule_file_index(normalized_path_key);

CREATE INDEX IF NOT EXISTS idx_assignment_project
ON activity_project_assignment(project_id);

CREATE INDEX IF NOT EXISTS idx_assignment_source_manual
ON activity_project_assignment(source, is_manual);

CREATE INDEX IF NOT EXISTS idx_project_rule_pattern
ON project_rule(pattern);

CREATE INDEX IF NOT EXISTS idx_clipboard_event_activity
ON activity_clipboard_event(activity_id);

CREATE INDEX IF NOT EXISTS idx_clipboard_event_time
ON activity_clipboard_event(copied_at);

CREATE INDEX IF NOT EXISTS idx_clipboard_event_sequence
ON activity_clipboard_event(clipboard_sequence);

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_resource_activity
ON activity_resource(activity_id);

CREATE INDEX IF NOT EXISTS idx_activity_resource_identity
ON activity_resource(identity_key);

CREATE INDEX IF NOT EXISTS idx_activity_resource_kind
ON activity_resource(resource_kind, resource_subtype);

CREATE INDEX IF NOT EXISTS idx_activity_resource_path
ON activity_resource(path_key);

CREATE INDEX IF NOT EXISTS idx_activity_resource_host
ON activity_resource(uri_host);

CREATE INDEX IF NOT EXISTS idx_project_session_note_key
ON project_session_note(report_date, first_activity_id);
