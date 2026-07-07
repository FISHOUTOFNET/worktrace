from __future__ import annotations
from tests.support.db_helpers import assign_activity_project

from worktrace.services import (
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_service,
)


def create_project(name: str = "Client") -> int:
    return project_service.create_project(name)


def create_keyword_rule(project_id: int, keyword: str = "Spec") -> int:
    return rule_service.create_rule(keyword, project_id)


def create_folder_rule(
    project_id: int,
    folder_path: str = "D:\\Client",
    *,
    recursive: bool = True,
) -> int:
    return folder_rule_service.create_or_update_folder_rule(
        folder_path, project_id, recursive=recursive
    )


def assign_activity_manually(activity_id: int, project_id: int) -> None:
    assign_activity_project(activity_id, project_id, manual=True)


def assign_activity_automatically(activity_id: int) -> dict | None:
    return project_inference_service.assign_project_for_activity(activity_id)
