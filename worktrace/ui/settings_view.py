from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..services import export_service
from ..services.settings_service import get_bool_setting, get_setting, set_setting
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
        design.label(header, text="调整导出目录、查看隐私说明或清空本地记录。", variant="caption").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        design.button(header, text="查看隐私说明", variant="subtle", command=self.show_notice).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.entries: dict[str, ctk.CTkEntry] = {}
        self.clipboard_capture_var = ctk.BooleanVar(value=get_bool_setting("clipboard_capture_enabled", False))
        form = design.card(self.scroll)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        form.grid_columnconfigure(1, weight=1)
        design.label(form, text="导出目录", variant="section").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 8)
        )
        fields = [
            ("export_path", "导出目录", "Excel 导出的默认位置"),
        ]
        for row_index, (key, label, hint) in enumerate(fields, start=1):
            design.label(form, text=label, variant="strong").grid(
                row=row_index, column=0, sticky="w", padx=(18, 14), pady=7
            )
            entry = design.entry(form)
            entry.insert(0, get_setting(key, "") or "")
            entry.grid(row=row_index, column=1, sticky="ew", pady=7)
            self.entries[key] = entry
            design.button(form, text="浏览", variant="subtle", width=72, command=self.choose_export_path).grid(
                row=row_index, column=2, sticky="e", padx=(8, 18), pady=7
            )
        design.button(form, text="保存设置", command=self.save).grid(
            row=len(fields) + 1, column=1, sticky="w", pady=(10, 18)
        )

        privacy = design.card(self.scroll)
        privacy.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        privacy.grid_columnconfigure(0, weight=1)
        design.label(privacy, text="复制文字记录", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        design.label(
            privacy,
            text="开启后会在本机保存每次复制的文本内容，并自动清理 30 天前的记录。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        design.checkbox(
            privacy,
            text="记录复制文字（默认关闭）",
            variable=self.clipboard_capture_var,
            command=self.save_clipboard_capture,
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 16))

        danger = design.card(self.scroll)
        danger.grid(row=2, column=0, sticky="ew")
        danger.grid_columnconfigure(0, weight=1)
        design.label(danger, text="本地数据操作", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        design.label(
            danger,
            text="清空后会重建默认设置且无法恢复。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        actions = ctk.CTkFrame(danger, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 18))
        design.button(actions, text="清空所有本地记录", variant="danger", command=self.clear_all).pack(side="left")

    def refresh(self) -> None:
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, get_setting(key, "") or "")
        if hasattr(self, "clipboard_capture_var"):
            self.clipboard_capture_var.set(get_bool_setting("clipboard_capture_enabled", False))

    def copy_page_text(self) -> str:
        export_path = self.entries.get("export_path").get() if "export_path" in self.entries else ""
        return "\n".join(
            [
                "设置与隐私",
                "调整导出目录、查看隐私说明或清空本地记录。",
                f"导出目录：{export_path}",
                f"记录复制文字：{'开启' if self.clipboard_capture_var.get() else '关闭'}",
                "本地数据操作：清空所有本地记录",
            ]
        )

    def save(self) -> None:
        for key, entry in self.entries.items():
            set_setting(key, entry.get())
        self.refresh()
        messagebox.showinfo("已保存", "设置已保存")

    def save_clipboard_capture(self) -> None:
        set_setting("clipboard_capture_enabled", "true" if self.clipboard_capture_var.get() else "false")

    def choose_export_path(self) -> None:
        folder = filedialog.askdirectory(title="选择导出目录")
        if folder:
            entry = self.entries["export_path"]
            entry.delete(0, "end")
            entry.insert(0, folder)

    def show_notice(self) -> None:
        PrivacyNoticeDialog(self)

    def clear_all(self) -> None:
        message = "此操作将删除本机保存的所有工作轨迹、项目、规则和设置。删除后无法恢复。是否继续？"
        if messagebox.askyesno("确认清空", message):
            export_service.clear_all_local_data(confirm=True)
            messagebox.showinfo("已清空", "本地数据已清空并重建默认设置")
            self.refresh()
