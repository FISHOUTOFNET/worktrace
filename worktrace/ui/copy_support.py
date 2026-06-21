from __future__ import annotations

import tkinter as tk
from typing import Callable


TextGetter = Callable[[], str]


def bind_copy_menu(widget, text_getter: TextGetter | None = None, label: str = "复制此文字") -> None:
    if widget is None or not hasattr(widget, "bind"):
        return

    def get_text() -> str:
        if text_getter is not None:
            return str(text_getter() or "")
        return _widget_text(widget)

    def show_menu(event=None):
        text = get_text().strip()
        if not text:
            return None
        try:
            menu = tk.Menu(widget, tearoff=0)
            menu.add_command(label=label, command=lambda value=text: copy_text(widget, value))
            menu.tk_popup(int(getattr(event, "x_root", 0)), int(getattr(event, "y_root", 0)))
        except Exception:
            copy_text(widget, text)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    try:
        widget.bind("<Button-3>", show_menu, add="+")
    except NotImplementedError:
        pass


def bind_tree_copy_menu(
    tree,
    *,
    cell_getter: Callable[[str, str], str],
    row_getter: Callable[[str], str],
    page_getter: TextGetter | None = None,
) -> None:
    if tree is None or not hasattr(tree, "bind"):
        return

    def show_menu(event=None):
        row_id = _identify(tree, "row", event)
        column_id = _identify(tree, "column", event)
        if row_id:
            try:
                tree.selection_set(row_id)
            except Exception:
                pass
        cell_text = cell_getter(row_id, column_id).strip() if row_id and column_id else ""
        row_text = row_getter(row_id).strip() if row_id else ""
        page_text = page_getter().strip() if page_getter is not None else ""
        if not any((cell_text, row_text, page_text)):
            return None
        try:
            menu = tk.Menu(tree, tearoff=0)
            if cell_text:
                menu.add_command(label="复制单元格", command=lambda value=cell_text: copy_text(tree, value))
            if row_text:
                menu.add_command(label="复制行", command=lambda value=row_text: copy_text(tree, value))
            if page_text:
                if cell_text or row_text:
                    menu.add_separator()
                menu.add_command(label="复制当前页文本", command=lambda value=page_text: copy_text(tree, value))
            menu.tk_popup(int(getattr(event, "x_root", 0)), int(getattr(event, "y_root", 0)))
        except Exception:
            copy_text(tree, cell_text or row_text or page_text)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    tree.bind("<Button-3>", show_menu, add="+")


def copy_text(widget, text: str) -> None:
    root = _root_for(widget)
    root.clipboard_clear()
    root.clipboard_append(str(text or ""))


def _identify(tree, part: str, event) -> str:
    if event is None or not hasattr(tree, "identify"):
        return ""
    try:
        return str(tree.identify(part, int(getattr(event, "x", 0)), int(getattr(event, "y", 0))) or "")
    except Exception:
        return ""


def _widget_text(widget) -> str:
    for key in ("text",):
        try:
            value = widget.cget(key)
        except Exception:
            value = ""
        if value:
            return str(value)
    get = getattr(widget, "get", None)
    if callable(get):
        try:
            return str(get() or "")
        except Exception:
            return ""
    return ""


def _root_for(widget):
    try:
        return widget.winfo_toplevel()
    except Exception:
        return widget
