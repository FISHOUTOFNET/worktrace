from __future__ import annotations


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
    """Return a display-safe activity/resource name that never falls back to
    raw ``window_title``.

    The fallback chain surfaces the most sanitized field first:

    1. ``resource_display_name`` — already sanitized by the resource service
       (basename for files, cleaned title for browsers, app name for generic
       apps).
    2. ``activity_display_name`` — set to ``resource_display_name`` or
       ``app_name`` by the resource service, so still safe.
    3. ``app_name`` — application name only, no path or window title.
    4. ``process_name`` — process executable name only.

    The raw ``window_title`` column is deliberately skipped because it can
    contain full file paths, URLs, or email subjects. ``file_path_hint`` and
    ``note`` are also skipped. If all safe fields are empty the row falls
    back to ``"未知"`` rather than leaking sensitive metadata.

    Used by the WebView bridge Timeline detail rows and the CSV export so
    the service layer does not reverse-depend on the bridge.
    """
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
