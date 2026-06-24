from __future__ import annotations

import json

import pytest

from worktrace.platforms.base import ActiveWindow
from worktrace.resources.detectors import (
    GenericAppDetector,
    ResourceDetectorRegistry,
    SystemDetector,
    detect_resource,
)
from worktrace.resources.resource_identity import (
    attach_resource_identity,
    infer_resource_for_activity,
    infer_resource_from_active_window,
)
from worktrace.resources.resource_policy import (
    safe_metadata_json,
    validate_resource_kind,
    validate_resource_subtype,
)
from worktrace.resources.types import DetectedResource


# ---------------------------------------------------------------------------
# 1. idle / paused / excluded / error -> system resource
# ---------------------------------------------------------------------------

class TestSystemDetector:
    @pytest.mark.parametrize(
        "process_name,expected_subtype,expected_display",
        [
            ("idle", "idle", "空闲"),
            ("paused", "paused", "已暂停"),
            ("excluded", "excluded", "已排除"),
            ("error", "error", "异常"),
        ],
    )
    def test_system_process_detected(self, process_name, expected_subtype, expected_display):
        aw = ActiveWindow(app_name="", process_name=process_name, window_title="")
        detector = SystemDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "system"
        assert result.resource_subtype == expected_subtype
        assert result.display_name == expected_display
        assert result.is_anchor is False
        assert result.identity_key == f"system:{expected_subtype}"

    def test_non_system_process_returns_none(self):
        aw = ActiveWindow(app_name="Chrome", process_name="chrome.exe", window_title="Google")
        detector = SystemDetector()
        assert detector.detect(aw) is None


# ---------------------------------------------------------------------------
# 2. Normal app -> app / generic_app fallback
# ---------------------------------------------------------------------------

class TestGenericAppDetector:
    def test_generic_app_with_app_name(self):
        aw = ActiveWindow(app_name="Chrome", process_name="chrome.exe", window_title="Search")
        detector = GenericAppDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "app"
        assert result.resource_subtype == "generic_app"
        assert result.display_name == "Chrome"
        assert result.identity_key.startswith("app:")
        assert result.is_anchor is False

    def test_generic_app_without_app_name_uses_process(self):
        aw = ActiveWindow(app_name="", process_name="chrome.exe", window_title="Search")
        detector = GenericAppDetector()
        result = detector.detect(aw)
        assert result.display_name == "chrome.exe"

    def test_generic_app_without_both_uses_unknown(self):
        aw = ActiveWindow(app_name="", process_name="", window_title="Something")
        detector = GenericAppDetector()
        result = detector.detect(aw)
        assert result.display_name == "未知应用"


# ---------------------------------------------------------------------------
# 3. Registry & detect_resource
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_registry_prefers_system_detector(self):
        registry = ResourceDetectorRegistry()
        registry.register(SystemDetector())
        registry.register(GenericAppDetector())
        aw = ActiveWindow(app_name="空闲", process_name="idle", window_title="用户空闲")
        result = registry.detect(aw)
        assert result.resource_kind == "system"
        assert result.resource_subtype == "idle"

    def test_registry_falls_back_to_generic(self):
        registry = ResourceDetectorRegistry()
        registry.register(SystemDetector())
        registry.register(GenericAppDetector())
        aw = ActiveWindow(app_name="WeChat", process_name="WeChat.exe", window_title="Chat")
        result = registry.detect(aw)
        assert result.resource_kind == "app"
        assert result.resource_subtype == "generic_app"

    def test_detect_resource_convenience_function(self):
        aw = ActiveWindow(app_name="微信", process_name="WeChat.exe", window_title="聊天")
        result = detect_resource(aw)
        assert result.resource_kind == "app"
        assert result.display_name == "微信"


# ---------------------------------------------------------------------------
# 4. attach_resource_identity fills resource_* and activity_* fields
# ---------------------------------------------------------------------------

