from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from ..services import folder_rule_service, project_service, resource_service, rule_service
from . import design
from .project_rule_dialog import RULE_TYPE_LABELS, open_project_rule_dialog


class ProjectRulesView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._rules_signature: tuple[tuple, ...] | None = None
        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text="项目规则", variant="title").grid(row=0, column=0, sticky="w")
        design.label(
            header,
            text="按项目管理文件、文件夹和关键词规则，让时间详情自动归到正确上下文。",
            variant="caption",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        design.button(actions, text="新建项目/规则", command=self.open_new_rule_dialog).pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.rules_section = design.card(self.scroll)
        self.rules_section.grid(row=0, column=0, sticky="ew")
        self.rules_section.grid_columnconfigure(0, weight=1)
        rules_header = ctk.CTkFrame(self.rules_section, fg_color="transparent")
        rules_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        rules_header.grid_columnconfigure(0, weight=1)
        design.label(rules_header, text="项目规则", variant="section").grid(row=0, column=0, sticky="w")
        design.button(
            rules_header,
            text="新建项目/规则",
            variant="subtle",
            width=128,
            command=self.open_new_rule_dialog,
        ).grid(row=0, column=1, sticky="e")
        self.rules_frame = ctk.CTkFrame(self.rules_section, fg_color="transparent")
        self.rules_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.rules_frame.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        self.refresh_rules()

    def refresh_project_bindings(self) -> None:
        self.refresh_rules()

    def refresh_rules(self) -> None:
        projects = project_service.list_project_bindings()
        signature = tuple(_project_signature(project) for project in projects)
        if signature == self._rules_signature:
            return
        self._rules_signature = signature
        _clear_children(self.rules_frame)
        if not projects:
            _empty_row(self.rules_frame, "暂无用户项目。请使用“新建项目/规则”创建第一个项目。")
            return
        for row_index, project in enumerate(projects):
            self._project_group(self.rules_frame, row_index, project)

    def _project_group(self, parent, row_index: int, project: dict) -> None:
        group = design.section(parent, fg_color=design.CARD_SUBTLE_BG)
        group.grid(row=row_index, column=0, sticky="ew", padx=6, pady=6)
        group.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(group, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text=project["name"], variant="section").grid(row=0, column=0, sticky="w")
        design.label(header, text=_project_rule_summary(project), variant="caption").grid(row=1, column=0, sticky="w", pady=(2, 0))
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        design.button(
            actions,
            text="新建规则",
            variant="subtle",
            width=82,
            command=lambda name=str(project["name"]): self.open_new_rule_dialog(initial_project_name=name),
        ).pack(side="left", padx=(0, 8))
        design.button(
            actions,
            text="删除项目",
            variant="danger",
            width=82,
            command=lambda item=project: self.delete_project(item),
        ).pack(side="left")

        rules = _rules_for_project(project)
        rules_frame = ctk.CTkFrame(group, fg_color="transparent")
        rules_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        rules_frame.grid_columnconfigure(1, weight=1)
        if not rules:
            design.label(rules_frame, text="暂无规则", variant="caption").grid(row=0, column=0, sticky="w", padx=6, pady=8)
            return
        for index, rule in enumerate(rules):
            self._rule_row(rules_frame, index, rule)

    def _rule_row(self, parent, row_index: int, rule: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color=design.CARD_BG, corner_radius=design.RADIUS_MD, border_width=1, border_color=design.BORDER)
        row.grid(row=row_index, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        row.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkLabel(
            row,
            text=RULE_TYPE_LABELS[rule["kind"]],
            font=design.FONT_CAPTION_STRONG,
            text_color=design.ACCENT,
            fg_color=design.ACCENT_SOFT,
            corner_radius=999,
            height=26,
            width=58,
        )
        badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=12, pady=9)
        design.label(row, text=rule["target"], variant="strong", anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(0, 12), pady=(9, 2)
        )
        design.label(row, text=_rule_detail_text(rule), variant="caption", anchor="w").grid(
            row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 9)
        )
        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, sticky="e", padx=10, pady=8)
        if rule["kind"] in {"folder", "keyword"}:
            action_text = "禁用" if bool(rule.get("enabled")) else "启用"
            design.button(
                actions,
                text=action_text,
                width=62,
                variant="subtle",
                command=lambda item=rule: self.set_rule_enabled(item),
            ).pack(side="left", padx=(0, 6))
        design.button(
            actions,
            text="删除",
            width=62,
            variant="danger",
            command=lambda item=rule: self.delete_rule(item),
        ).pack(side="left")

    def _combined_rules(self) -> list[dict]:
        rules: list[dict] = []
        for project in project_service.list_project_bindings():
            rules.extend(_rules_for_project(project))
        return rules

    def create_project(self) -> None:
        self.open_new_rule_dialog()

    def add_folder_rule(self) -> None:
        self.open_new_rule_dialog("folder")

    def open_new_rule_dialog(
        self,
        initial_type: str = "file",
        *,
        initial_project_name: str | None = None,
        initial_target: str = "",
    ) -> None:
        open_project_rule_dialog(
            self,
            initial_type=initial_type,
            initial_target=initial_target,
            initial_project_name=initial_project_name,
            on_saved=lambda _result: self._after_project_rule_saved(),
        )

    def _after_project_rule_saved(self) -> None:
        self._invalidate()
        self.refresh()

    def set_rule_enabled(self, rule: dict) -> None:
        if rule["kind"] == "folder":
            folder_rule_service.set_folder_rule_enabled(int(rule["id"]), not bool(rule.get("enabled")))
        elif rule["kind"] == "keyword":
            rule_service.set_rule_enabled(int(rule["id"]), not bool(rule.get("enabled")))
        self._invalidate()
        self.refresh()

    def delete_rule(self, rule: dict) -> None:
        if not messagebox.askyesno("删除规则", "只删除规则本身，不会改写历史 activity。是否继续？"):
            return
        if rule["kind"] == "file":
            resource_service.clear_file_default(int(rule["id"]))
        elif rule["kind"] == "folder":
            folder_rule_service.delete_folder_rule(int(rule["id"]))
        elif rule["kind"] == "keyword":
            rule_service.delete_rule(int(rule["id"]))
        self._invalidate()
        self.refresh()

    def delete_project(self, project: dict) -> None:
        message = (
            f"确定删除项目“{project['name']}”吗？\n\n"
            "项目会从当前选择和未来自动归类中移除，相关规则会被删除；历史时间记录会保留原项目名称。"
        )
        if not messagebox.askyesno("删除项目", message):
            return
        try:
            project_service.delete_project(int(project["id"]))
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        self._invalidate()
        self.refresh()

    def set_folder_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        folder_rule_service.set_folder_rule_enabled(rule_id, enabled)
        self._invalidate()
        self.refresh()

    def delete_folder_rule(self, rule_id: int) -> None:
        self.delete_rule({"kind": "folder", "id": rule_id})

    def _invalidate(self) -> None:
        self._rules_signature = None


