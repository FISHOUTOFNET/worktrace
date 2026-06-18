from __future__ import annotations

import customtkinter as ctk

from ..constants import PRIVACY_NOTICE_TEXT


class FirstRunDialog(ctk.CTkToplevel):
    def __init__(self, master, on_accept):
        super().__init__(master)
        self.title("WorkTrace 隐私说明")
        self.geometry("560x520")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._block_close)
        self.on_accept = on_accept

        ctk.CTkLabel(self, text="首次使用隐私说明", font=ctk.CTkFont(size=20, weight="bold")).pack(
            padx=20, pady=(20, 10)
        )
        box = ctk.CTkTextbox(self, height=360, wrap="word")
        box.insert("1.0", PRIVACY_NOTICE_TEXT)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, padx=20, pady=10)
        ctk.CTkButton(self, text="我已了解并同意开始记录", command=self._accept).pack(
            padx=20, pady=(0, 20)
        )

    def _block_close(self) -> None:
        self.lift()

    def _accept(self) -> None:
        self.on_accept()
        self.destroy()
