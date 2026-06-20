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
