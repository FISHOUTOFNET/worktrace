from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

from .copy_support import bind_copy_menu


FONT_FAMILY = "Microsoft YaHei UI"
FONT_BODY = (FONT_FAMILY, 13)
FONT_BODY_STRONG = (FONT_FAMILY, 13, "bold")
FONT_CAPTION = (FONT_FAMILY, 12)
FONT_CAPTION_STRONG = (FONT_FAMILY, 12, "bold")
FONT_TITLE = (FONT_FAMILY, 24, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 16, "bold")
FONT_SECTION = (FONT_FAMILY, 15, "bold")
FONT_MONO = ("Consolas", 12)

WINDOW_BG = ("#f5f7fb", "#111827")
SIDEBAR_BG = ("#eef2f8", "#0f172a")
PANEL_BG = ("#ffffff", "#182235")
PANEL_ALT_BG = ("#f8fafc", "#111827")
CARD_BG = ("#ffffff", "#1f2937")
CARD_SUBTLE_BG = ("#f8fafc", "#172033")
BORDER = ("#d9e2ef", "#334155")
TEXT = ("#1f2937", "#f8fafc")
MUTED_TEXT = ("#64748b", "#94a3b8")
SUBTLE_TEXT = ("#7c8da5", "#a1adbd")
ACCENT = ("#475569", "#cbd5e1")
ACCENT_HOVER = ("#334155", "#94a3b8")
ACCENT_SOFT = ("#e2e8f0", "#334155")
SUCCESS = ("#0f8b5f", "#34d399")
SUCCESS_SOFT = ("#dcfce7", "#064e3b")
WARNING = ("#b45309", "#fbbf24")
WARNING_SOFT = ("#fef3c7", "#78350f")
DANGER = ("#b42318", "#f87171")
DANGER_HOVER = ("#991b1b", "#ef4444")
DANGER_SOFT = ("#fee2e2", "#7f1d1d")
NEUTRAL_SOFT = ("#e2e8f0", "#334155")

RADIUS_SM = 8
RADIUS_MD = 10
RADIUS_LG = 14
PAD_X = 18
PAD_Y = 16


def apply_app_theme() -> None:
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("green")


def page_frame(master) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color="transparent")


def card(master, **kwargs) -> ctk.CTkFrame:
    kwargs.setdefault("fg_color", CARD_BG)
    kwargs.setdefault("corner_radius", RADIUS_LG)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", BORDER)
    return ctk.CTkFrame(master, **kwargs)


def section(master, **kwargs) -> ctk.CTkFrame:
    kwargs.setdefault("fg_color", PANEL_BG)
    kwargs.setdefault("corner_radius", RADIUS_LG)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", BORDER)
    return ctk.CTkFrame(master, **kwargs)


def label(master, text: str = "", variant: str = "body", **kwargs) -> ctk.CTkLabel:
    fonts = {
        "title": FONT_TITLE,
        "subtitle": FONT_SUBTITLE,
        "section": FONT_SECTION,
        "body": FONT_BODY,
        "strong": FONT_BODY_STRONG,
        "caption": FONT_CAPTION,
        "caption_strong": FONT_CAPTION_STRONG,
        "mono": FONT_MONO,
    }
    kwargs.setdefault("font", fonts.get(variant, FONT_BODY))
    kwargs.setdefault("text_color", TEXT if variant not in {"caption", "mono"} else MUTED_TEXT)
    widget = ctk.CTkLabel(master, text=text, **kwargs)
    bind_copy_menu(widget)
    return widget


def button(master, text: str, variant: str = "primary", **kwargs) -> ctk.CTkButton:
    kwargs.setdefault("font", FONT_BODY_STRONG if variant == "primary" else FONT_BODY)
    kwargs.setdefault("corner_radius", RADIUS_SM)
    kwargs.setdefault("height", 34)
    if variant == "primary":
        kwargs.setdefault("fg_color", ACCENT)
        kwargs.setdefault("hover_color", ACCENT_HOVER)
        kwargs.setdefault("text_color", "#ffffff")
    elif variant == "danger":
        kwargs.setdefault("fg_color", DANGER)
        kwargs.setdefault("hover_color", DANGER_HOVER)
        kwargs.setdefault("text_color", "#ffffff")
    elif variant == "subtle":
        kwargs.setdefault("fg_color", NEUTRAL_SOFT)
        kwargs.setdefault("hover_color", ("#cbd5e1", "#475569"))
        kwargs.setdefault("text_color", TEXT)
    elif variant == "ghost":
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("hover_color", NEUTRAL_SOFT)
        kwargs.setdefault("text_color", TEXT)
    widget = ctk.CTkButton(master, text=text, **kwargs)
    bind_copy_menu(widget)
    return widget


