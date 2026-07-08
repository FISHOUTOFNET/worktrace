from tests.support.db_helpers import assign_activity_project
from worktrace.services import activity_service, project_service, rule_service
from worktrace.db import get_connection
import pytest

pytestmark = [pytest.mark.db]


def test_rule_auto_classification(temp_db):
    pid = project_service.create_project("Writing")
    rule_id = rule_service.create_rule("Spec", pid)
    assert rule_id > 0
    assert rule_service.list_rules()[0]["keyword"] == "Spec"
    with get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert "rule" not in tables
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule WHERE pattern = 'Spec'").fetchone()["c"] == 1
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Architecture Spec.docx", start_time="2026-06-18 09:00:00"
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
    assign_activity_project(aid, manual_project, manual=True)
    rule_service.apply_rules_to_activity(aid)
    row = activity_service.get_activity(aid)
    assert row["project_id"] == manual_project
    assert row["manual_override"] == 1


def test_keyword_rule_can_be_disabled_and_deleted(temp_db):
    project = project_service.create_project("Rule")
    rule_id = rule_service.create_rule("Spec", project)

    rule_service.set_rule_enabled(rule_id, False)
    assert rule_service.list_rules()[0]["enabled"] == 0

    rule_service.delete_rule(rule_id)
    assert rule_service.list_rules() == []
