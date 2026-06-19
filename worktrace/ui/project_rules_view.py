from __future__ import annotations

import logging
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..constants import ANCHOR_FILE_EXTENSIONS
from ..services import folder_rule_service, project_service, resource_service, rule_service
from . import design


RULE_TYPE_LABELS = {
    "file": "文件",
    "folder": "文件夹",
    "keyword": "关键词",
}


class ProjectRulesView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._rules_signature: tuple[tuple, ...] | None = None
        self._bindings_signature: tuple[tuple, ...] | None = None
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
            text="管理项目、文件规则、文件夹规则和关键词规则，让时间详情自动归到正确上下文。",
            variant="caption",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        design.button(actions, text="新建项目", command=self.create_project).pack(side="left", padx=(0, 8))
        design.button(actions, text="新建规则", variant="subtle", command=self.open_new_rule_dialog).pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.project_section = design.card(self.scroll)
        self.project_section.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.project_section.grid_columnconfigure(0, weight=1)
        design.label(self.project_section, text="项目绑定总览", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 8)
        )
        self.project_bindings_frame = ctk.CTkFrame(self.project_section, fg_color="transparent")
        self.project_bindings_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.project_bindings_frame.grid_columnconfigure(0, weight=1)

        self.rules_section = design.card(self.scroll)
        self.rules_section.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self.rules_section.grid_columnconfigure(0, weight=1)
        rules_header = ctk.CTkFrame(self.rules_section, fg_color="transparent")
        rules_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        rules_header.grid_columnconfigure(0, weight=1)
        design.label(rules_header, text="项目规则", variant="section").grid(row=0, column=0, sticky="w")
        design.button(
            rules_header,
            text="新建规则",
            variant="ghost",
            width=88,
            command=self.open_new_rule_dialog,
        ).grid(row=0, column=1, sticky="e")
        self.rules_frame = ctk.CTkFrame(self.rules_section, fg_color="transparent")
        self.rules_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.rules_frame.grid_columnconfigure(0, weight=1)

        self.new_rule_section = design.card(self.scroll)
        self.new_rule_section.grid(row=2, column=0, sticky="ew")
        self.new_rule_section.grid_columnconfigure(0, weight=1)
        design.label(self.new_rule_section, text="新建规则", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        design.label(
            self.new_rule_section,
            text="文件规则用于单个文件，文件夹规则用于目录范围，关键词规则用于匹配文件名。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        quick = ctk.CTkFrame(self.new_rule_section, fg_color="transparent")
        quick.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 18))
        for rule_type, label in [("file", "文件规则"), ("folder", "文件夹规则"), ("keyword", "关键词规则")]:
            design.button(
                quick,
                text=label,
                variant="subtle" if rule_type != "file" else "primary",
                command=lambda value=rule_type: self.open_new_rule_dialog(value),
            ).pack(side="left", padx=(0, 8))

    def refresh(self) -> None:
        self.refresh_project_bindings()
        self.refresh_rules()

    def refresh_project_bindings(self) -> None:
        projects = project_service.list_project_bindings()
        signature = tuple(
            (
                project["id"],
                project["name"],
                tuple((rule["id"], rule["folder_path"], rule["enabled"]) for rule in project["folder_rules"]),
                tuple((row["id"], row.get("full_path") or row.get("display_name")) for row in project["file_defaults"]),
                tuple((rule["id"], rule["keyword"], rule["enabled"]) for rule in project.get("keyword_rules", [])),
            )
            for project in projects
        )
        if signature == self._bindings_signature:
            return
        self._bindings_signature = signature
        _clear_children(self.project_bindings_frame)
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
            design.label(
                row,
                text=_project_binding_text(project),
                variant="caption",
                anchor="w",
                justify="left",
                wraplength=900,
            ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))

    def refresh_rules(self) -> None:
        rules = self._combined_rules()
        signature = tuple(
            (
                rule["kind"],
                rule["id"],
                rule["target"],
                rule["project_name"],
                rule.get("enabled"),
                rule.get("recursive"),
            )
            for rule in rules
        )
        if signature == self._rules_signature:
            return
        self._rules_signature = signature
        _clear_children(self.rules_frame)
        if not rules:
            _empty_row(self.rules_frame, "暂无项目规则")
            return
        for row_index, rule in enumerate(rules):
            row = design.section(self.rules_frame, fg_color=design.CARD_SUBTLE_BG)
            row.grid(row=row_index, column=0, sticky="ew", padx=6, pady=5)
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
            badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=14, pady=10)
            design.label(row, text=rule["target"], variant="strong", anchor="w").grid(
                row=0, column=1, sticky="ew", padx=(0, 12), pady=(10, 2)
            )
            design.label(row, text=_rule_detail_text(rule), variant="caption", anchor="w").grid(
                row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 10)
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
        file_rules = [
            {
                "kind": "file",
                "id": int(row["id"]),
                "target": row.get("full_path") or row.get("display_name") or "未知文件",
                "project_name": row.get("project_name") or "未知项目",
            }
            for row in resource_service.list_file_defaults()
        ]
        folder_rules = [
            {
                "kind": "folder",
                "id": int(rule["id"]),
                "target": rule["folder_path"],
                "project_name": rule.get("project_name") or "未知项目",
                "enabled": bool(int(rule["enabled"])),
                "recursive": bool(int(rule["recursive"])),
            }
            for rule in folder_rule_service.list_folder_rules()
        ]
        keyword_rules = [
            {
                "kind": "keyword",
                "id": int(rule["id"]),
                "target": rule["keyword"],
                "project_name": rule.get("project_name") or "未知项目",
                "enabled": bool(int(rule["enabled"])),
            }
            for rule in rule_service.list_rules()
        ]
        return [*file_rules, *folder_rules, *keyword_rules]

    def create_project(self) -> None:
        name = ctk.CTkInputDialog(text="项目名称", title="新建项目").get_input()
        if name:
            try:
                project_service.create_project(name)
                messagebox.showinfo("已创建", name)
                self._invalidate()
                self.refresh()
            except Exception as exc:
                messagebox.showerror("创建失败", str(exc))

    def add_folder_rule(self) -> None:
        self.open_new_rule_dialog("folder")

    def open_new_rule_dialog(self, initial_type: str = "file") -> None:
        projects = project_service.list_user_projects()
        if not projects:
            messagebox.showerror("无法新增", "请先创建项目")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("新建规则")
        dialog.geometry("640x390")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=design.WINDOW_BG)

        content = design.card(dialog)
        content.pack(fill="both", expand=True, padx=16, pady=16)
        content.grid_columnconfigure(1, weight=1)
        design.label(content, text="新建规则", variant="section").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(16, 12)
        )

        rule_type_var = ctk.StringVar(value=RULE_TYPE_LABELS.get(initial_type, "文件"))
        target_var = ctk.StringVar(value="")
        selected_name = ctk.StringVar(value=projects[0]["name"])
        recursive_var = ctk.BooleanVar(value=True)

        design.label(content, text="规则类型", variant="strong").grid(row=1, column=0, sticky="w", padx=16, pady=7)
        type_menu = design.option_menu(
            content,
            values=["文件", "文件夹", "关键词"],
            variable=rule_type_var,
            width=180,
        )
        type_menu.grid(row=1, column=1, sticky="w", pady=7)

        target_label = design.label(content, text="文件", variant="strong")
        target_label.grid(row=2, column=0, sticky="w", padx=16, pady=7)
        target_entry = design.entry(content, textvariable=target_var)
        target_entry.grid(row=2, column=1, sticky="ew", pady=7)
        browse_button = design.button(content, text="浏览", variant="ghost", width=72)
        browse_button.grid(row=2, column=2, sticky="e", padx=(8, 16), pady=7)

        design.label(content, text="归属项目", variant="strong").grid(row=3, column=0, sticky="w", padx=16, pady=7)
        design.option_menu(
            content,
            values=[project["name"] for project in projects],
            variable=selected_name,
            width=280,
        ).grid(row=3, column=1, sticky="w", pady=7)

        recursive_checkbox = design.checkbox(content, text="包含子文件夹", variable=recursive_var)
        recursive_checkbox.grid(row=4, column=1, sticky="w", pady=7)

        hint_label = design.label(
            content,
            text="选择一个具体文件，之后该文件默认归入所选项目。",
            variant="caption",
            anchor="w",
            justify="left",
            wraplength=520,
        )
        hint_label.grid(row=5, column=0, columnspan=3, sticky="ew", padx=16, pady=(6, 12))

        def current_kind() -> str:
            reverse = {value: key for key, value in RULE_TYPE_LABELS.items()}
            return reverse.get(rule_type_var.get(), "file")

        def update_type(*_args) -> None:
            kind = current_kind()
            labels = {"file": "文件", "folder": "文件夹", "keyword": "关键词"}
            hints = {
                "file": "选择一个具体文件，之后该文件默认归入所选项目。",
                "folder": "选择一个文件夹，之后目录内文件会按该规则归入所选项目。",
                "keyword": "输入关键词，匹配到的锚点文件会自动归入所选项目。",
            }
            target_label.configure(text=labels[kind])
            hint_label.configure(text=hints[kind])
            if kind == "keyword":
                browse_button.configure(state="disabled")
                recursive_checkbox.grid_remove()
            else:
                browse_button.configure(state="normal")
                if kind == "folder":
                    recursive_checkbox.grid(row=4, column=1, sticky="w", pady=7)
                else:
                    recursive_checkbox.grid_remove()

        def browse_target() -> None:
            kind = current_kind()
            if kind == "file":
                pattern = " ".join(f"*{ext}" for ext in ANCHOR_FILE_EXTENSIONS)
                path = filedialog.askopenfilename(title="选择要绑定项目的文件", filetypes=[("支持的文件", pattern), ("所有文件", "*.*")])
            elif kind == "folder":
                path = filedialog.askdirectory(title="选择要绑定项目的文件夹")
            else:
                path = ""
            if path:
                target_var.set(path)

        def save_rule() -> None:
            project = project_service.get_project_by_name(selected_name.get())
            if not project:
                messagebox.showerror("保存失败", "请选择有效项目")
                return
            target = target_var.get().strip()
            if not target:
                messagebox.showerror("保存失败", "请输入或选择规则内容")
                return
            try:
                kind = current_kind()
                if kind == "file":
                    resource_service.create_or_update_file_default(target, int(project["id"]))
                elif kind == "folder":
                    if not self._save_folder_rule(target, int(project["id"]), bool(recursive_var.get()), refresh=False):
                        return
                else:
                    rule_service.create_rule(target, int(project["id"]))
            except Exception as exc:
                logging.exception("rule save failed")
                messagebox.showerror("保存失败", str(exc))
                return
            dialog.destroy()
            self._invalidate()
            self.refresh()

        browse_button.configure(command=browse_target)
        type_menu.configure(command=lambda _value: update_type())
        update_type()

        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.grid(row=6, column=0, columnspan=3, sticky="e", padx=16, pady=(0, 16))
        design.button(actions, text="取消", variant="ghost", width=72, command=dialog.destroy).pack(
            side="right", padx=(8, 0)
        )
        design.button(actions, text="保存", width=72, command=save_rule).pack(side="right")

    def _save_folder_rule(self, folder: str, project_id: int, recursive: bool, refresh: bool = True) -> bool:
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
                return False
        rule_id = folder_rule_service.create_or_update_folder_rule(folder, project_id, recursive=recursive)
        if refresh:
            self._invalidate()
            self.refresh()
        if messagebox.askyesno("已保存", "文件夹规则已保存。是否执行 safe 历史回填？"):
            result = folder_rule_service.backfill_folder_rule(rule_id, mode="safe")
            messagebox.showinfo("回填完成", f"已更新 {result['updated_activity_count']} 条记录")
        return True

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

    def set_folder_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        folder_rule_service.set_folder_rule_enabled(rule_id, enabled)
        self._invalidate()
        self.refresh()

    def delete_folder_rule(self, rule_id: int) -> None:
        self.delete_rule({"kind": "folder", "id": rule_id})

    def _invalidate(self) -> None:
        self._rules_signature = None
        self._bindings_signature = None


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
