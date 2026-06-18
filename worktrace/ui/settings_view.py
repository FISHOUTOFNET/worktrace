from __future__ import annotations

import logging
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from .. import __version__
from ..config import resolve_paths
from ..constants import PRIVACY_NOTICE_TEXT
from ..services import export_service, project_service, privacy_service
from ..services.settings_service import get_setting, set_setting


class SettingsView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self._build()

    def _build(self) -> None:
        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=12, pady=12)
        self.entries: dict[str, ctk.CTkEntry] = {}
        for row, (key, label) in enumerate(
            [
                ("poll_interval_seconds", "采集间隔秒"),
                ("idle_threshold_minutes", "空闲阈值分钟"),
                ("min_activity_seconds", "最小记录秒"),
                ("exclude_keywords", "隐私排除关键词"),
                ("export_path", "导出目录"),
            ]
        ):
            ctk.CTkLabel(form, text=label).grid(row=row, column=0, padx=8, pady=6, sticky="w")
            entry = ctk.CTkEntry(form, width=420)
            entry.insert(0, get_setting(key, "") or "")
            entry.grid(row=row, column=1, padx=8, pady=6, sticky="w")
            self.entries[key] = entry
        ctk.CTkButton(form, text="保存设置", command=self.save).grid(row=5, column=1, padx=8, pady=8, sticky="w")

        actions = ctk.CTkFrame(self)
        actions.pack(fill="x", padx=12, pady=8)
        ctk.CTkButton(actions, text="新建项目", command=self.create_project).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="查看隐私说明", command=self.show_notice).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="导出全部本地数据", command=self.export_all).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="清空所有本地记录", fg_color="#a33", command=self.clear_all).pack(
            side="left", padx=4
        )

        self.info = ctk.CTkLabel(self, text="", justify="left")
        self.info.pack(fill="x", padx=16, pady=12)

    def refresh(self) -> None:
        paths = resolve_paths()
        self.info.configure(
            text=(
                f"数据路径：{paths.db_path}\n"
                f"日志路径：{paths.log_path}\n"
                f"采集器心跳：{get_setting('last_collector_heartbeat', '')}\n"
                f"版本：{__version__}"
            )
        )

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
            except Exception as exc:
                messagebox.showerror("创建失败", str(exc))

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