def entry(master, **kwargs) -> ctk.CTkEntry:
    kwargs.setdefault("font", FONT_BODY)
    kwargs.setdefault("height", 34)
    kwargs.setdefault("corner_radius", RADIUS_SM)
    kwargs.setdefault("border_color", BORDER)
    return ctk.CTkEntry(master, **kwargs)


def option_menu(master, **kwargs) -> ctk.CTkOptionMenu:
    kwargs.setdefault("font", FONT_BODY)
    kwargs.setdefault("dropdown_font", FONT_BODY)
    kwargs.setdefault("height", 34)
    kwargs.setdefault("corner_radius", RADIUS_SM)
    kwargs.setdefault("fg_color", CARD_SUBTLE_BG)
    kwargs.setdefault("button_color", NEUTRAL_SOFT)
    kwargs.setdefault("button_hover_color", ("#cbd5e1", "#475569"))
    kwargs.setdefault("dropdown_fg_color", CARD_BG)
    kwargs.setdefault("dropdown_hover_color", ACCENT_SOFT)
    kwargs.setdefault("dropdown_text_color", TEXT)
    kwargs.setdefault("text_color", TEXT)
    widget = ctk.CTkOptionMenu(master, **kwargs)
    bind_copy_menu(widget)
    return widget


def checkbox(master, **kwargs) -> ctk.CTkCheckBox:
    kwargs.setdefault("font", FONT_BODY)
    kwargs.setdefault("text_color", TEXT)
    kwargs.setdefault("fg_color", ACCENT)
    kwargs.setdefault("hover_color", ACCENT_HOVER)
    kwargs.setdefault("border_color", BORDER)
    widget = ctk.CTkCheckBox(master, **kwargs)
    bind_copy_menu(widget)
    return widget


def segmented_button(master, **kwargs) -> ctk.CTkSegmentedButton:
    kwargs.setdefault("font", FONT_BODY_STRONG)
    kwargs.setdefault("height", 34)
    kwargs.setdefault("corner_radius", RADIUS_SM)
    kwargs.setdefault("fg_color", ("#f1f5f9", "#1f2937"))
    kwargs.setdefault("selected_color", ("#cbd5e1", "#475569"))
    kwargs.setdefault("selected_hover_color", ACCENT_HOVER)
    kwargs.setdefault("unselected_color", ("#f1f5f9", "#1f2937"))
    kwargs.setdefault("unselected_hover_color", ("#cbd5e1", "#475569"))
    kwargs.setdefault("text_color", TEXT)
    kwargs.setdefault("text_color_disabled", MUTED_TEXT)
    widget = ctk.CTkSegmentedButton(master, **kwargs)
    bind_copy_menu(widget)
    return widget


def color(value) -> str:
    if isinstance(value, tuple):
        mode = ctk.get_appearance_mode().lower()
        return value[1] if mode == "dark" else value[0]
    return value


def configure_tree_style(owner) -> None:
    style = ttk.Style(owner)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "WorkTrace.Treeview",
        background=color(CARD_BG),
        fieldbackground=color(CARD_BG),
        foreground=color(TEXT),
        rowheight=36,
        borderwidth=0,
        relief="flat",
        font=FONT_CAPTION,
    )
    style.configure(
        "WorkTrace.Treeview.Heading",
        background=color(PANEL_ALT_BG),
        foreground=color(MUTED_TEXT),
        borderwidth=0,
        relief="flat",
        font=FONT_CAPTION_STRONG,
    )
    style.map(
        "WorkTrace.Treeview",
        background=[("selected", color(ACCENT_SOFT))],
        foreground=[("selected", color(ACCENT))],
    )
    style.configure(
        "WorkTrace.Vertical.TScrollbar",
        background=color(NEUTRAL_SOFT),
        troughcolor=color(PANEL_ALT_BG),
        bordercolor=color(PANEL_ALT_BG),
        arrowcolor=color(MUTED_TEXT),
        relief="flat",
        width=12,
    )
    style.configure(
        "WorkTrace.Horizontal.TScrollbar",
        background=color(NEUTRAL_SOFT),
        troughcolor=color(PANEL_ALT_BG),
        bordercolor=color(PANEL_ALT_BG),
        arrowcolor=color(MUTED_TEXT),
        relief="flat",
        width=12,
    )


def status_palette(status: str) -> tuple[tuple[str, str], tuple[str, str]]:
    if status in {"running", "记录中"}:
        return SUCCESS_SOFT, SUCCESS
    if status in {"paused", "已暂停"}:
        return WARNING_SOFT, WARNING
    if status in {"error", "状态异常"}:
        return DANGER_SOFT, DANGER
    return NEUTRAL_SOFT, MUTED_TEXT
