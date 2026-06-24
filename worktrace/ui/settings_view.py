from __future__ import annotations

from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from ..api import backup_api, settings_api
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
        self.clipboard_capture_var = ctk.BooleanVar(value=settings_api.get_bool_setting_value("clipboard_capture_enabled", False))
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
            entry.insert(0, settings_api.get_setting_value(key, "") or "")
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

        backup = design.card(self.scroll)
        backup.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        backup.grid_columnconfigure(0, weight=1)
        design.label(backup, text="加密备份", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        design.label(
            backup,
            text="导出本机数据为加密 .wtbackup 文件，用于迁移或备份。忘记密码无法恢复。WorkTrace 不会上传该文件。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        design.label(
            backup,
            text="注意：如果开启了复制文字记录，备份将包含已保存的复制文本。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        backup_actions = ctk.CTkFrame(backup, fg_color="transparent")
        backup_actions.grid(row=3, column=0, sticky="w", padx=18, pady=(0, 18))
        design.button(backup_actions, text="导出加密备份", command=self.export_encrypted_backup).pack(side="left")
        design.button(backup_actions, text="导入加密备份", variant="subtle", command=self.import_encrypted_backup).pack(side="left", padx=(8, 0))

        danger = design.card(self.scroll)
        danger.grid(row=3, column=0, sticky="ew")
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
            entry.insert(0, settings_api.get_setting_value(key, "") or "")
        if hasattr(self, "clipboard_capture_var"):
            self.clipboard_capture_var.set(settings_api.get_bool_setting_value("clipboard_capture_enabled", False))

    def copy_page_text(self) -> str:
        export_path = self.entries.get("export_path").get() if "export_path" in self.entries else ""
        return "\n".join(
            [
                "设置与隐私",
                "调整导出目录、查看隐私说明或清空本地记录。",
                f"导出目录：{export_path}",
                f"记录复制文字：{'开启' if self.clipboard_capture_var.get() else '关闭'}",
                "加密备份：导出加密备份 / 导入加密备份",
                "本地数据操作：清空所有本地记录",
            ]
        )

    def save(self) -> None:
        for key, entry in self.entries.items():
            settings_api.set_setting_value(key, entry.get())
        self.refresh()
        messagebox.showinfo("已保存", "设置已保存")

    def save_clipboard_capture(self) -> None:
        settings_api.set_setting_value("clipboard_capture_enabled", "true" if self.clipboard_capture_var.get() else "false")

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
            settings_api.clear_all_local_data(confirm=True)
            messagebox.showinfo("已清空", "本地数据已清空并重建默认设置")
            self.refresh()

    def export_encrypted_backup(self) -> None:
        passphrase = self._ask_new_passphrase()
        if not passphrase:
            return
        default_name = "WorkTrace-Backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".wtbackup"
        path = filedialog.asksaveasfilename(
            title="导出加密备份",
            defaultextension=".wtbackup",
            filetypes=[("WorkTrace 加密备份", "*.wtbackup"), ("所有文件", "*.*")],
            initialfile=default_name,
        )
        if not path:
            return
        try:
            backup_api.export_encrypted_backup(path, passphrase)
        except Exception:
            messagebox.showerror("导出失败", "导出加密备份时出错，请重试。")
            return
        messagebox.showinfo("导出成功", f"加密备份已导出到：\n{path}")

    def import_encrypted_backup(self) -> None:
        confirm_message = (
            "导入将替换当前本机 WorkTrace 数据。\n"
            "建议先导出当前数据进行备份。\n"
            "错误密码不会导入。\n"
            "忘记密码无法恢复备份。\n\n"
            "是否继续？"
        )
        if not messagebox.askyesno("确认导入加密备份", confirm_message):
            return
        path = filedialog.askopenfilename(
            title="选择加密备份文件",
            filetypes=[("WorkTrace 加密备份", "*.wtbackup"), ("所有文件", "*.*")],
        )
        if not path:
            return
        passphrase = simpledialog.askstring(
            "输入备份密码", "请输入备份密码：", show="*", parent=self
        )
        if not passphrase:
            return
        try:
            backup_api.import_encrypted_backup(path, passphrase, mode="replace")
        except backup_api.BackupDecryptionError:
            messagebox.showerror("导入失败", "无法解密备份或密码错误。")
            return
        except backup_api.BackupCorruptedError:
            messagebox.showerror("导入失败", "备份文件无效或已损坏。")
            return
        except backup_api.BackupVersionNotSupportedError:
            messagebox.showerror("导入失败", "备份版本不受支持。")
            return
        except Exception:
            messagebox.showerror("导入失败", "导入加密备份时出错。")
            return
        messagebox.showinfo("导入成功", "加密备份已导入并替换当前本地数据。")
        self.refresh()

    def _ask_new_passphrase(self) -> str | None:
        passphrase = simpledialog.askstring(
            "设置备份密码", "请输入备份密码：", show="*", parent=self
        )
        if not passphrase:
            return None
        confirm = simpledialog.askstring(
            "确认备份密码", "请再次输入备份密码：", show="*", parent=self
        )
        if not confirm:
            return None
        if passphrase != confirm:
            messagebox.showerror("密码不一致", "两次输入的密码不一致，请重试。")
            return None
        return passphrase