class TestAttachResourceIdentity:
    def test_attaches_resource_fields_for_generic_app(self):
        row = {
            "app_name": "微信",
            "process_name": "WeChat.exe",
            "window_title": "聊天",
        }
        result = attach_resource_identity(row)
        assert result["resource_kind"] == "app"
        assert result["resource_subtype"] == "generic_app"
        assert result["resource_display_name"] == "微信"
        assert result["resource_identity_key"].startswith("app:")
        assert result["resource_is_anchor"] is False
        assert result["resource_path_hint"] is None
        assert result["resource_uri_host"] is None

    def test_attaches_resource_fields_for_browser_tab(self):
        row = {
            "app_name": "Chrome",
            "process_name": "chrome.exe",
            "window_title": "Search",
        }
        result = attach_resource_identity(row)
        assert result["activity_display_name"] == result["resource_display_name"]
        assert result["activity_identity_key"] == result["resource_identity_key"]
        # Browser tabs are anchor resources in the resource-first model.
        assert result["resource_is_anchor"] is True
        assert result["resource_path_hint"] is None

    def test_system_row_attaches_correctly(self):
        row = {
            "app_name": "空闲",
            "process_name": "idle",
            "window_title": "用户空闲",
        }
        result = attach_resource_identity(row)
        assert result["resource_kind"] == "system"
        assert result["resource_subtype"] == "idle"
        assert result["resource_display_name"] == "空闲"
        assert result["activity_display_name"] == "空闲"
        assert result["resource_is_anchor"] is False

    def test_does_not_mutate_original(self):
        row = {
            "app_name": "Chrome",
            "process_name": "chrome.exe",
            "window_title": "Search",
        }
        original_keys = set(row.keys())
        _ = attach_resource_identity(row)
        assert set(row.keys()) == original_keys


# ---------------------------------------------------------------------------
# 5. infer_resource_from_active_window / infer_resource_for_activity
# ---------------------------------------------------------------------------

class TestInferResource:
    def test_infer_from_active_window(self):
        aw = ActiveWindow(app_name="空闲", process_name="idle", window_title="用户空闲")
        result = infer_resource_from_active_window(aw)
        assert result.resource_kind == "system"

    def test_infer_for_activity(self):
        activity = {
            "app_name": "微信",
            "process_name": "WeChat.exe",
            "window_title": "聊天",
        }
        result = infer_resource_for_activity(activity)
        assert result.resource_kind == "app"
        assert result.display_name == "微信"


# ---------------------------------------------------------------------------
# 6. safe_metadata_json removes body-like fields
# ---------------------------------------------------------------------------

class TestSafeMetadataJson:
    def test_removes_forbidden_keys(self):
        metadata = {
            "title": "Report",
            "body": "secret content",
            "email_body": "secret email",
            "page_content": "secret page",
        }
        result = safe_metadata_json(metadata)
        assert result is not None
        parsed = json.loads(result)
        assert "title" in parsed
        assert "body" not in parsed
        assert "email_body" not in parsed
        assert "page_content" not in parsed

    def test_all_forbidden_keys_removed(self):
        metadata = {key: "x" for key in [
            "body", "html_body", "rtf_body", "text_body", "content",
            "page_content", "document_text", "email_body", "webpage_body",
            "clipboard_text",
        ]}
        result = safe_metadata_json(metadata)
        assert result is None

    def test_none_returns_none(self):
        assert safe_metadata_json(None) is None

    def test_empty_dict_returns_none(self):
        assert safe_metadata_json({}) is None

    def test_safe_keys_preserved(self):
        metadata = {"file_ext": ".docx", "line_count": 100}
        result = safe_metadata_json(metadata)
        assert result is not None
        parsed = json.loads(result)
        assert parsed == {"file_ext": ".docx", "line_count": 100}


# ---------------------------------------------------------------------------
# 7. validate_resource_kind / validate_resource_subtype
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_kinds(self):
        for kind in ["local_file", "office_document", "email", "browser_tab",
                      "ide_file", "app", "system", "unknown"]:
            assert validate_resource_kind(kind) == kind

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="invalid resource_kind"):
            validate_resource_kind("cloud_ai")

    def test_valid_subtypes(self):
        for st in ["word_document", "spreadsheet", "presentation", "pdf",
                    "text_file", "markdown_file", "csv_file", "code_file",
                    "email_message", "email_file", "browser_page",
                    "ide_workspace", "generic_app", "idle", "paused",
                    "excluded", "error", "unknown"]:
            assert validate_resource_subtype(st) == st

    def test_invalid_subtype_raises(self):
        with pytest.raises(ValueError, match="invalid resource_subtype"):
            validate_resource_subtype("ai_summary")
