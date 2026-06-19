from __future__ import annotations

import customtkinter as ctk

from ..constants import PRIVACY_NOTICE_TEXT
from . import design


class FirstRunDialog(ctk.CTkToplevel):
    def __init__(self, master, on_accept):
        super().__init__(master)
        self.title("WorkTrace 隐私说明")
        self.geometry("560x520")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._block_close)
        self.on_accept = on_accept
        self.configure(fg_color=design.WINDOW_BG)

        shell = design.card(self)
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        shell.grid_columnconfigure(0, weight=1)
        design.label(shell, text="开始使用前，请确认隐私边界", variant="title").grid(
            row=0, column=0, sticky="w", padx=18, pady=(18, 6)
        )
        design.label(
            shell,
            text="WorkTrace 只记录窗口元数据和时间，用来帮你整理自己的工作轨迹。",
            variant="caption",
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        highlights = ctk.CTkFrame(shell, fg_color="transparent")
        highlights.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        for index, item in enumerate(["本地保存", "不截屏录屏", "不读取正文", "用户可清空"]):
            pill = ctk.CTkLabel(
                highlights,
                text=item,
                font=design.FONT_CAPTION_STRONG,
                text_color=design.ACCENT,
                fg_color=design.ACCENT_SOFT,
                corner_radius=999,
                height=28,
            )
            pill.pack(side="left", padx=(0 if index == 0 else 8, 0))

        box = ctk.CTkTextbox(
            shell,
            height=300,
            wrap="word",
            font=design.FONT_BODY,
            corner_radius=design.RADIUS_MD,
            border_width=1,
            border_color=design.BORDER,
        )
        box.insert("1.0", PRIVACY_NOTICE_TEXT)
        box.configure(state="disabled")
        box.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 14))
        shell.grid_rowconfigure(3, weight=1)
        design.button(shell, text="我已了解，开始本地记录", command=self._accept).grid(
            row=4, column=0, sticky="ew", padx=18, pady=(0, 18)
        )

    def _block_close(self) -> None:
        self.lift()

    def _accept(self) -> None:
        self.on_accept()
        self.destroy()
