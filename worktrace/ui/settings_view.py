from __future__ import annotations

import logging
from pathlib import Path

import customtkinter as ctk
from tkinter import BooleanVar, StringVar, filedialog, messagebox

from .. import __version__
from ..config import resolve_paths
from ..constants import PRIVACY_NOTICE_TEXT
from ..services import export_service, folder_rule_service, project_service, privacy_service
from ..services.settings_service import get_setting, set_setting


class SettingsView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self._build()

    def _build(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True)

        form = ctk.CTkFrame(self.scroll)
        form.pack(fill="x", padx=12, pady=12)
        self.entries: dict[str, ctk.CTkEntry] = {}
        for row, (key, label) in enumerate(
            [
                ("poll_interval_seconds", "采集间隔秒"),
                ("idle_threshold_minutes", "空闲阈值分钟"),
                ("min_activity_seconds", "最小记录秒"),
                ("min_history_seconds", "正式历史阈值秒"),
                ("min_idle_segment_seconds", "空闲入库阈值秒"),
                ("exclude_keywords", "隐私排除关键词"),
                ("export_path", "导出目录"),
            ]
        ):
            ctk.CTkLabel(form, text=label).grid(row=row, column=0, padx=8, pady=6, sticky="w")
            entry = ctk.CTkEntry(form, width=420)
            entry.insert(0, get_setting(key, "") or "")
            entry.grid(row=row, column=1, padx=8, pady=6, sticky="w")
            self.entries[key] = entry
        ctk.CTkButton(form, text="保存设置", command=self.save).grid(
            row=len(self.entries), column=1, padx=8, pady=8, sticky="w"
        )

        actions = ctk.CTkFrame(self.scroll)
        actions.pack(fill="x", padx=12, pady=8)
        ctk.CTkButton(actions, text="新建项目", command=self.create_project).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="查看隐私说明", command=self.show_notice).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="导出全部本地数据", command=self.export_all).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="清空所有本地记录", fg_color="#a33", command=self.clear_all).pack(
            side="left", padx=4
        )

        self._build_project_bindings()
        self._build_folder_rules()

        self.info = ctk.CTkLabel(self.scroll, text="", justify="left")
        self.info.pack(fill="x", padx=16, pady=12)

    def _build_folder_rules(self) -> None:
        section = ctk.CTkFrame(self.scroll)
        section.pack(fill="x", padx=12, pady=8)
        header = ctk.CTkFrame(section)
        header.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(header, text="文件夹项目规则", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="新增文件夹规则", command=self.add_folder_rule).pack(side="right")

        self.folder_rules_frame = ctk.CTkFrame(section)
        self.folder_rules_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.refresh_folder_rules()

    def _build_project_bindings(self) -> None:
        section = ctk.CTkFrame(self.scroll)
        section.pack(fill="x", padx=12, pady=8)
        header = ctk.CTkFrame(section)
        header.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(header, text="用户项目绑定总览", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.project_bindings_frame = ctk.CTkFrame(section)
        self.project_bindings_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.refresh_project_bindings()

    def refresh(self) -> None:
        self.refresh_project_bindings()
        self.refresh_folder_rules()
        paths = resolve_paths()
        self.info.configure(
            text=(
                f"数据路径：{paths.db_path}\n"
                f"日志路径：{paths.log_path}\n"
                f"采集器心跳：{get_setting('last_collector_heartbeat', '')}\n"
                f"版本：{__version__}"
            )
        )

    def refresh_folder_rules(self) -> None:
        if not hasattr(self, "folder_rules_frame"):
            return
        for child in self.folder_rules_frame.winfo_children():
            child.destroy()
        rules = folder_rule_service.list_folder_rules()
        if not rules:
            ctk.CTkLabel(self.folder_rules_frame, text="暂无文件夹规则", anchor="w").pack(fill="x", padx=8, pady=6)
            return
        for rule in rules:
            row = ctk.CTkFrame(self.folder_rules_frame)
            row.pack(fill="x", padx=4, pady=4)
            text = (
                f"{rule['folder_path']}  →  {rule.get('project_name') or '未知项目'}"
                f"｜{'包含子文件夹' if int(rule['recursive']) else '仅直接文件'}"
                f"｜{'已启用' if int(rule['enabled']) else '已禁用'}"
            )
            ctk.CTkLabel(row, text=text, anchor="w", wraplength=760).pack(side="left", fill="x", expand=True, padx=6)
            action_text = "禁用" if int(rule["enabled"]) else "启用"
            ctk.CTkButton(
                row,
                text=action_text,
                width=56,
                command=lambda rid=int(rule["id"]), enabled=not bool(int(rule["enabled"])): self.set_folder_rule_enabled(rid, enabled),
            ).pack(side="right", padx=3)
            ctk.CTkButton(
                row,
                text="删除",
                width=56,
                fg_color="#a33",
                command=lambda rid=int(rule["id"]): self.delete_folder_rule(rid),
            ).pack(side="right", padx=3)

    def refresh_project_bindings(self) -> None:
        if not hasattr(self, "project_bindings_frame"):
            return
        for child in self.project_bindings_frame.winfo_children():
            child.destroy()
        projects = project_service.list_project_bindings()
        if not projects:
            ctk.CTkLabel(self.project_bindings_frame, text="暂无用户项目", anchor="w").pack(fill="x", padx=8, pady=6)
            return
        for project in projects:
            folder_rules = project["folder_rules"]
            file_defaults = project["file_defaults"]
            lines = [project["name"]]
            if folder_rules:
                lines.append("文件夹：" + "；".join(rule["folder_path"] for rule in folder_rules[:5]))
                if len(folder_rules) > 5:
                    lines.append(f"另有 {len(folder_rules) - 5} 条文件夹规则")
            if file_defaults:
                file_names = [row.get("full_path") or row.get("display_name") or "未知文件" for row in file_defaults[:5]]
                lines.append("文件：" + "；".join(file_names))
                if len(file_defaults) > 5:
                    lines.append(f"另有 {len(file_defaults) - 5} 个文件")
            if not folder_rules and not file_defaults:
                lines.append("暂无绑定")
            ctk.CTkLabel(
                self.project_bindings_frame,
                text="\n".join(lines),
                anchor="w",
                justify="left",
                wraplength=860,
            ).pack(fill="x", padx=8, pady=6)

    def save(self) -> None:
        for key, entry in self.entries.items():
            set_setting(key, entry.get())
        privacy_service.set_exclude_keywords(self.entries["exclude_keywords"].get().split(","))
        self.refresh()
        messagebox.showinfo("已保存", "设置已保存")

    def create_project(self) -> None:
        name = ctk.CTkInputDialog(text="项目名称", title="新建项目").get_input()
        if name:
            try:
                project_service.create_project(name)
                messagebox.showinfo("已创建", name)
                self.refresh_project_bindings()
                self.refresh_folder_rules()
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
        dialog.geometry("520x220")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=folder, wraplength=480, anchor="w").pack(fill="x", padx=14, pady=(14, 8))
        names = [project["name"] for project in projects]
        selected_name = StringVar(value=names[0])
        ctk.CTkOptionMenu(dialog, values=names, variable=selected_name, width=300).pack(anchor="w", padx=14, pady=8)
        recursive_var = BooleanVar(value=True)
        ctk.CTkCheckBox(dialog, text="包含子文件夹", variable=recursive_var).pack(anchor="w", padx=14, pady=8)

        def save_rule() -> None:
            project = project_service.get_project_by_name(selected_name.get())
            if not project:
                messagebox.showerror("保存失败", "请选择有效项目")
                return
            dialog.destroy()
            self._save_folder_rule(folder, int(project["id"]), recursive_var.get())

        actions = ctk.CTkFrame(dialog)
        actions.pack(fill="x", padx=14, pady=12)
        ctk.CTkButton(actions, text="取消", width=72, command=dialog.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="保存", width=72, command=save_rule).pack(side="right")

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
            self.refresh_project_bindings()
            self.refresh_folder_rules()
            if messagebox.askyesno("已保存", "文件夹规则已保存。是否执行 safe 历史回填？"):
                result = folder_rule_service.backfill_folder_rule(rule_id, mode="safe")
                messagebox.showinfo("回填完成", f"已更新 {result['updated_activity_count']} 条记录")
        except Exception as exc:
            logging.exception("folder rule save failed")
            messagebox.showerror("保存失败", str(exc))

    def set_folder_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        folder_rule_service.set_folder_rule_enabled(rule_id, enabled)
        self.refresh_project_bindings()
        self.refresh_folder_rules()

    def delete_folder_rule(self, rule_id: int) -> None:
        if messagebox.askyesno("删除规则", "只删除规则本身，不会改写历史 activity。是否继续？"):
            folder_rule_service.delete_folder_rule(rule_id)
            self.refresh_project_bindings()
            self.refresh_folder_rules()

    def show_notice(self) -> None:
        messagebox.showinfo("WorkTrace 隐私说明", PRIVACY_NOTICE_TEXT)

    def export_all(self) -> None:
        export_dir = Path(get_setting("export_path", str(Path.home() / "Documents" / "WorkTrace Exports")))
        try:
            path = export_service.export_all_local_data(str(export_dir / "worktrace_all_local_data.xlsx"))
            messagebox.showinfo("导出完成", path)
        except Exception as exc:
            logging.exception("all local data export failed")
            messagebox.showerror("导出失败", str(exc))

    def clear_all(self) -> None:
        message = "此操作将删除本机保存的所有工作轨迹、项目、规则和设置。删除后无法恢复。是否继续？"
        if messagebox.askyesno("确认清空", message):
            export_service.clear_all_local_data(confirm=True)
            messagebox.showinfo("已清空", "本地数据已清空并重建默认设置")
