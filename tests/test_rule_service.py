from worktrace.services import activity_service, project_service, rule_service


def test_rule_auto_classification(temp_db):
    pid = project_service.create_project("Writing")
    rule_service.create_rule("Spec", pid)
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Architecture Spec", start_time="2026-06-18 09:00:00"
    )
    rule_service.apply_rules_to_activity(aid)
    row = activity_service.get_activity(aid)
    assert row["project_id"] == pid
    assert row["auto_classified"] == 1


def test_manual_override_prevents_rule_overwrite(temp_db):
    manual_project = project_service.create_project("Manual")
    rule_project = project_service.create_project("Rule")
    rule_service.create_rule("Spec", rule_project)
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )
    activity_service.update_activity_project(aid, manual_project, manual=True)
    rule_service.apply_rules_to_activity(aid)
    row = activity_service.get_activity(aid)
    assert row["project_id"] == manual_project
    assert row["manual_override"] == 1
