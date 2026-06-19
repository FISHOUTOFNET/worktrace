from __future__ import annotations

import logging
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .. import __version__
from ..config import resolve_paths
from ..services import export_service, privacy_service
from ..services.settings_service import get_setting, set_setting
from . import design
from .first_run_dialog import PrivacyNoticeDialog


class SettingsView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text="设置与隐私", variant="title").grid(row=0, column=0, sticky="w")
        design.label(header, text="调整采集频率、隐私排除和本地数据操作。", variant="caption").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        design.button(header, text="查看隐私说明", variant="subtle", command=self.show_notice).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.entries: dict[str, ctk.CTkEntry] = {}
        form = design.card(self.scroll)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        form.grid_columnconfigure(1, weight=1)
        design.label(form, text="采集与导出", variant="section").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 8)
        )
        fields = [
            ("poll_interval_seconds", "采集间隔秒", "后台轮询当前窗口的间隔"),
            ("idle_threshold_minutes", "空闲阈值分钟", "超过该时长判定为空闲"),
            ("min_activity_seconds", "最小记录秒", "短于该时长的片段不作为正式记录"),
            ("exclude_keywords", "隐私排除关键词", "用英文逗号分隔，命中后匿名记录"),
            ("export_path", "导出目录", "Excel、Markdown 和本地数据导出的默认位置"),
        ]
        for row_index, (key, label, hint) in enumerate(fields, start=1):
            design.label(form, text=label, variant="strong").grid(
                row=row_index, column=0, sticky="w", padx=(18, 14), pady=7
            )
            entry = design.entry(form)
            entry.insert(0, get_setting(key, "") or "")
            entry.grid(row=row_index, column=1, sticky="ew", pady=7)
            self.entries[key] = entry
            if key == "export_path":
                design.button(form, text="浏览", variant="ghost", width=72, command=self.choose_export_path).grid(
                    row=row_index, column=2, sticky="e", padx=(8, 18), pady=7
                )
            else:
                design.label(form, text=hint, variant="caption", wraplength=220, justify="left").grid(
                    row=row_index, column=2, sticky="w", padx=(10, 18), pady=7
                )
        design.button(form, text="保存设置", command=self.save).grid(
            row=len(fields) + 1, column=1, sticky="w", pady=(10, 18)
        )

        about = design.card(self.scroll)
        about.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        about.grid_columnconfigure(0, weight=1)
        design.label(about, text="关于本地数据", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 8)
        )
        self.info = design.label(about, text="", variant="caption", justify="left", anchor="w")
        self.info.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

        danger = design.card(self.scroll)
        danger.grid(row=2, column=0, sticky="ew")
        danger.grid_columnconfigure(0, weight=1)
        design.label(danger, text="本地数据操作", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        design.label(
            danger,
            text="导出全部数据会包含本机保存的路径字段；清空后会重建默认设置且无法恢复。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        actions = ctk.CTkFrame(danger, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 18))
        design.button(actions, text="导出全部本地数据", variant="subtle", command=self.export_all).pack(
            side="left", padx=(0, 8)
        )
        design.button(actions, text="清空所有本地记录", variant="danger", command=self.clear_all).pack(side="left")

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

    def choose_export_path(self) -> None:
        folder = filedialog.askdirectory(title="选择导出目录")
        if folder:
            entry = self.entries["export_path"]
            entry.delete(0, "end")
            entry.insert(0, folder)

    def show_notice(self) -> None:
        PrivacyNoticeDialog(self)

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
            self.refresh()
