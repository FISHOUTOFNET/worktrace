CREATE INDEX IF NOT EXISTS idx_activity_time
ON activity_log(start_time, end_time);

CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_log_single_open
ON activity_log((1))
WHERE end_time IS NULL;

CREATE INDEX IF NOT EXISTS idx_session_boundary_time
ON session_boundary(occurred_at);

CREATE INDEX IF NOT EXISTS idx_activity_status
ON activity_log(status);

CREATE INDEX IF NOT EXISTS idx_folder_project_rule_key
ON folder_project_rule(normalized_folder_key);

CREATE INDEX IF NOT EXISTS idx_folder_project_rule_project
ON folder_project_rule(project_id);

CREATE INDEX IF NOT EXISTS idx_folder_rule_index_status
ON folder_rule_index_state(status, refresh_requested);

CREATE INDEX IF NOT EXISTS idx_folder_rule_index_generation
ON folder_rule_index_state(active_generation, building_generation);

CREATE INDEX IF NOT EXISTS idx_folder_rule_file_index_name
ON folder_rule_file_index(normalized_file_name);

CREATE INDEX IF NOT EXISTS idx_folder_rule_file_index_rule_name
ON folder_rule_file_index(folder_rule_id, generation, normalized_file_name);

CREATE INDEX IF NOT EXISTS idx_folder_rule_file_index_path
ON folder_rule_file_index(generation, normalized_path_key);

CREATE TRIGGER IF NOT EXISTS reset_empty_active_folder_generation
AFTER DELETE ON folder_rule_file_index
WHEN NOT EXISTS (
        SELECT 1 FROM folder_rule_file_index remaining
        WHERE remaining.folder_rule_id = OLD.folder_rule_id
          AND remaining.generation = OLD.generation
     )
 AND EXISTS (
        SELECT 1 FROM folder_rule_index_state state
        WHERE state.folder_rule_id = OLD.folder_rule_id
          AND state.active_generation = OLD.generation
     )
BEGIN
    UPDATE folder_rule_index_state
    SET status = 'pending', valid_from = NULL, active_generation = NULL,
        building_generation = NULL, build_status = 'pending', last_error = NULL,
        last_indexed_at = NULL, last_checked_at = NULL, file_count = 0,
        error_message = NULL, refresh_requested = 1
    WHERE folder_rule_id = OLD.folder_rule_id;
END;

CREATE TRIGGER IF NOT EXISTS normalize_pending_folder_generation
AFTER UPDATE OF status ON folder_rule_index_state
WHEN NEW.status = 'pending'
 AND (
        NEW.valid_from IS NOT NULL
        OR NEW.active_generation IS NOT NULL
        OR NEW.building_generation IS NOT NULL
        OR NEW.build_status IS NOT 'pending'
        OR NEW.last_error IS NOT NULL
        OR NEW.last_indexed_at IS NOT NULL
        OR NEW.last_checked_at IS NOT NULL
        OR NEW.file_count <> 0
        OR NEW.error_message IS NOT NULL
     )
BEGIN
    UPDATE folder_rule_index_state
    SET valid_from = NULL, active_generation = NULL,
        building_generation = NULL, build_status = 'pending', last_error = NULL,
        last_indexed_at = NULL, last_checked_at = NULL, file_count = 0,
        error_message = NULL, refresh_requested = 1
    WHERE folder_rule_id = NEW.folder_rule_id;
END;

CREATE INDEX IF NOT EXISTS idx_history_mutation_job_status
ON history_mutation_job(status, updated_at, id);

CREATE INDEX IF NOT EXISTS idx_history_mutation_job_rule_lookup
ON history_mutation_job_rule(rule_type, rule_id, job_id);

CREATE TRIGGER IF NOT EXISTS cleanup_history_jobs_after_project_reset
AFTER DELETE ON project
WHEN OLD.created_by = 'system'
 AND OLD.name IN ('未归类', '已排除')
BEGIN
    DELETE FROM history_mutation_job;
END;

CREATE INDEX IF NOT EXISTS idx_assignment_project
ON activity_project_assignment(project_id);

CREATE INDEX IF NOT EXISTS idx_assignment_source_manual
ON activity_project_assignment(source, is_manual);

CREATE INDEX IF NOT EXISTS idx_assignment_source_rule
ON activity_project_assignment(source_rule_type, source_rule_id, is_manual);

CREATE INDEX IF NOT EXISTS idx_report_session_operation_date_sequence
ON report_session_operation(report_date, sequence, id);

CREATE INDEX IF NOT EXISTS idx_report_session_operation_instance
ON report_session_operation(report_date, source_instance_key);

CREATE INDEX IF NOT EXISTS idx_report_session_operation_target
ON report_session_operation(report_date, target_instance_key);

CREATE INDEX IF NOT EXISTS idx_report_mutation_request_operation
ON report_mutation_request(operation_id);

CREATE INDEX IF NOT EXISTS idx_report_session_operation_member_activity
ON report_session_operation_member(activity_id, report_date);

CREATE INDEX IF NOT EXISTS idx_report_session_operation_member_role
ON report_session_operation_member(operation_id, role);

CREATE INDEX IF NOT EXISTS idx_project_rule_pattern
ON project_rule(pattern);

CREATE INDEX IF NOT EXISTS idx_clipboard_event_activity
ON activity_clipboard_event(activity_id);

CREATE INDEX IF NOT EXISTS idx_clipboard_event_time
ON activity_clipboard_event(copied_at);

CREATE INDEX IF NOT EXISTS idx_clipboard_event_sequence
ON activity_clipboard_event(clipboard_sequence);

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
