CREATE TABLE IF NOT EXISTS data_generation_state (
    namespace TEXT PRIMARY KEY CHECK(length(trim(namespace)) > 0),
    generation INTEGER NOT NULL CHECK(generation >= 0)
);

INSERT INTO data_generation_state(namespace, generation)
VALUES
    ('report_structure', 0),
    ('classification_catalog', 0),
    ('settings', 0),
    ('privacy_catalog', 0),
    ('database_replacement', 0)
ON CONFLICT(namespace) DO NOTHING;

CREATE TABLE IF NOT EXISTS activity_resource_repair_job (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    policy_version INTEGER NOT NULL CHECK(policy_version > 0),
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    cursor_activity_id INTEGER NOT NULL DEFAULT 0 CHECK(cursor_activity_id >= 0),
    processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count >= 0),
    repaired_count INTEGER NOT NULL DEFAULT 0 CHECK(repaired_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
    unknown_count INTEGER NOT NULL DEFAULT 0 CHECK(unknown_count >= 0),
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS activity_inference_job (
    activity_id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL CHECK(reason = 'closed_activity'),
    status TEXT NOT NULL CHECK(status IN ('pending', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    next_attempt_at TEXT,
    last_error_code TEXT CHECK(
        last_error_code IS NULL OR last_error_code IN (
            'data_repair_required',
            'database_busy',
            'database_generation_changed',
            'secure_import_in_progress',
            'unexpected_failure'
        )
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(activity_id) REFERENCES activity_log(id) ON DELETE CASCADE
);
