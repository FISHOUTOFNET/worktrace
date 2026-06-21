from __future__ import annotations

import json
from datetime import date
from tkinter import messagebox, ttk
from typing import Any

import customtkinter as ctk

from ..constants import UNCATEGORIZED_PROJECT
from ..formatters import format_current_duration, format_duration, format_project_label
from ..services import activity_service, project_service, timeline_service
from ..services.live_time_service import (
    short_activity_carry_duration,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_signature,
    sync_short_activity_carry,
)
from ..services.settings_service import get_setting
from . import design
from .date_range import DateRange, classify_range, current_week_range, previous_week_range, shift_range, today_range
from .project_rule_dialog import open_project_rule_dialog


UI_FONT = design.FONT_BODY
UI_FONT_BOLD = design.FONT_BODY_STRONG
TREE_FONT = design.FONT_CAPTION
TREE_HEADING_FONT = design.FONT_CAPTION_STRONG
TREE_ROWHEIGHT = 36


class TimelineView(ctk.CTkFrame):
    def __init__(self, master, start_var=None, end_var=None):
        super().__init__(master, fg_color="transparent")
        today = timeline_service.get_default_report_date()
        self.start_var = start_var or ctk.StringVar(value=today)
        self.end_var = end_var or ctk.StringVar(value=today)
        self.date_var = self.start_var
        self.range_var = ctk.StringVar(value="今日")
        self.only_uncategorized = ctk.BooleanVar(value=False)
        self.session_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.adjust_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.activity_project_var = self.adjust_project_var

        self._project_by_name: dict[str, int] = {}
        self._project_name_by_id: dict[int, str] = {}
        self._activity_project_targets: dict[str, dict[str, Any]] = {}
        self._sessions_by_id: dict[str, dict[str, Any]] = {}
        self._details_by_id: dict[int, dict[str, Any]] = {}
        self._session_live_bases: dict[str, int] = {}
        self._detail_live_bases: dict[int, int] = {}
        self._current_snapshot: dict | None = None
        self._current_signature: tuple | None = None
        self._short_activity_carry: dict[str, Any] | None = None
        self._tree_values: dict[str, tuple[str, ...]] = {}
        self._selected_session_id: str | None = None
        self._selected_activity_id: int | None = None
        self._active_adjustment: dict[str, Any] | None = None
        self._editor_dirty = False
        self._control_active = False
        self._control_idle_after_id: str | None = None
        self._loading_editor = False
        self._session_project_dirty = False
        self._tree_column_widths: dict[str, dict[str, int]] = {}
        self._tree_keys: dict[int, str] = {}
        self._pending_session_id: str | None = None

        self._build()

    def _build(self) -> None:
        self._ensure_range_vars()
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.toolbar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.toolbar_frame.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        self.toolbar_frame.grid_columnconfigure(0, weight=1)
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=0, minsize=360)
        self.content_frame.grid_columnconfigure(1, weight=1)

        top = self.toolbar_frame
        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        self._label(title_box, text="时间详情", font=design.FONT_TITLE).pack(anchor="w")
        self.current_activity_label = self._label(
            title_box,
            text="当前活动：无",
            text_color=design.MUTED_TEXT,
            wraplength=640,
            justify="left",
        )
        self.current_activity_label.pack(anchor="w", pady=(4, 0))

        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")
        self.prev_range_button = self._button(controls, text="<", width=34, command=lambda: self._shift_visible_range(-1))
        self.prev_range_button.pack(side="left", padx=(0, 4))
        self.range_segment = design.segmented_button(
            controls,
            values=["上周", "本周", "今日"],
            variable=self.range_var,
            command=self._apply_quick_range,
            width=174,
        )
        self.range_segment.pack(side="left", padx=(0, 8))
        self.start_entry = self._entry(controls, textvariable=self.start_var, width=118)
        self.start_entry.pack(side="left")
        self.start_entry.bind("<Return>", lambda _event: self.refresh(), add="+")
        self._label(controls, text="-", text_color=design.MUTED_TEXT).pack(side="left", padx=6)
        self.end_entry = self._entry(controls, textvariable=self.end_var, width=118)
        self.end_entry.pack(side="left")
        self.end_entry.bind("<Return>", lambda _event: self.refresh(), add="+")
        self.next_range_button = self._button(controls, text=">", width=34, command=lambda: self._shift_visible_range(1))
        self.next_range_button.pack(side="left", padx=(8, 0))

        self._build_session_table()
        self._build_detail_area()
        self._build_adjustment_editor()
        self._show_adjustment_editor(False)

    def _build_session_table(self) -> None:
        self._configure_tree_style()
        self.session_panel = ctk.CTkFrame(
            self.content_frame,
            fg_color=design.CARD_BG,
            corner_radius=design.RADIUS_LG,
            border_width=1,
            border_color=design.BORDER,
        )
        self.session_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.session_panel.grid_rowconfigure(1, weight=1)
        self.session_panel.grid_columnconfigure(0, weight=1)
        session_header = ctk.CTkFrame(self.session_panel, fg_color="transparent")
        session_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        session_header.grid_columnconfigure(0, weight=1)
        session_title_row = ctk.CTkFrame(session_header, fg_color="transparent")
        session_title_row.grid(row=0, column=0, sticky="w")
        self._label(session_title_row, text="项目", font=design.FONT_SECTION).pack(side="left")
        self._checkbox(
            session_title_row,
            text="仅未归类",
            variable=self.only_uncategorized,
            command=self.refresh,
            width=92,
            height=24,
            checkbox_width=16,
            checkbox_height=16,
        ).pack(side="left", padx=(10, 0))
        self.session_count_label = self._label(session_header, text="0 条", text_color=design.MUTED_TEXT)
        self.session_count_label.grid(row=0, column=1, sticky="e")
        columns = ("time", "project", "duration", "summary")
        headings = {"time": "时间", "project": "项目", "duration": "时长", "summary": "摘要"}
        widths = {"time": 132, "project": 130, "duration": 72, "summary": 180}
        self.session_tree_frame = self._make_tree_frame(self.session_panel)
        self.session_tree_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.session_tree = self._make_tree(self.session_tree_frame, "sessions", columns, headings, widths, height=14)
        self.session_tree.bind("<<TreeviewSelect>>", self._on_session_select)

    def _build_detail_area(self) -> None:
        self.detail_panel = ctk.CTkFrame(
            self.content_frame,
            fg_color=design.CARD_BG,
            corner_radius=design.RADIUS_LG,
            border_width=1,
            border_color=design.BORDER,
        )
        self.detail_panel.grid(row=0, column=1, sticky="nsew")
        self.detail_panel.grid_rowconfigure(1, weight=1)
        self.detail_panel.grid_rowconfigure(2, weight=0)
        self.detail_panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.detail_panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)
        title_stack = ctk.CTkFrame(header, fg_color="transparent")
        title_stack.grid(row=0, column=0, sticky="ew")
        self.detail_label = self._label(title_stack, text="请选择项目会话", font=design.FONT_SECTION)
        self.detail_label.pack(anchor="w")
        self.detail_hint_label = self._label(title_stack, text="选择左侧会话后查看活动明细", text_color=design.MUTED_TEXT)
        self.detail_hint_label.pack(anchor="w", pady=(2, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.session_project_menu = self._option_menu(
            actions,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.session_project_var,
            width=160,
            command=lambda _name: self._mark_session_project_dirty(),
        )
        self.session_project_menu.pack(side="left", padx=(0, 6))
        self.save_session_project_button = self._button(
            actions,
            text="调整",
            width=72,
            command=self._save_session_project,
        )
        self.save_session_project_button.pack(side="left", padx=(0, 6))
        self.session_rule_button = self._button(
            actions,
            text="新增规则",
            width=86,
            command=self._open_project_rule_dialog,
            fg_color=design.NEUTRAL_SOFT,
            text_color=design.TEXT,
        )
        self.session_rule_button.pack(side="left", padx=(0, 6))
        self.detail_container = ctk.CTkFrame(self.detail_panel, fg_color="transparent")
        self.detail_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.detail_container.grid_rowconfigure(0, weight=1)
        self.detail_container.grid_columnconfigure(0, weight=1)

        self.detail_tree_frame = self._make_tree_frame(self.detail_container)
        self.detail_tree_frame.grid(row=0, column=0, sticky="nsew")
        self.detail_tree = self._make_tree(
            self.detail_tree_frame,
            "details",
            ("time", "app", "window", "duration", "project", "note"),
            {
                "time": "时间",
                "app": "应用",
                "window": "窗口",
                "duration": "时长",
                "project": "项目",
                "note": "备注",
            },
            {
                "time": 120,
                "app": 120,
                "window": 360,
                "duration": 90,
                "project": 120,
                "note": 180,
            },
        )
        self.detail_tree.bind("<<TreeviewSelect>>", self._on_activity_select)

        self.editor_scroll_frame = ctk.CTkFrame(
            self.detail_panel,
            fg_color=design.CARD_SUBTLE_BG,
            corner_radius=design.RADIUS_MD,
            border_width=1,
            border_color=design.BORDER,
        )
        self.editor_panel = self.editor_scroll_frame
        self.editor_scroll_frame.grid_columnconfigure(0, weight=1)

    def _build_adjustment_editor(self) -> None:
        self.adjustment_editor = ctk.CTkFrame(self.editor_panel, fg_color="transparent")
        self.adjustment_editor.grid_columnconfigure(5, weight=1)
        self.activity_editor = self.adjustment_editor
        self.adjustment_label = self._label(self.adjustment_editor, text="未选择活动", font=UI_FONT_BOLD)
        self.adjustment_label.grid(row=0, column=0, columnspan=6, sticky="w", padx=14, pady=(14, 6))
        self.activity_editor_label = self.adjustment_label
        self._label(self.adjustment_editor, text="项目", text_color=design.MUTED_TEXT).grid(row=1, column=0, sticky="w", padx=(14, 4), pady=4)
        self.adjust_project_menu = self._option_menu(
            self.adjustment_editor,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.adjust_project_var,
            width=180,
            command=lambda _name: self._mark_editor_dirty(),
        )
        self.adjust_project_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)
        self.activity_project_menu = self.adjust_project_menu
        self.save_adjustment_button = self._button(self.adjustment_editor, text="保存", width=72, command=lambda: self._save_adjustment(False))
        self.save_adjustment_button.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=4)
        self.save_activity_button = self.save_adjustment_button
        self.current_session_button = self.save_adjustment_button
        self.adjustment_rule_button = self._button(
            self.adjustment_editor,
            text="新增规则",
            width=86,
            command=self._open_adjustment_project_rule_dialog,
            fg_color=design.NEUTRAL_SOFT,
            text_color=design.TEXT,
        )
        self.adjustment_rule_button.grid(row=1, column=3, sticky="w", padx=(0, 8), pady=4)
        self.activity_rule_button = self.adjustment_rule_button
        self.delete_adjustment_button = self._button(
            self.adjustment_editor,
            text="删除",
            width=72,
            fg_color=design.DANGER,
            hover_color=design.DANGER_HOVER,
            command=self._delete_adjustment_activities,
        )
        self.delete_adjustment_button.grid(row=1, column=4, sticky="w", padx=(0, 8), pady=4)
        self.delete_activity_button = self.delete_adjustment_button
        self.adjustment_hint_label = self._label(self.adjustment_editor, text="", text_color=design.MUTED_TEXT)
        self.adjustment_hint_label.grid(row=2, column=0, columnspan=6, sticky="w", padx=14, pady=(0, 8))
        self.note_label = self._label(self.adjustment_editor, text="备注", text_color=design.MUTED_TEXT)
        self.note_label.grid(row=3, column=0, sticky="nw", padx=(14, 4), pady=(8, 14))
        self.note_text = ctk.CTkTextbox(self.adjustment_editor, height=72, font=UI_FONT, corner_radius=design.RADIUS_SM, border_width=1, border_color=design.BORDER)
        self.note_text.grid(row=3, column=1, columnspan=5, sticky="ew", padx=(0, 14), pady=(8, 14))
        self.note_text.bind("<KeyRelease>", lambda _event: self._mark_editor_dirty(), add="+")
        self._editor_widgets = [
            self.adjust_project_menu,
            self.save_adjustment_button,
            self.adjustment_rule_button,
            self.delete_adjustment_button,
            self.note_text,
        ]
        for widget in self._editor_widgets:
            widget.bind("<ButtonPress-1>", self._on_control_activity, add="+")
            widget.bind("<FocusIn>", self._on_control_activity, add="+")

    def refresh(self, ensure_context: bool = True) -> None:
        self._ensure_range_vars()
        self._current_snapshot = _read_current_activity_snapshot()
        self._current_signature = snapshot_signature(self._current_snapshot)
        self._sync_status(self._current_snapshot)
        if not self._valid_range():
            return
        self._sync_range_buttons()
        self._refresh_projects()
        sessions = timeline_service.get_project_sessions_by_range(
            self.start_var.get(),
            self.end_var.get(),
            ensure_context=ensure_context,
        )
        if self.only_uncategorized.get():
            sessions = [session for session in sessions if session["is_uncategorized"]]
        self._sync_sessions(sessions)
        self._refresh_selected_session(ensure_context=ensure_context)

    def open_context(
        self,
        target_date: str,
        only_uncategorized: bool = False,
        selected_session_id: str | None = None,
    ) -> None:
        self._ensure_range_vars()
        self.start_var.set(target_date)
        self.end_var.set(target_date)
        self.only_uncategorized.set(only_uncategorized)
        self._session_project_dirty = False
        self._editor_dirty = False
        self._pending_session_id = selected_session_id

    def is_user_interacting(self) -> bool:
        editor_focus = any(self._widget_has_focus(widget) for widget in getattr(self, "_editor_widgets", []))
        return (
            self._control_active
            or self._editor_dirty
            or self._adjustment_editor_visible()
            or editor_focus
        )

    def _sync_sessions(self, sessions: list[dict]) -> None:
        previous = self._pending_session_id or self._selected_session_id
        self._sessions_by_id = {session["session_id"]: session for session in sessions}
        self._refresh_activity_project_targets()
        self._session_live_bases = {
            session["session_id"]: self._activity_ids_live_seconds(
                session.get("activity_ids") or [],
                str(session.get("report_date") or session.get("start_time") or "")[:10],
                getattr(self, "_current_snapshot", None),
            )
            for session in sessions
        }
        display_sessions = self._sessions_with_short_activity_carry(sessions, getattr(self, "_current_snapshot", None))
        if hasattr(self, "session_count_label"):
            self.session_count_label.configure(text=f"{len(display_sessions)} 条")
        self._sync_tree(self.session_tree, [(session["session_id"], self._session_values(session)) for session in display_sessions])
        if previous in self._sessions_by_id:
            self._selected_session_id = previous
            self._select_tree_item(self.session_tree, previous)
        elif sessions:
            self._selected_session_id = sessions[0]["session_id"]
            self._select_tree_item(self.session_tree, self._selected_session_id)
        else:
            self._selected_session_id = None
            self._session_project_dirty = False
            self.session_project_var.set(UNCATEGORIZED_PROJECT)
            self.detail_label.configure(text="暂无项目会话")
            if hasattr(self, "detail_hint_label"):
                self.detail_hint_label.configure(text="调整日期或关闭筛选后再查看")
            self._sync_details([])
        self._pending_session_id = None

    def _refresh_selected_session(self, ensure_context: bool = True) -> None:
        session = self._sessions_by_id.get(self._selected_session_id or "")
        if not session:
            return
        display_session = self._session_with_short_activity_carry(session, getattr(self, "_current_snapshot", None))
        self._sync_selected_session_summary(display_session)
        self._sync_details(
            timeline_service.get_session_activity_details(
                session["activity_ids"],
                report_date=session.get("report_date"),
                ensure_context=ensure_context,
            )
        )

    def _sync_selected_session_summary(self, session: dict) -> None:
        self.detail_label.configure(
            text=f"{self._session_time(session)} | {format_project_label(session['project_name'], session.get('project_description'))}"
        )
        if hasattr(self, "detail_hint_label"):
            self.detail_hint_label.configure(
                text=f"{format_duration(session['duration_seconds'])} | {session['event_count']} 条活动 | {session['status_summary']}"
            )
        if not getattr(self, "_session_project_dirty", False):
            self.session_project_var.set(self._project_name_by_id.get(int(session["project_id"]), UNCATEGORIZED_PROJECT))

    def _sync_details(self, details: list[dict]) -> None:
        previous = self._selected_activity_id
        keep_editor_open = self._activity_editor_visible()
        self._details_by_id = {int(row["id"]): row for row in details}
        report_date = self._selected_session_report_date()
        self._detail_live_bases = {
            int(row["id"]): self._activity_ids_live_seconds(
                [int(row["id"])],
                report_date,
                getattr(self, "_current_snapshot", None),
            )
            for row in details
        }
        self._sync_tree(self.detail_tree, [(str(row["id"]), self._detail_values(row)) for row in details])
        if previous in self._details_by_id:
            self._select_tree_item(self.detail_tree, str(previous))
            if keep_editor_open:
                self._load_activity_editor(previous)
        elif not self._editor_dirty:
            self._selected_activity_id = None
            self._active_adjustment = None
            self._show_activity_editor(False)

    def _sync_tree(self, tree: ttk.Treeview, items: list[tuple[str, tuple[str, ...]]]) -> None:
        old_children = list(tree.get_children())
        current = {iid for iid, _values in items}
        yview = tree.yview()
        for iid in old_children:
            if iid not in current:
                tree.delete(iid)
                self._tree_values.pop(f"{id(tree)}:{iid}", None)
        for index, (iid, values) in enumerate(items):
            key = f"{id(tree)}:{iid}"
            if not tree.exists(iid):
                tree.insert("", index, iid=iid, values=values)
            else:
                if self._tree_values.get(key) != values:
                    tree.item(iid, values=values)
                tree.move(iid, "", index)
            self._tree_values[key] = values
        self._apply_tree_column_widths(tree)
        xview = tree.xview() if hasattr(tree, "xview") else (0.0, 1.0)

        def restore(y_position=yview[0], x_position=xview[0], target=tree) -> None:
            target.yview_moveto(y_position)
            if hasattr(target, "xview_moveto"):
                target.xview_moveto(x_position)

        if hasattr(self, "after_idle"):
            self.after_idle(restore)
        else:
            restore()

    def _sync_tree_values_only(self, tree: ttk.Treeview, items: list[tuple[str, tuple[str, ...]]]) -> bool:
        existing = list(tree.get_children())
        incoming = [iid for iid, _values in items]
        if existing != incoming:
            return False
        for iid, values in items:
            key = f"{id(tree)}:{iid}"
            if self._tree_values.get(key) != values:
                tree.item(iid, values=values)
            self._tree_values[key] = values
        return True

    def _on_session_select(self, _event=None) -> None:
        selection = self.session_tree.selection()
        if not selection:
            return
        self._selected_session_id = selection[0]
        self._selected_activity_id = None
        self._session_project_dirty = False
        self._editor_dirty = False
        self._refresh_selected_session()

    def _on_activity_select(self, _event=None) -> None:
        selection = self.detail_tree.selection()
        if not selection:
            if not self._editor_dirty:
                self._selected_activity_id = None
                self._active_adjustment = None
                self._show_activity_editor(False)
            return
        activity_id = int(selection[0])
        if self._editor_dirty and self._selected_activity_id != activity_id:
            self._select_tree_item(self.detail_tree, str(self._selected_activity_id))
            self.activity_editor_label.configure(text="当前修改未保存，请先保存后再切换记录")
            return
        self._selected_activity_id = activity_id
        self._load_activity_editor(activity_id)

    def _save_session_project(self) -> None:
        session = self._sessions_by_id.get(self._selected_session_id or "")
        if not session:
            return
        project_id = self._project_by_name.get(self.session_project_var.get())
        if project_id is None:
            messagebox.showerror("保存失败", "请选择有效项目")
            return
        preview = timeline_service.preview_session_project_update(session["activity_ids"], project_id)
        if any(preview.values()):
            if not messagebox.askyesno("锚点文件归属提示", self._format_session_project_preview(preview)):
                return
        timeline_service.update_session_project(session["activity_ids"], project_id)
        self._session_project_dirty = False
        self.refresh()

    def _format_session_project_preview(self, preview: dict) -> str:
        parts = []
        if preview["folder_rule_conflicts"]:
            parts.append("以下锚点文件命中了其他项目的文件夹规则：")
            parts.extend(self._preview_lines(preview["folder_rule_conflicts"]))
        if preview["unassigned_anchor_files"]:
            parts.append("以下锚点文件还没有命中目标项目的文件夹规则：")
            parts.extend(self._preview_lines(preview["unassigned_anchor_files"]))
        parts.append("")
        parts.append("继续后只会修改当前会话活动归属，不会自动修改文件夹或关键词规则。")
        return "\n".join(parts)

    def _preview_lines(self, rows: list[dict], limit: int = 12) -> list[str]:
        lines = []
        for row in rows[:limit]:
            location = row.get("full_path") or row.get("parent_dir") or ""
            current = row.get("current_project_name") or "未设置"
            suffix = f"｜当前：{current}" if current != "未设置" else ""
            lines.append(f"- {row.get('display_name') or '未知文件'}{suffix}｜{location}")
        if len(rows) > limit:
            lines.append(f"- 另有 {len(rows) - limit} 个文件未显示")
        return lines

    def _open_project_rule_dialog(self) -> None:
        project_name = self.session_project_var.get()
        if project_name == UNCATEGORIZED_PROJECT:
            project_name = None
        open_project_rule_dialog(
            self,
            initial_type="folder",
            initial_target=self._default_session_folder(),
            initial_project_name=project_name,
            on_saved=self._after_project_rule_saved,
        )

    def _after_project_rule_saved(self, result: dict) -> None:
        project_name = str(result.get("project_name") or "")
        self._refresh_projects()
        if project_name in self._project_by_name:
            self.session_project_var.set(project_name)
            self.activity_project_var.set(project_name)
            self.adjustment_hint_label.configure(text=f"已保存新建项目规则：{project_name}")
        self.refresh()

    def _default_session_folder(self) -> str:
        session = self._sessions_by_id.get(self._selected_session_id or "")
        if not session:
            return ""
        folders = timeline_service.get_session_anchor_folders(session["activity_ids"])
        return folders[0] if folders else ""

    def _load_activity_editor(self, activity_id: int) -> None:
        row = self._details_by_id.get(activity_id)
        if not row:
            self._show_activity_editor(False)
            return
        self._show_activity_editor(True)
        self._active_adjustment = self._adjustment_from_activity(row)
        self._loading_editor = True
        self.adjust_project_var.set(self._activity_target_label_for_row(row))
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", row.get("note") or "")
        self._set_note_visible(True)
        self.adjustment_hint_label.configure(text="")
        self._loading_editor = False
        self._editor_dirty = False
        self.activity_editor_label.configure(text=self._active_adjustment["label"])

    def _save_activity(self) -> None:
        self._save_adjustment(False)

    def _delete_activity(self) -> None:
        self._delete_adjustment_activities()

    def _open_activity_project_rule_dialog(self) -> None:
        self._open_adjustment_project_rule_dialog()

    def _open_adjustment_project_rule_dialog(self) -> None:
        adjustment = self._active_adjustment or {}
        if not adjustment:
            return
        project_name = self.adjust_project_var.get()
        if project_name == UNCATEGORIZED_PROJECT:
            project_name = None
        open_project_rule_dialog(
            self,
            initial_type=str(adjustment.get("rule_type") or "keyword"),
            initial_target=str(adjustment.get("rule_target") or ""),
            initial_project_name=project_name,
            on_saved=self._after_project_rule_saved,
        )

    def _refresh_activity_project_targets(self) -> None:
        targets: dict[str, dict[str, Any]] = {}
        project_by_name = getattr(self, "_project_by_name", {})
        project_name_by_id = getattr(self, "_project_name_by_id", {})
        names = list(project_by_name)
        if UNCATEGORIZED_PROJECT not in names:
            names.insert(0, UNCATEGORIZED_PROJECT)
        for name in names:
            project_id = project_by_name.get(name)
            if project_id is None and name == UNCATEGORIZED_PROJECT:
                project_id = next((pid for pid, pname in project_name_by_id.items() if pname == UNCATEGORIZED_PROJECT), None)
            if project_id is not None:
                targets[name] = {"project_id": int(project_id), "label": name}
        self._activity_project_targets = targets
        menu = getattr(self, "activity_project_menu", None)
        if menu is not None:
            menu.configure(values=list(targets) or [UNCATEGORIZED_PROJECT])

    def _activity_target_label_for_row(self, row: dict) -> str:
        return row.get("official_project_name") or UNCATEGORIZED_PROJECT

    def _adjustment_from_activity(self, row: dict) -> dict[str, Any]:
        is_anchor_file = bool(row.get("is_anchor_file"))
        folder_target = row.get("anchor_parent_dir") or ""
        target = folder_target or row.get("activity_display_name") or row.get("window_title") or ""
        return {
            "kind": "activity",
            "activity_ids": [int(row["id"])],
            "project_id": int(row.get("project_id") or 0),
            "project_name": row.get("official_project_name") or UNCATEGORIZED_PROJECT,
            "label": f"正在调整：{self._detail_values(row)[0]}｜{row.get('app_name') or ''}",
            "rule_type": "folder" if is_anchor_file and folder_target else "keyword",
            "rule_target": str(target),
            "note": row.get("note") or "",
        }

    def _save_adjustment(self, remember: bool = False) -> None:
        adjustment = self._active_adjustment or {}
        activity_ids = [int(value) for value in adjustment.get("activity_ids") or []]
        if not adjustment or not activity_ids:
            return
        project_id = self._project_by_name.get(self.adjust_project_var.get())
        if project_id is None:
            self.adjustment_hint_label.configure(text="请选择有效项目")
            return
        if int(adjustment.get("project_id") or 0) != int(project_id):
            timeline_service.update_activity_group_project(activity_ids, int(project_id))
        if adjustment.get("kind") == "activity":
            activity_id = activity_ids[0]
            row = self._details_by_id.get(activity_id) or {}
            note = self.note_text.get("1.0", "end-1c")
            if (row.get("note") or "") != note:
                activity_service.update_activity_note(activity_id, note)
            self._editor_dirty = False
            self._focus_activity_after_refresh(activity_id)
            return
        self._editor_dirty = False
        self.refresh()

    def _delete_adjustment_activities(self) -> None:
        adjustment = self._active_adjustment or {}
        activity_ids = [int(value) for value in adjustment.get("activity_ids") or []]
        if not activity_ids:
            return
        if len(activity_ids) > 1 and not messagebox.askyesno("删除活动", "将删除当前会话中这组活动记录。是否继续？"):
            return
        for activity_id in activity_ids:
            activity_service.soft_delete_activity(activity_id)
        self._selected_activity_id = None
        self._active_adjustment = None
        self._editor_dirty = False
        self.refresh()

    def _focus_activity_after_refresh(self, activity_id: int) -> None:
        self._selected_activity_id = activity_id
        target_session = self._find_session_containing_activity(activity_id)
        if target_session and self.only_uncategorized.get() and not target_session.get("is_uncategorized"):
            self.only_uncategorized.set(False)
            target_session = self._find_session_containing_activity(activity_id)
        if target_session:
            self._pending_session_id = str(target_session["session_id"])
        self.refresh(ensure_context=False)
        if hasattr(self, "detail_tree") and self.detail_tree.exists(str(activity_id)):
            self._select_tree_item(self.detail_tree, str(activity_id))
            self._load_activity_editor(activity_id)

    def _find_session_containing_activity(self, activity_id: int) -> dict | None:
        sessions = timeline_service.get_project_sessions_by_range(
            self.start_var.get(),
            self.end_var.get(),
            include_hidden=True,
            ensure_context=False,
        )
        visible_sessions = [session for session in sessions if session["is_uncategorized"]] if self.only_uncategorized.get() else sessions
        for session in visible_sessions:
            if activity_id in {int(value) for value in session.get("activity_ids") or []}:
                return session
        if self.only_uncategorized.get():
            for session in sessions:
                if activity_id in {int(value) for value in session.get("activity_ids") or []}:
                    self.only_uncategorized.set(False)
                    return session
        return None

    def _refresh_projects(self) -> None:
        projects = project_service.list_selectable_projects()
        self._project_by_name = {p["name"]: int(p["id"]) for p in projects}
        self._project_name_by_id = {int(p["id"]): p["name"] for p in projects}
        names = list(self._project_by_name)
        if UNCATEGORIZED_PROJECT not in names:
            names.insert(0, UNCATEGORIZED_PROJECT)
        for menu_name in ("session_project_menu", "activity_project_menu"):
            menu = getattr(self, menu_name, None)
            if menu is not None:
                menu.configure(values=names or [UNCATEGORIZED_PROJECT])
        self._refresh_activity_project_targets()

    def _sync_status(self, snapshot: dict | None = None) -> None:
        self.current_activity_label.configure(text=self._current_activity_text(snapshot))

    def refresh_current_activity(self) -> None:
        self._ensure_range_vars()
        snapshot = _read_current_activity_snapshot()
        signature = snapshot_signature(snapshot)
        self._sync_short_activity_carry(snapshot)
        self.current_activity_label.configure(text=self._current_activity_text(snapshot))
        if signature != self._current_signature:
            if not self._valid_range(show_message=False):
                self._current_snapshot = snapshot
                return
            if self.is_user_interacting():
                self._current_snapshot = snapshot
                return
            self.refresh(ensure_context=False)
            return
        self._current_snapshot = snapshot
        if not self._valid_range(show_message=False) or self.is_user_interacting():
            return
        if not self._refresh_live_table_values(snapshot):
            self.refresh(ensure_context=False)

    def copy_selection_text(self) -> str:
        for tree in (self.detail_tree, getattr(self, "session_tree", None)):
            text = self._copy_tree_selection(tree)
            if text:
                return text
        return ""

    def copy_page_text(self) -> str:
        self._ensure_range_vars()
        lines = [
            "时间详情",
            f"日期范围：{self.start_var.get()} 至 {self.end_var.get()}",
            self.current_activity_label.cget("text"),
            "",
            "项目",
            *self._tree_rows_text(self.session_tree),
        ]
        lines.extend(["", "时间顺序", *self._tree_rows_text(self.detail_tree)])
        return "\n".join(line for line in lines if line)

    def _copy_tree_selection(self, tree) -> str:
        if tree is None:
            return ""
        try:
            selection = tree.selection()
        except Exception:
            return ""
        lines = []
        for iid in selection:
            values = self._tree_values.get(f"{id(tree)}:{iid}")
            if values:
                lines.append("\t".join(str(value) for value in values))
        return "\n".join(lines)

    def _tree_rows_text(self, tree) -> list[str]:
        rows = []
        try:
            children = tree.get_children()
        except Exception:
            return rows
        for iid in children:
            values = self._tree_values.get(f"{id(tree)}:{iid}")
            if values:
                rows.append("｜".join(str(value) for value in values))
        return rows

    def _refresh_live_table_values(self, snapshot: dict | None) -> bool:
        self._ensure_range_vars()
        sessions = self._live_sessions(snapshot)
        if self.only_uncategorized.get():
            sessions = [session for session in sessions if session["is_uncategorized"]]
        session_items = [(session["session_id"], self._session_values(session)) for session in sessions]
        if not self._sync_tree_values_only(self.session_tree, session_items):
            return False
        if hasattr(self, "session_count_label"):
            self.session_count_label.configure(text=f"{len(sessions)} 条")
        if not sessions:
            self._selected_session_id = None
            return True
        session = self._sessions_by_id.get(self._selected_session_id or "")
        if not session:
            return False
        live_session = next((item for item in sessions if item["session_id"] == self._selected_session_id), session)
        self._sync_selected_session_summary(live_session)
        details = self._live_details(snapshot)
        detail_items = [(str(row["id"]), self._detail_values(row)) for row in details]
        if not self._sync_tree_values_only(self.detail_tree, detail_items):
            return False
        if self._selected_activity_id is not None and self._selected_activity_id not in self._details_by_id:
            return False
        return True

    def _current_activity_text(self, snapshot: dict | None = None) -> str:
        if snapshot is None:
            snapshot = _read_current_activity_snapshot()
        if not snapshot:
            return "当前活动：无"
        name = snapshot.get("activity_display_name") or snapshot.get("app_name") or snapshot.get("process_name") or "未知"
        project = snapshot.get("inferred_project_name") or UNCATEGORIZED_PROJECT
        elapsed = format_current_duration(_current_elapsed_seconds(snapshot))
        state = "已进入历史" if snapshot.get("is_persisted") else "暂不入历史"
        if snapshot.get("status") == "idle":
            name = "空闲中"
        return f"当前活动：{name}｜{project}｜{elapsed}｜{state}"

    def _live_sessions(self, snapshot: dict | None) -> list[dict]:
        sessions = [
            self._with_live_duration(
                session,
                "duration_seconds",
                session.get("activity_ids") or [],
                self._session_live_bases.get(str(session["session_id"]), 0),
                str(session.get("report_date") or session.get("start_time") or "")[:10],
                snapshot,
            )
            for session in sorted(self._sessions_by_id.values(), key=lambda row: (str(row.get("start_time") or ""), str(row.get("session_id") or "")), reverse=True)
        ]
        return self._sessions_with_short_activity_carry(sessions, snapshot)

    def _sync_short_activity_carry(self, snapshot: dict | None) -> None:
        previous = getattr(self, "_current_snapshot", None)
        self._short_activity_carry = sync_short_activity_carry(
            getattr(self, "_short_activity_carry", None),
            previous,
            snapshot,
        )

    def _sessions_with_short_activity_carry(self, sessions: list[dict], snapshot: dict | None) -> list[dict]:
        return [self._session_with_short_activity_carry(session, snapshot) for session in sessions]

    def _session_with_short_activity_carry(self, session: dict, snapshot: dict | None) -> dict:
        duration = self._short_activity_carry_duration(session, snapshot)
        if duration is None:
            return session
        item = dict(session)
        item["duration_seconds"] = duration
        return item

    def _short_activity_carry_duration(self, session: dict, snapshot: dict | None) -> int | None:
        carry = getattr(self, "_short_activity_carry", None)
        report_date = str(session.get("report_date") or session.get("start_time") or "")[:10]
        return short_activity_carry_duration(
            carry,
            [int(value) for value in session.get("activity_ids") or []],
            int(session.get("duration_seconds") or 0),
            report_date,
            snapshot,
        )

    def _live_details(self, snapshot: dict | None) -> list[dict]:
        return [
            self._with_live_duration(
                row,
                "duration_seconds",
                [int(row["id"])],
                self._detail_live_bases.get(int(row["id"]), 0),
                self._selected_session_report_date(),
                snapshot,
            )
            for row in sorted(self._details_by_id.values(), key=lambda item: (str(item.get("start_time") or ""), int(item.get("id") or 0)), reverse=True)
        ]

    def _with_live_duration(
        self,
        row: dict,
        duration_key: str,
        activity_ids: list[int],
        base_live_seconds: int,
        report_date: str,
        snapshot: dict | None,
    ) -> dict:
        current_live = self._activity_ids_live_seconds(activity_ids, report_date, snapshot)
        delta = max(0, current_live - int(base_live_seconds or 0))
        if not delta:
            return dict(row)
        item = dict(row)
        item[duration_key] = int(item.get(duration_key) or 0) + delta
        return item

    def _activity_ids_live_seconds(self, activity_ids: list[int], report_date: str, snapshot: dict | None) -> int:
        persisted_id = snapshot_persisted_id(snapshot)
        if persisted_id is None or persisted_id not in {int(activity_id) for activity_id in activity_ids}:
            return 0
        if not report_date:
            return 0
        return snapshot_seconds_for_date_range(snapshot, report_date, report_date)

    def _selected_session_report_date(self) -> str:
        session = getattr(self, "_sessions_by_id", {}).get(getattr(self, "_selected_session_id", None) or "")
        return str((session or {}).get("report_date") or (session or {}).get("start_time") or "")[:10]

    def _session_values(self, session: dict) -> tuple[str, ...]:
        return (
            self._session_time(session),
            format_project_label(session["project_name"], session.get("project_description")),
            format_duration(session["duration_seconds"]),
            str(session["status_summary"]),
        )

    def _detail_values(self, row: dict) -> tuple[str, ...]:
        note = " ".join(str(row.get("note") or "").split())
        if len(note) > 28:
            note = f"{note[:28]}..."
        start = row.get("start_time") or ""
        end = row.get("end_time") or ""
        return (
            f"{start[11:16] if len(start) >= 16 else start}-{end[11:16] if len(end) >= 16 else ''}",
            str(row.get("app_name") or ""),
            str(row.get("window_title") or ""),
            format_duration(row.get("duration_seconds") or 0),
            format_project_label(row.get("project_name") or UNCATEGORIZED_PROJECT, row.get("project_description")),
            note,
        )

    def _session_time(self, session: dict) -> str:
        start = session.get("start_time") or ""
        end = session.get("end_time") or ""
        prefix = f"{start[5:10]} " if self._include_session_dates() and len(start) >= 10 else ""
        return f"{prefix}{start[11:16] if len(start) >= 16 else start}-{end[11:16] if len(end) >= 16 else ''}"

    def _label(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        kwargs.setdefault("text_color", design.TEXT)
        return ctk.CTkLabel(master, **kwargs)

    def _button(self, master, **kwargs):
        variant = kwargs.pop("variant", "primary")
        kwargs.setdefault("font", UI_FONT)
        return design.button(master, variant=variant, **kwargs)

    def _checkbox(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        return design.checkbox(master, **kwargs)

    def _entry(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        kwargs.setdefault("height", 34)
        kwargs.setdefault("corner_radius", design.RADIUS_SM)
        kwargs.setdefault("border_color", design.BORDER)
        return ctk.CTkEntry(master, **kwargs)

    def _option_menu(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        kwargs.setdefault("dropdown_font", UI_FONT)
        return design.option_menu(master, **kwargs)

    def _make_tree_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=design.PANEL_ALT_BG, corner_radius=design.RADIUS_MD)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)
        return frame

    def _make_tree(self, master, tree_key, columns, headings, widths, height=None) -> ttk.Treeview:
        kwargs = {"columns": columns, "show": "headings", "style": "WorkTrace.Treeview"}
        if height is not None:
            kwargs["height"] = height
        tree = ttk.Treeview(master, **kwargs)
        self._tree_keys[id(tree)] = tree_key
        for column in columns:
            width = widths[column]
            minwidth = max(60, min(width, 120))
            if column in {"summary", "window", "note"}:
                minwidth = max(minwidth, 120)
            tree.heading(column, text=headings[column])
            tree.column(column, width=width, minwidth=minwidth, anchor="w", stretch=False)
        vertical_scrollbar = ttk.Scrollbar(
            master,
            orient="vertical",
            command=tree.yview,
            style="WorkTrace.Vertical.TScrollbar",
        )
        horizontal_scrollbar = ttk.Scrollbar(
            master,
            orient="horizontal",
            command=tree.xview,
            style="WorkTrace.Horizontal.TScrollbar",
        )
        tree.configure(yscrollcommand=vertical_scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        tree.bind("<ButtonRelease-1>", lambda _event, target=tree: self._save_tree_column_widths(target), add="+")
        self._apply_tree_column_widths(tree)
        return tree

    def _configure_tree_style(self) -> None:
        design.configure_tree_style(self)

    def _save_tree_column_widths(self, tree: ttk.Treeview) -> None:
        tree_key = self._tree_keys.get(id(tree))
        if tree_key is None:
            return
        self._tree_column_widths[tree_key] = {
            column: int(tree.column(column, "width"))
            for column in tree["columns"]
        }

    def _apply_tree_column_widths(self, tree: ttk.Treeview) -> None:
        tree_key = self._tree_keys.get(id(tree))
        if tree_key is None:
            return
        for column, width in self._tree_column_widths.get(tree_key, {}).items():
            if column in tree["columns"]:
                tree.column(column, width=width)

    def _show_activity_editor(self, show: bool) -> None:
        self._show_adjustment_editor(show)

    def _show_adjustment_editor(self, show: bool) -> None:
        if show:
            self._show_editor_panel(True)
            self.adjustment_editor.grid(row=0, column=0, sticky="ew")
        else:
            self.adjustment_editor.grid_remove()
            self._show_editor_panel(False)

    def _show_editor_panel(self, show: bool) -> None:
        if show:
            self.editor_scroll_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        else:
            self.editor_scroll_frame.grid_remove()

    def _set_note_visible(self, visible: bool) -> None:
        if visible:
            self.note_label.grid(row=3, column=0, sticky="nw", padx=(14, 4), pady=(8, 14))
            self.note_text.grid(row=3, column=1, columnspan=5, sticky="ew", padx=(0, 14), pady=(8, 14))
        else:
            self.note_label.grid_remove()
            self.note_text.grid_remove()

    def _select_tree_item(self, tree: ttk.Treeview, iid: str | None) -> None:
        if iid is None or not tree.exists(iid):
            return
        tree.selection_set(iid)
        tree.focus(iid)
        if hasattr(tree, "see"):
            tree.see(iid)

    def _include_session_dates(self) -> bool:
        self._ensure_range_vars()
        return self.start_var.get() != self.end_var.get()

    def _apply_today_range(self) -> None:
        self._set_visible_range(today_range(timeline_service.get_default_report_date()))

    def _apply_current_week_range(self) -> None:
        self._set_visible_range(current_week_range(timeline_service.get_default_report_date()))

    def _apply_previous_week_range(self) -> None:
        self._set_visible_range(previous_week_range(timeline_service.get_default_report_date()))

    def _apply_quick_range(self, value: str) -> None:
        if value == "上周":
            self._apply_previous_week_range()
        elif value == "本周":
            self._apply_current_week_range()
        elif value == "今日":
            self._apply_today_range()

    def _shift_visible_range(self, direction: int) -> None:
        shifted = shift_range(self.start_var.get(), self.end_var.get(), direction)
        if shifted is None:
            return
        self._set_visible_range(shifted)

    def _set_visible_range(self, date_range: DateRange) -> None:
        self.start_var.set(date_range.start)
        self.end_var.set(date_range.end)
        self._session_project_dirty = False
        self._editor_dirty = False
        self.refresh()

    def _sync_range_buttons(self) -> None:
        state = "normal" if classify_range(self.start_var.get(), self.end_var.get()) != "custom" else "disabled"
        for button_name in ("prev_range_button", "next_range_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.configure(state=state)
        if hasattr(self, "range_var"):
            self.range_var.set(self._active_range_label())

    def _active_range_label(self) -> str:
        today = timeline_service.get_default_report_date()
        current = DateRange(self.start_var.get(), self.end_var.get(), classify_range(self.start_var.get(), self.end_var.get()))
        if current == previous_week_range(today):
            return "上周"
        if current == current_week_range(today):
            return "本周"
        if current == today_range(today):
            return "今日"
        return ""

    def _valid_range(self, show_message: bool = True) -> bool:
        self._ensure_range_vars()
        try:
            start = date.fromisoformat(self.start_var.get())
            end = date.fromisoformat(self.end_var.get())
        except ValueError:
            if show_message:
                self.current_activity_label.configure(text="日期格式错误，请使用 YYYY-MM-DD")
            self._sync_range_buttons()
            return False
        if start > end:
            if show_message:
                self.current_activity_label.configure(text="日期范围错误，开始日期不能晚于结束日期")
            self._sync_range_buttons()
            return False
        return True

    def _ensure_range_vars(self) -> None:
        if not hasattr(self, "start_var"):
            if hasattr(self, "date_var"):
                self.start_var = self.date_var
            else:
                self.start_var = ctk.StringVar(value=timeline_service.get_default_report_date())
        if not hasattr(self, "end_var"):
            self.end_var = self.start_var
        if not hasattr(self, "date_var"):
            self.date_var = self.start_var
        if not hasattr(self, "range_var"):
            try:
                self.range_var = ctk.StringVar(value="今日")
            except RuntimeError:
                self.range_var = self.start_var

    def _valid_date(self, value: str) -> bool:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    def _mark_session_project_dirty(self) -> None:
        self._session_project_dirty = True
        self._on_control_activity()

    def _mark_editor_dirty(self) -> None:
        if not self._loading_editor:
            self._editor_dirty = True
            self.activity_editor_label.configure(text="当前修改未保存")

    def _on_control_activity(self, _event=None) -> None:
        self._control_active = True
        if self._control_idle_after_id is not None:
            self.after_cancel(self._control_idle_after_id)
        self._control_idle_after_id = self.after(800, self._clear_control_activity)

    def _clear_control_activity(self) -> None:
        self._control_active = False
        self._control_idle_after_id = None

    def _widget_has_focus(self, widget) -> bool:
        focused = self.focus_get()
        while focused is not None:
            if focused == widget:
                return True
            focused = getattr(focused, "master", None)
        return False

    def _activity_editor_visible(self) -> bool:
        return self._adjustment_editor_visible() and (self._active_adjustment or {}).get("kind") == "activity"

    def _adjustment_editor_visible(self) -> bool:
        try:
            return bool(self.adjustment_editor.winfo_ismapped())
        except Exception:
            return False

    def _close_activity_editor(self) -> None:
        self._selected_activity_id = None
        self._active_adjustment = None
        self._editor_dirty = False
        if hasattr(self, "detail_tree"):
            self.detail_tree.selection_remove(self.detail_tree.selection())
        self._show_activity_editor(False)


def _current_elapsed_seconds(snapshot: dict) -> int:
    return snapshot_elapsed_seconds(snapshot) + snapshot_extra_seconds(snapshot)


def _read_current_activity_snapshot() -> dict | None:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