def _rules_for_project(project: dict) -> list[dict]:
    project_name = project.get("name") or "未知项目"
    file_rules = [
        {
            "kind": "file",
            "id": int(row["id"]),
            "target": row.get("full_path") or row.get("display_name") or "未知文件",
            "project_name": project_name,
        }
        for row in project.get("file_defaults", [])
    ]
    folder_rules = [
        {
            "kind": "folder",
            "id": int(rule["id"]),
            "target": rule["folder_path"],
            "project_name": project_name,
            "enabled": bool(int(rule["enabled"])),
            "recursive": bool(int(rule["recursive"])),
        }
        for rule in project.get("folder_rules", [])
    ]
    keyword_rules = [
        {
            "kind": "keyword",
            "id": int(rule["id"]),
            "target": rule["keyword"],
            "project_name": project_name,
            "enabled": bool(int(rule["enabled"])),
        }
        for rule in project.get("keyword_rules", [])
    ]
    return [*file_rules, *folder_rules, *keyword_rules]


def _project_signature(project: dict) -> tuple:
    return (
        project["id"],
        project["name"],
        tuple((row["id"], row.get("full_path") or row.get("display_name")) for row in project.get("file_defaults", [])),
        tuple((rule["id"], rule["folder_path"], rule["enabled"], rule["recursive"]) for rule in project.get("folder_rules", [])),
        tuple((rule["id"], rule["keyword"], rule["enabled"]) for rule in project.get("keyword_rules", [])),
    )


def _project_rule_summary(project: dict) -> str:
    file_count = len(project.get("file_defaults", []))
    folder_count = len(project.get("folder_rules", []))
    keyword_count = len(project.get("keyword_rules", []))
    total = file_count + folder_count + keyword_count
    if total == 0:
        return "暂无规则"
    return f"{total} 条规则：文件 {file_count}，文件夹 {folder_count}，关键词 {keyword_count}"


def _rule_detail_text(rule: dict) -> str:
    base = f"归属项目：{rule['project_name']}"
    if rule["kind"] == "folder":
        scope = "包含子文件夹" if bool(rule.get("recursive")) else "仅直接文件"
        state = "已启用" if bool(rule.get("enabled")) else "已禁用"
        return f"{base} | {scope} | {state}"
    if rule["kind"] == "keyword":
        state = "已启用" if bool(rule.get("enabled")) else "已禁用"
        return f"{base} | {state}"
    return base


def _project_binding_text(project: dict) -> str:
    folder_rules = project["folder_rules"]
    file_defaults = project["file_defaults"]
    keyword_rules = project.get("keyword_rules", [])
    lines = []
    if file_defaults:
        file_names = [row.get("full_path") or row.get("display_name") or "未知文件" for row in file_defaults[:5]]
        lines.append("文件：" + "；".join(file_names))
        if len(file_defaults) > 5:
            lines.append(f"另有 {len(file_defaults) - 5} 个文件")
    if folder_rules:
        lines.append("文件夹：" + "；".join(rule["folder_path"] for rule in folder_rules[:5]))
        if len(folder_rules) > 5:
            lines.append(f"另有 {len(folder_rules) - 5} 条文件夹规则")
    if keyword_rules:
        lines.append("关键词：" + "；".join(rule["keyword"] for rule in keyword_rules[:5]))
        if len(keyword_rules) > 5:
            lines.append(f"另有 {len(keyword_rules) - 5} 条关键词规则")
    if not lines:
        lines.append("暂无绑定")
    return "\n".join(lines)


def _empty_row(parent, text: str) -> None:
    row = design.section(parent, fg_color=design.CARD_SUBTLE_BG)
    row.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
    design.label(row, text=text, variant="caption").pack(anchor="w", padx=14, pady=12)


def _clear_children(widget) -> None:
    for child in widget.winfo_children():
        child.destroy()
