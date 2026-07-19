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

CREATE INDEX IF NOT EXISTS idx_history_mutation_job_status
ON history_mutation_job(status, updated_at, id);

CREATE INDEX IF NOT EXISTS idx_history_mutation_job_rule_lookup
ON history_mutation_job_rule(rule_type, rule_id, job_id);

CREATE INDEX IF NOT EXISTS idx_activity_inference_job_runnable
ON activity_inference_job(status, next_attempt_at, activity_id);

CREATE INDEX IF NOT EXISTS idx_startup_recovery_job_runnable
ON startup_recovery_job(status, next_attempt_at, id);

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

CREATE TRIGGER IF NOT EXISTS project_reserved_name_insert
BEFORE INSERT ON project
WHEN NEW.name IN ('未归类', '排除规则') AND NEW.created_by <> 'system'
BEGIN
    SELECT RAISE(ABORT, 'reserved_project_name');
END;

CREATE TRIGGER IF NOT EXISTS project_reserved_name_update
BEFORE UPDATE OF name, created_by ON project
WHEN NEW.name IN ('未归类', '排除规则') AND NEW.created_by <> 'system'
BEGIN
    SELECT RAISE(ABORT, 'reserved_project_name');
END;

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
