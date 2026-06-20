from __future__ import annotations

import logging
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from ..constants import ANCHOR_FILE_EXTENSIONS
from ..services import folder_rule_service, project_service, resource_service, rule_service
from . import design


RULE_TYPE_LABELS = {
    "file": "文件",
    "folder": "文件夹",
    "keyword": "关键词",
}
RULE_LABEL_TO_TYPE = {label: kind for kind, label in RULE_TYPE_LABELS.items()}
PROJECT_MODE_EXISTING = "选择已有项目"
PROJECT_MODE_NEW = "创建项目"

SavedCallback = Callable[[dict], None]


def open_project_rule_dialog(
    master,
    *,
    initial_type: str = "folder",
    initial_target: str = "",
    initial_project_name: str | None = None,
    initial_project_mode: str | None = None,
    initial_create_rule: bool | None = None,
    lock_project: bool = False,
    edit_project_id: int | None = None,
    on_saved: SavedCallback | None = None,
):
    return ProjectRuleDialog(
        master,
        initial_type=initial_type,
        initial_target=initial_target,
        initial_project_name=initial_project_name,
        initial_project_mode=initial_project_mode,
        initial_create_rule=initial_create_rule,
        lock_project=lock_project,
        edit_project_id=edit_project_id,
        on_saved=on_saved,
    )


def save_folder_rule_with_confirmation(folder: str, project_id: int, recursive: bool) -> bool:
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
    if messagebox.askyesno("已保存", "文件夹规则已保存。是否执行 safe 历史回填？"):
        result = folder_rule_service.backfill_folder_rule(rule_id, mode="safe")
        messagebox.showinfo("回填完成", f"已更新 {result['updated_activity_count']} 条记录")
    return True


class ProjectRuleDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        initial_type: str = "folder",
        initial_target: str = "",
        initial_project_name: str | None = None,
        initial_project_mode: str | None = None,
        initial_create_rule: bool | None = None,
        lock_project: bool = False,
        edit_project_id: int | None = None,
        on_saved: SavedCallback | None = None,
    ):
        super().__init__(master)
        self.on_saved = on_saved
        self.edit_project = project_service.get_project(edit_project_id) if edit_project_id is not None else None
        if self.edit_project and self.edit_project.get("created_by") == "system":
            raise ValueError("system project cannot be edited")
        self.projects = project_service.list_rule_target_projects()
        project_names = [project["name"] for project in self.projects]
        initial_type = initial_type if initial_type in RULE_TYPE_LABELS else "folder"
        initial_project_name = initial_project_name if initial_project_name in project_names else None
        self.lock_project = bool(lock_project and initial_project_name)
        if initial_project_mode not in {PROJECT_MODE_EXISTING, PROJECT_MODE_NEW}:
            initial_project_mode = PROJECT_MODE_EXISTING if initial_project_name or project_names else PROJECT_MODE_NEW

        self.project_mode_var = ctk.StringVar(
            value=initial_project_mode
        )
        self.selected_project_var = ctk.StringVar(value=initial_project_name or (project_names[0] if project_names else ""))
        self.new_project_var = ctk.StringVar(value=str(self.edit_project.get("name") or "") if self.edit_project else "")
        self.description_var = ctk.StringVar(
            value=str(self.edit_project.get("description") or "") if self.edit_project else ""
        )
        if initial_create_rule is None:
            initial_create_rule = self.edit_project is None
        self.create_rule_var = ctk.BooleanVar(value=bool(initial_create_rule))
        self.rule_type_var = ctk.StringVar(value=RULE_TYPE_LABELS[initial_type])
        self.target_var = ctk.StringVar(value=initial_target)
        self.recursive_var = ctk.BooleanVar(value=True)
        self.feedback_var = ctk.StringVar(value="")

        self.dialog_title = self._dialog_title()
        self.title(self.dialog_title)
        self.geometry("700x560")
        self.transient(master)
        self.grab_set()
        self.configure(fg_color=design.WINDOW_BG)
        self._build(project_names)
        self._sync_project_mode()
        self._sync_rule_type()

    def _build(self, project_names: list[str]) -> None:
        shell = design.card(self)
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        content = ctk.CTkScrollableFrame(shell, fg_color="transparent")
        content.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        content.grid_columnconfigure(1, weight=1)

        title = self.dialog_title
        if self.edit_project:
            subtitle = "可修改项目名称和备注，也可以顺手添加一条新规则。"
        elif self.lock_project:
            subtitle = "为当前项目添加一条文件、文件夹或关键词规则。"
        elif self.project_mode_var.get() == PROJECT_MODE_NEW and not self.create_rule_var.get():
            subtitle = "先创建项目，之后可在项目卡片中继续添加规则。"
        else:
            subtitle = "可以创建新项目并添加首条规则，也可以选择已有项目新增规则。"
        design.label(content, text=title, variant="section").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(16, 4)
        )
        design.label(
            content,
            text=subtitle,
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 12))

        if self.edit_project:
            design.label(content, text="项目", variant="strong").grid(row=2, column=0, sticky="w", padx=16, pady=7)
            design.label(content, text="编辑当前项目", variant="caption").grid(row=2, column=1, sticky="w", pady=7)
            self.project_mode_control = None
        elif self.lock_project:
            design.label(content, text="项目", variant="strong").grid(row=2, column=0, sticky="w", padx=16, pady=7)
            design.label(content, text=self.selected_project_var.get(), variant="caption").grid(row=2, column=1, sticky="w", pady=7)
            self.project_mode_control = None
        else:
            design.label(content, text="项目", variant="strong").grid(row=2, column=0, sticky="w", padx=16, pady=7)
            mode = design.segmented_button(
                content,
                values=[PROJECT_MODE_EXISTING, PROJECT_MODE_NEW],
                variable=self.project_mode_var,
                command=lambda _value: self._sync_project_mode(),
                width=250,
            )
            mode.grid(row=2, column=1, sticky="w", pady=7)
            self.project_mode_control = mode
            if not project_names:
                mode.configure(state="disabled")

        self.existing_project_menu = design.option_menu(
            content,
            values=project_names or ["暂无项目"],
            variable=self.selected_project_var,
            width=280,
        )
        self.existing_project_menu.grid(row=3, column=1, sticky="w", pady=7)

        self.new_project_entry = design.entry(content, textvariable=self.new_project_var)
        self.new_project_entry.grid(row=4, column=1, sticky="ew", pady=7)
        self.new_project_label = design.label(content, text="项目名称", variant="caption")
        self.new_project_label.grid(row=4, column=0, sticky="w", padx=16, pady=7)
        self.description_entry = design.entry(content, textvariable=self.description_var)
        self.description_entry.grid(row=5, column=1, sticky="ew", pady=7)
        self.description_label = design.label(content, text="项目备注", variant="caption")
        self.description_label.grid(row=5, column=0, sticky="w", padx=16, pady=7)

        self.create_rule_checkbox = design.checkbox(content, text="同时新建规则", variable=self.create_rule_var, command=self._sync_rule_enabled)
        self.create_rule_checkbox.grid(row=6, column=1, sticky="w", pady=(10, 6))

        self.rule_type_label = design.label(content, text="规则类型", variant="strong")
        self.rule_type_label.grid(row=7, column=0, sticky="w", padx=16, pady=7)
        self.rule_type_menu = design.option_menu(
            content,
            values=list(RULE_TYPE_LABELS.values()),
            variable=self.rule_type_var,
            width=180,
            command=lambda _value: self._sync_rule_type(),
        )
        self.rule_type_menu.grid(row=7, column=1, sticky="w", pady=7)

        self.target_label = design.label(content, text="文件", variant="strong")
        self.target_label.grid(row=8, column=0, sticky="w", padx=16, pady=7)
        self.target_entry = design.entry(content, textvariable=self.target_var)
        self.target_entry.grid(row=8, column=1, sticky="ew", pady=7)
        self.browse_button = design.button(content, text="浏览", variant="subtle", width=72, command=self._browse_target)
        self.browse_button.grid(row=8, column=2, sticky="e", padx=(8, 16), pady=7)

        self.recursive_checkbox = design.checkbox(content, text="包含子文件夹", variable=self.recursive_var)
        self.recursive_checkbox.grid(row=9, column=1, sticky="w", pady=7)

        self.hint_label = design.label(content, text="", variant="caption", anchor="w", justify="left", wraplength=560)
        self.hint_label.grid(row=10, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 8))
        self.feedback_label = design.label(content, textvariable=self.feedback_var, variant="caption", anchor="w", justify="left")
        self.feedback_label.grid(row=11, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 8))

        actions = ctk.CTkFrame(shell, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="e", padx=16, pady=(10, 16))
        design.button(actions, text="取消", variant="subtle", width=72, command=self.destroy).pack(side="right", padx=(8, 0))
        design.button(actions, text="保存", width=72, command=self._save).pack(side="right")

    def _sync_project_mode(self) -> None:
        if self.edit_project:
            self.existing_project_menu.grid_remove()
            self.new_project_label.grid()
            self.new_project_entry.grid()
            self.description_label.grid()
            self.description_entry.grid()
            self.create_rule_checkbox.configure(state="normal")
            self._sync_rule_enabled()
            return
        if self.lock_project:
            self.existing_project_menu.grid_remove()
            self.new_project_label.grid_remove()
            self.new_project_entry.grid_remove()
            self.description_label.grid_remove()
            self.description_entry.grid_remove()
            self.create_rule_var.set(True)
            self.create_rule_checkbox.configure(state="disabled")
            self._sync_rule_enabled()
            return
        mode = self.project_mode_var.get()
        if mode == PROJECT_MODE_NEW:
            self.existing_project_menu.grid_remove()
            self.new_project_label.grid()
            self.new_project_entry.grid()
            self.description_label.grid()
            self.description_entry.grid()
            self.create_rule_checkbox.configure(state="normal")
        else:
            self.existing_project_menu.grid()
            self.new_project_label.grid_remove()
            self.new_project_entry.grid_remove()
            self.description_label.grid_remove()
            self.description_entry.grid_remove()
            self.create_rule_var.set(True)
            self.create_rule_checkbox.configure(state="disabled")
        self._sync_rule_enabled()

    def _sync_rule_enabled(self) -> None:
        enabled = bool(self.create_rule_var.get())
        state = "normal" if enabled else "disabled"
        for widget in (self.rule_type_menu, self.target_entry, self.browse_button, self.recursive_checkbox):
            widget.configure(state=state)
        if enabled:
            self.rule_type_label.grid()
            self.rule_type_menu.grid()
            self.target_label.grid()
            self.target_entry.grid()
            self.browse_button.grid()
            self._sync_rule_type()
        else:
            self.rule_type_label.grid_remove()
            self.rule_type_menu.grid_remove()
            self.target_label.grid_remove()
            self.target_entry.grid_remove()
            self.browse_button.grid_remove()
            self.recursive_checkbox.grid_remove()
            self.hint_label.configure(text="仅保存项目信息，不添加规则。")

    def _sync_rule_type(self) -> None:
        if not self.create_rule_var.get():
            return
        kind = self._current_kind()
        labels = {"file": "文件", "folder": "文件夹", "keyword": "关键词"}
        hints = {
            "file": "选择一个具体文件，之后该文件默认归入所选项目。",
            "folder": "选择一个文件夹，之后目录内文件会按该规则归入所选项目。",
            "keyword": "输入关键词，匹配到的锚点文件会自动归入所选项目。",
        }
        self.target_label.configure(text=labels[kind])
        self.hint_label.configure(text=hints[kind])
        if kind == "keyword":
            self.browse_button.configure(state="disabled")
            self.recursive_checkbox.grid_remove()
        else:
            self.browse_button.configure(state="normal")
            if kind == "folder":
                self.recursive_checkbox.grid(row=9, column=1, sticky="w", pady=7)
            else:
                self.recursive_checkbox.grid_remove()

    def _current_kind(self) -> str:
        return RULE_LABEL_TO_TYPE.get(self.rule_type_var.get(), "file")

    def _browse_target(self) -> None:
        kind = self._current_kind()
        if kind == "file":
            pattern = " ".join(f"*{ext}" for ext in ANCHOR_FILE_EXTENSIONS)
            path = filedialog.askopenfilename(title="选择要绑定项目的文件", filetypes=[("支持的文件", pattern), ("所有文件", "*.*")])
        elif kind == "folder":
            path = filedialog.askdirectory(title="选择要绑定项目的文件夹")
        else:
            path = ""
        if path:
            self.target_var.set(path)

    def _save(self) -> None:
        try:
            project_id, project_name, created_project = self._resolve_project()
            rule_created = False
            if self.create_rule_var.get():
                target = self.target_var.get().strip()
                if not target:
                    messagebox.showerror("保存失败", "请输入或选择规则内容")
                    return
                if not self._save_rule(project_id, target):
                    return
                rule_created = True
            elif not created_project and self.edit_project is None:
                messagebox.showerror("保存失败", "请选择创建项目，或同时新建规则")
                return
        except Exception as exc:
            logging.exception("project/rule save failed")
            messagebox.showerror("保存失败", str(exc))
            return

        if self.on_saved is not None:
            self.on_saved({"project_id": project_id, "project_name": project_name, "rule_created": rule_created})
        self.destroy()

    def _resolve_project(self) -> tuple[int, str, bool]:
        if self.edit_project:
            project_id = int(self.edit_project["id"])
            name = self.new_project_var.get().strip()
            project_service.update_project(project_id, name, self.description_var.get().strip())
            self.edit_project = project_service.get_project(project_id) or {"id": project_id, "name": name}
            return project_id, name, False

        if self.project_mode_var.get() == PROJECT_MODE_NEW:
            name = self.new_project_var.get().strip()
            if not name:
                raise ValueError("请输入项目名称")
            existing = project_service.get_project_by_name(name)
            if existing:
                return int(existing["id"]), str(existing["name"]), False
            project_id = project_service.create_project(name, self.description_var.get().strip())
            return project_id, name, True

        project = project_service.get_project_by_name(self.selected_project_var.get())
        if not project:
            raise ValueError("请选择有效项目")
        return int(project["id"]), str(project["name"]), False

    def _save_rule(self, project_id: int, target: str) -> bool:
        kind = self._current_kind()
        if kind == "file":
            resource_service.create_or_update_file_default(target, project_id)
        elif kind == "folder":
            return save_folder_rule_with_confirmation(target, project_id, bool(self.recursive_var.get()))
        else:
            rule_service.create_rule(target, project_id)
        return True

    def _dialog_title(self) -> str:
        if self.edit_project:
            return "编辑项目"
        if self.lock_project:
            return "新增规则"
        if self.project_mode_var.get() == PROJECT_MODE_NEW and not self.create_rule_var.get():
            return "新增项目"
        return "新建项目规则"
