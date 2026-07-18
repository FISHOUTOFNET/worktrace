"""Current encrypted-backup contracts plus retained cross-version coverage."""

from __future__ import annotations

import json

from tests import secure_backup_service_contracts as _contracts

pytestmark = _contracts.pytestmark

# Retain the established encryption, replacement, rollback, privacy, and API
# contracts. Only tests whose published payload semantics changed in v5 are
# replaced below.
for _name in dir(_contracts):
    if _name.startswith("test_"):
        globals()[_name] = getattr(_contracts, _name)


def test_export_payload_contains_required_tables(temp_db, tmp_path):
    _contracts._seed_test_data()
    payload = _contracts.secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))

    assert data["format"] == "worktrace-local-data"
    assert data["version"] == 5
    assert data["schema_version"] == "11"
    tables = data["tables"]
    for required in [
        "project",
        "activity_log",
        "settings",
        "session_boundary",
        "folder_project_rule",
        "folder_rule_index_state",
        "project_rule",
        "activity_project_assignment",
        "activity_clipboard_event",
        "report_session_operation",
        "report_mutation_request",
        "report_session_operation_member",
        "activity_resource",
        "activity_inference_job",
    ]:
        assert required in tables, f"missing table {required} in payload"


def test_published_v8_backup_remains_importable(temp_db, tmp_path):
    _contracts._seed_test_data()
    payload = json.loads(
        _contracts.secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["version"] = 4
    payload["schema_version"] = "8"
    payload["schema_fingerprint"] = (
        "3fd5ae980749886a04f7f9170669a606fa80d6b554924d0ad29b457b0c51deac"
    )
    payload["tables"].pop("activity_inference_job", None)
    out = tmp_path / "published-v8.wtbackup"
    out.write_bytes(
        _contracts.create_encrypted_backup(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            "passphrase",
            "legacy-test",
        )
    )

    result = _contracts.secure_backup_service.import_encrypted_backup(
        out,
        "passphrase",
    )

    assert result.mode == "replace"
