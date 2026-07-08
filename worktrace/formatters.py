from __future__ import annotations

from .constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    UNCATEGORIZED_PROJECT,
)


def format_duration(seconds: int | None) -> str:
    seconds = max(0, int(seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_current_duration(seconds: int | None) -> str:
    return format_duration(seconds)


def format_project_label(name: str | None, description: str | None = "") -> str:
    cleaned_name = str(name or "").strip() or "Unknown"
    cleaned_description = " ".join(str(description or "").split())
    if not cleaned_description:
        return cleaned_name
    return f"{cleaned_name} ({cleaned_description})"


_STATUS_LABELS: dict[str, str] = {
    STATUS_NORMAL: "正常",
    STATUS_IDLE: "空闲",
    STATUS_PAUSED: "已暂停",
    STATUS_EXCLUDED: "已排除",
    STATUS_ERROR: "异常",
}


def format_status_label(status_code: str | None) -> str:
    return _STATUS_LABELS.get(str(status_code or "").strip(), "未知状态")


def format_activity_project_cell(row: dict) -> str:
    """Format the formal ``项目`` cell for a CSV / export row.

    Report-visible attribution surfaces the project name. Candidate /
    uncategorized / unknown sources stay uncategorized. Never falls back
    to raw project fields.
    """
    if str(row.get("status") or "").strip() != STATUS_NORMAL:
        return "—"
    if not row.get("is_report_project"):
        return UNCATEGORIZED_PROJECT
    return str(row.get("report_project_name") or UNCATEGORIZED_PROJECT).strip() or UNCATEGORIZED_PROJECT


_RESOURCE_TYPE_LABELS: dict[str, str] = {
    "office_document/word_document": "Word 文档",
    "office_document/spreadsheet": "表格",
    "office_document/presentation": "演示文稿",
    "office_document/pdf": "PDF",
    "local_file/pdf": "PDF",
    "local_file/code_file": "代码文件",
    "local_file/text_file": "文本文件",
    "local_file/markdown_file": "Markdown 文件",
    "local_file/csv_file": "CSV 文件",
    "email/email_message": "邮件",
    "email/email_file": "邮件文件",
    "browser_tab/browser_page": "浏览器标签页",
    "ide_file/code_file": "IDE 文件",
    "ide_file/ide_workspace": "IDE 工作区",
    "app/generic_app": "普通应用",
    "system/idle": "空闲",
    "system/paused": "已暂停",
    "system/excluded": "已排除",
    "system/error": "异常",
}


def format_resource_type(resource_kind: str | None, resource_subtype: str | None) -> str:
    kind = str(resource_kind or "").strip()
    subtype = str(resource_subtype or "").strip()
    key = f"{kind}/{subtype}"
    return _RESOURCE_TYPE_LABELS.get(key, kind or "未知")


def format_activity_display_name(row: dict) -> str:
    """Return the best display name for an activity row, preferring resource info."""
    name = row.get("resource_display_name") or row.get("activity_display_name")
    if name and str(name).strip():
        return str(name).strip()
    # Fallback chain: window_title -> app_name -> process_name
    for key in ("window_title", "app_name", "process_name"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return "未知"


def format_safe_display_name(row: dict) -> str:
    """Return a display-safe activity/resource name that never falls back to"""
    for key in (
        "resource_display_name",
        "activity_display_name",
        "app_name",
        "process_name",
    ):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return "未知"
