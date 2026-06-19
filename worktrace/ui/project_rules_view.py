from __future__ import annotations

import logging
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..services import folder_rule_service, project_service
from . import design


class ProjectRulesView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text="项目与规则", variant="title").grid(row=0, column=0, sticky="w")
        design.label(
            header,
            text="管理项目、文件默认归属和文件夹规则，让时间线自动归到正确上下文。",
            variant="caption",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        design.button(actions, text="新建项目", command=self.create_project).pack(side="left", padx=(0, 8))
        design.button(actions, text="新增文件夹规则", variant="subtle", command=self.add_folder_rule).pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.project_section = design.card(self.scroll)
        self.project_section.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.project_section.grid_columnconfigure(0, weight=1)
        design.label(self.project_section, text="用户项目绑定总览", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 8)
        )
        self.project_bindings_frame = ctk.CTkFrame(self.project_section, fg_color="transparent")
        self.project_bindings_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.project_bindings_frame.grid_columnconfigure(0, weight=1)

        self.folder_section = design.card(self.scroll)
        self.folder_section.grid(row=1, column=0, sticky="ew")
        self.folder_section.grid_columnconfigure(0, weight=1)
        folder_header = ctk.CTkFrame(self.folder_section, fg_color="transparent")
        folder_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        folder_header.grid_columnconfigure(0, weight=1)
        design.label(folder_header, text="文件夹项目规则", variant="section").grid(row=0, column=0, sticky="w")
        design.button(
            folder_header,
            text="新增规则",
            variant="ghost",
            width=88,
            command=self.add_folder_rule,
        ).grid(row=0, column=1, sticky="e")
        self.folder_rules_frame = ctk.CTkFrame(self.folder_section, fg_color="transparent")
        self.folder_rules_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.folder_rules_frame.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        self.refresh_project_bindings()
        self.refresh_folder_rules()

    def refresh_project_bindings(self) -> None:
        _clear_children(self.project_bindings_frame)
        projects = project_service.list_project_bindings()
        if not projects:
            _empty_row(self.project_bindings_frame, "暂无用户项目")
            return
        for row_index, project in enumerate(projects):
            row = design.section(self.project_bindings_frame, fg_color=design.CARD_SUBTLE_BG)
            row.grid(row=row_index, column=0, sticky="ew", padx=6, pady=5)
            row.grid_columnconfigure(0, weight=1)
            design.label(row, text=project["name"], variant="strong").grid(
                row=0, column=0, sticky="w", padx=14, pady=(10, 2)
            )
            detail = _project_binding_text(project)
            design.label(row, text=detail, variant="caption", anchor="w", justify="left", wraplength=900).grid(
                row=1, column=0, sticky="ew", padx=14, pady=(0, 10)
            )

    def refresh_folder_rules(self) -> None:
        _clear_children(self.folder_rules_frame)
        rules = folder_rule_service.list_folder_rules()
        if not rules:
            _empty_row(self.folder_rules_frame, "暂无文件夹规则")
            return
        for row_index, rule in enumerate(rules):
            row = design.section(self.folder_rules_frame, fg_color=design.CARD_SUBTLE_BG)
            row.grid(row=row_index, column=0, sticky="ew", padx=6, pady=5)
            row.grid_columnconfigure(0, weight=1)
            text = (
                f"{rule['folder_path']}  ->  {rule.get('project_name') or '未知项目'}"
                f" | {'包含子文件夹' if int(rule['recursive']) else '仅直接文件'}"
                f" | {'已启用' if int(rule['enabled']) else '已禁用'}"
            )
            design.label(row, text=text, variant="caption", anchor="w", justify="left", wraplength=820).grid(
                row=0, column=0, sticky="ew", padx=14, pady=10
            )
            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.grid(row=0, column=1, sticky="e", padx=10, pady=8)
            action_text = "禁用" if int(rule["enabled"]) else "启用"
            design.button(
                actions,
                text=action_text,
                width=62,
                variant="subtle",
                command=lambda rid=int(rule["id"]), enabled=not bool(int(rule["enabled"])): self.set_folder_rule_enabled(rid, enabled),
            ).pack(side="left", padx=(0, 6))
            design.button(
                actions,
                text="删除",
                width=62,
                variant="danger",
                command=lambda rid=int(rule["id"]): self.delete_folder_rule(rid),
            ).pack(side="left")

    def create_project(self) -> None:
        name = ctk.CTkInputDialog(text="项目名称", title="新建项目").get_input()
        if name:
            try:
                project_service.create_project(name)
                messagebox.showinfo("已创建", name)
                self.refresh()
            except Exception as exc:
                messagebox.showerror("创建失败", str(exc))

    def add_folder_rule(self) -> None:
        folder = filedialog.askdirectory(title="选择要绑定项目的文件夹")
        if not folder:
            return
        projects = project_service.list_user_projects()
        if not projects:
            messagebox.showerror("无法新增", "请先创建项目")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("新增文件夹规则")
        dialog.geometry("560x260")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=design.WINDOW_BG)

        content = design.card(dialog)
        content.pack(fill="both", expand=True, padx=16, pady=16)
        content.grid_columnconfigure(0, weight=1)
        design.label(content, text="新增文件夹规则", variant="section").grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 4)
        )
        design.label(content, text=folder, variant="caption", wraplength=500, anchor="w", justify="left").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 12)
        )
        names = [project["name"] for project in projects]
        selected_name = ctk.StringVar(value=names[0])
        design.option_menu(content, values=names, variable=selected_name, width=320).grid(
            row=2, column=0, sticky="w", padx=16, pady=(0, 10)
        )
        recursive_var = ctk.BooleanVar(value=True)
        design.checkbox(content, text="包含子文件夹", variable=recursive_var).grid(
            row=3, column=0, sticky="w", padx=16, pady=(0, 12)
        )

        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="e", padx=16, pady=(0, 16))

        def save_rule() -> None:
            project = project_service.get_project_by_name(selected_name.get())
            if not project:
                messagebox.showerror("保存失败", "请选择有效项目")
                return
            dialog.destroy()
            self._save_folder_rule(folder, int(project["id"]), recursive_var.get())

        design.button(actions, text="取消", variant="ghost", width=72, command=dialog.destroy).pack(
            side="right", padx=(8, 0)
        )
        design.button(actions, text="保存", width=72, command=save_rule).pack(side="right")

    def _save_folder_rule(self, folder: str, project_id: int, recursive: bool) -> None:
        preview = folder_rule_service.preview_folder_rule_conflicts(folder, project_id)
        if any(int(preview[key]) for key in preview):
            message = (
                f"下级已有不同项目的文件夹规则：{preview['child_folder_rule_conflicts']}\n"
                f"具体文件已有不同项目：{preview['file_default_project_conflicts']}\n"
                f"历史 activity 属于其他项目：{preview['other_project_activity_count']}\n"
                f"手动指定且 safe 回填不会覆盖：{preview['manual_activity_count']}\n\n"
                "将保留下级独立设置，且默认不自动回填历史。是否继续保存？"
            )
            if not messagebox.askyesno("规则冲突预览", message):
                return
        try:
            rule_id = folder_rule_service.create_or_update_folder_rule(folder, project_id, recursive=recursive)
            self.refresh()
            if messagebox.askyesno("已保存", "文件夹规则已保存。是否执行 safe 历史回填？"):
                result = folder_rule_service.backfill_folder_rule(rule_id, mode="safe")
                messagebox.showinfo("回填完成", f"已更新 {result['updated_activity_count']} 条记录")
        except Exception as exc:
            logging.exception("folder rule save failed")
            messagebox.showerror("保存失败", str(exc))

    def set_folder_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        folder_rule_service.set_folder_rule_enabled(rule_id, enabled)
        self.refresh()

    def delete_folder_rule(self, rule_id: int) -> None:
        if messagebox.askyesno("删除规则", "只删除规则本身，不会改写历史 activity。是否继续？"):
            folder_rule_service.delete_folder_rule(rule_id)
            self.refresh()


def _project_binding_text(project: dict) -> str:
    folder_rules = project["folder_rules"]
    file_defaults = project["file_defaults"]
    lines = []
    if folder_rules:
        lines.append("文件夹：" + "；".join(rule["folder_path"] for rule in folder_rules[:5]))
        if len(folder_rules) > 5:
            lines.append(f"另有 {len(folder_rules) - 5} 条文件夹规则")
    if file_defaults:
        file_names = [row.get("full_path") or row.get("display_name") or "未知文件" for row in file_defaults[:5]]
        lines.append("文件：" + "；".join(file_names))
        if len(file_defaults) > 5:
            lines.append(f"另有 {len(file_defaults) - 5} 个文件")
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
