CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
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
    resource_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id),
    FOREIGN KEY (resource_id) REFERENCES resource(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_role TEXT NOT NULL CHECK (
        resource_role IN ('anchor', 'auxiliary')
    ),
    resource_type TEXT NOT NULL CHECK (
        resource_type IN ('file', 'app')
    ),
    display_name TEXT NOT NULL,
    canonical_key TEXT NOT NULL UNIQUE,
    app_name TEXT,
    process_name TEXT,
    title_hint TEXT,
    full_path TEXT,
    parent_dir TEXT,
    file_stem TEXT,
    default_project_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (default_project_id) REFERENCES project(id)
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
            'folder_rule',
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

CREATE INDEX IF NOT EXISTS idx_activity_time
ON activity_log(start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_activity_status
ON activity_log(status);

CREATE INDEX IF NOT EXISTS idx_activity_project
ON activity_log(project_id);

CREATE INDEX IF NOT EXISTS idx_resource_key
ON resource(canonical_key);

CREATE INDEX IF NOT EXISTS idx_resource_role_type
ON resource(resource_role, resource_type);

CREATE INDEX IF NOT EXISTS idx_resource_default_project
ON resource(default_project_id);

CREATE INDEX IF NOT EXISTS idx_resource_path
ON resource(full_path, parent_dir);

CREATE INDEX IF NOT EXISTS idx_folder_project_rule_key
ON folder_project_rule(normalized_folder_key);

CREATE INDEX IF NOT EXISTS idx_folder_project_rule_project
ON folder_project_rule(project_id);

CREATE INDEX IF NOT EXISTS idx_assignment_project
ON activity_project_assignment(project_id);

CREATE INDEX IF NOT EXISTS idx_assignment_source_manual
ON activity_project_assignment(source, is_manual);

CREATE INDEX IF NOT EXISTS idx_project_rule_pattern
ON project_rule(pattern);
