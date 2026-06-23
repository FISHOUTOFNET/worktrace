from __future__ import annotations

import json

VALID_RESOURCE_KINDS = frozenset({
    "local_file",
    "office_document",
    "email",
    "browser_tab",
    "ide_file",
    "app",
    "system",
    "unknown",
})

VALID_RESOURCE_SUBTYPES = frozenset({
    "word_document",
    "spreadsheet",
    "presentation",
    "pdf",
    "text_file",
    "markdown_file",
    "csv_file",
    "code_file",
    "email_message",
    "email_file",
    "browser_page",
    "ide_workspace",
    "generic_app",
    "idle",
    "paused",
    "excluded",
    "error",
    "unknown",
})

FORBIDDEN_METADATA_KEYS = frozenset({
    "body",
    "html_body",
    "rtf_body",
    "text_body",
    "content",
    "page_content",
    "document_text",
    "email_body",
    "webpage_body",
    "clipboard_text",
})


def validate_resource_kind(value: str) -> str:
    if value not in VALID_RESOURCE_KINDS:
        raise ValueError(f"invalid resource_kind: {value!r}")
    return value


def validate_resource_subtype(value: str) -> str:
    if value not in VALID_RESOURCE_SUBTYPES:
        raise ValueError(f"invalid resource_subtype: {value!r}")
    return value


def safe_metadata_json(metadata: dict | None) -> str | None:
    if metadata is None:
        return None
    cleaned = {k: v for k, v in metadata.items() if k not in FORBIDDEN_METADATA_KEYS}
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)
