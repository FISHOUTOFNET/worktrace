from __future__ import annotations

import json
import time
from datetime import date
from tkinter import filedialog, messagebox, ttk
from typing import Any

import customtkinter as ctk

from ..constants import UNCATEGORIZED_PROJECT
from ..exports.markdown_exporter import format_duration
from ..services import activity_service, folder_rule_service, project_service, timeline_service
from ..services.settings_service import get_bool_setting, get_setting, set_setting


UI_FONT = ("Microsoft YaHei UI", 13)
UI_FONT_BOLD = ("Microsoft YaHei UI", 13, "bold")
TREE_FONT = ("Microsoft YaHei UI", 12)
TREE_HEADING_FONT = ("Microsoft YaHei UI", 12, "bold")
TREE_ROWHEIGHT = 36


class TimelineView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.date_var = ctk.StringVar(value=date.today().isoformat())
        self.only_uncategorized = ctk.BooleanVar(value=False)
        self.session_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.resource_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.new_project_var = ctk.StringVar(value="")
        self.activity_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.billable_var = ctk.BooleanVar(value=False)

        self._project_by_name: dict[str, int] = {}
        self._project_name_by_id: dict[int, str] = {}
        self._sessions_by_id: dict[str, dict[str, Any]] = {}
        self._resources_by_id: dict[int, dict[str, Any]] = {}
        self._details_by_id: dict[int, dict[str, Any]] = {}
        self._tree_values: dict[str, tuple[str, ...]] = {}
        self._selected_session_id: str | None = None
        self._selected_resource_id: int | None = None
        self._selected_activity_id: int | None = None
        self._detail_mode = "resources"
        self._editor_dirty = False
        self._control_active = False
        self._control_idle_after_id: str | None = None
        self._loading_editor = False
        self._resource_selected_at = 0.0
        self._tree_column_widths: dict[str, dict[str, int]] = {}
        self._tree_keys: dict[int, str] = {}

        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.toolbar_frame = ctk.CTkFrame(self)
        self.toolbar_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(1, weight=0)
        self.content_frame.grid_rowconfigure(2, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.editor_scroll_frame = ctk.CTkScrollableFrame(self, height=260)
        self.editor_panel = self.editor_scroll_frame
        self.editor_scroll_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.editor_scroll_frame.grid_columnconfigure(0, weight=1)

        top = self.toolbar_frame
        self.status_label = self._label(top, text="采集器未运行")
        self.status_label.pack(side="left", padx=6)
        self.pause_button = self._button(top, text="暂停", width=90, command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=6)
        self._label(top, text="日期").pack(side="left", padx=(16, 4))
        self.date_entry = self._entry(top, textvariable=self.date_var, width=120)
        self.date_entry.pack(side="left")
        self.refresh_button = self._button(top, text="刷新", width=70, command=self.refresh)
        self.refresh_button.pack(side="left", padx=6)
        self._checkbox(top, text="仅未归类", variable=self.only_uncategorized, command=self.refresh).pack(side="left", padx=6)
        self.current_activity_label = self._label(top, text="当前活动：无")
        self.current_activity_label.pack(side="left", padx=(16, 6))

        self._build_session_table()
        self._build_detail_area()
        self._build_resource_editor()
        self._build_activity_editor()
        self._show_resource_editor(False)
        self._show_activity_editor(False)

    def _build_session_table(self) -> None:
        self._configure_tree_style()
        columns = ("time", "project", "duration", "count", "summary")
        headings = {"time": "时间", "project": "项目/状态", "duration": "时长", "count": "活动数", "summary": "摘要"}
        widths = {"time": 128, "project": 180, "duration": 100, "count": 72, "summary": 420}
        self.session_tree_frame = self._make_tree_frame(self.content_frame)
        self.session_tree_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.session_tree = self._make_tree(self.session_tree_frame, "sessions", columns, headings, widths, height=8)
        self.session_tree.bind("<<TreeviewSelect>>", self._on_session_select)

    def _build_detail_area(self) -> None:
        header = ctk.CTkFrame(self.content_frame)
        header.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.detail_label = self._label(header, text="请选择项目会话")
        self.detail_label.pack(side="left", padx=6, pady=6)
        self.folder_rule_button = self._button(
            header,
            text="文件夹项目规则",
            width=130,
            command=self._open_folder_rule_dialog,
        )
        self.folder_rule_button.pack(side="left", padx=(8, 4), pady=6)
        self._label(header, text="整体项目").pack(side="left", padx=(8, 4), pady=6)
        self.session_project_menu = self._option_menu(
            header,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.session_project_var,
            width=160,
        )
        self.session_project_menu.pack(side="left", padx=(0, 4), pady=6)
        self.save_session_project_button = self._button(
            header,
            text="调整当前会话",
            width=120,
            command=self._save_session_project,
        )
        self.save_session_project_button.pack(side="left", padx=4, pady=6)
        self.create_session_project_button = self._button(
            header,
            text="新建项目",
            width=86,
            command=self._create_project_for_session,
        )
        self.create_session_project_button.pack(side="left", padx=4, pady=6)
        self.toggle_detail_button = self._button(
            header,
            text="查看时间顺序明细",
            width=150,
            command=self._toggle_detail_mode,
        )
        self.toggle_detail_button.pack(side="right", padx=6, pady=6)

        self.detail_container = ctk.CTkFrame(self.content_frame)
        self.detail_container.grid(row=2, column=0, sticky="nsew")
        self.detail_container.grid_rowconfigure(0, weight=1)
        self.detail_container.grid_columnconfigure(0, weight=1)

        self.resource_tree_frame = self._make_tree_frame(self.detail_container)
        self.resource_tree_frame.grid(row=0, column=0, sticky="nsew")
        self.resource_tree = self._make_tree(
            self.resource_tree_frame,
            "resources",
            ("resource", "type", "duration", "count", "project"),
            {
                "resource": "资源",
                "type": "类型",
                "duration": "时长",
                "count": "活动数",
                "project": "当前项目",
            },
            {"resource": 360, "type": 92, "duration": 100, "count": 72, "project": 160},
        )
        self.resource_tree.bind("<<TreeviewSelect>>", self._on_resource_select)

        self.detail_tree_frame = self._make_tree_frame(self.detail_container)
        self.detail_tree = self._make_tree(
            self.detail_tree_frame,
            "details",
            ("time", "app", "window", "resource", "duration", "project", "billable", "note"),
            {
                "time": "时间",
                "app": "应用",
                "window": "窗口",
                "resource": "资源",
                "duration": "时长",
                "project": "项目",
                "billable": "计费",
                "note": "备注",
            },
            {
                "time": 120,
                "app": 120,
                "window": 300,
                "resource": 160,
                "duration": 90,
                "project": 120,
                "billable": 64,
                "note": 180,
            },
        )
        self.detail_tree.bind("<<TreeviewSelect>>", self._on_activity_select)
        self.detail_tree_frame.grid_remove()

    def _build_resource_editor(self) -> None:
        self.resource_editor = ctk.CTkFrame(self.editor_panel)
        self.resource_editor.grid_columnconfigure(4, weight=1)
        self.resource_label = self._label(self.resource_editor, text="未选择资源", font=UI_FONT_BOLD)
        self.resource_label.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))
        self.close_resource_button = self._button(self.resource_editor, text="关闭", width=72, command=self._close_resource_editor)
        self.close_resource_button.grid(row=0, column=4, sticky="e", padx=8, pady=(8, 4))
        self._label(self.resource_editor, text="改归类到").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=6)
        self.resource_project_menu = self._option_menu(
            self.resource_editor,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.resource_project_var,
            width=180,
            command=lambda _name: self._on_resource_control_change(),
        )
        self.resource_project_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=6)
        self.current_session_button = self._button(
            self.resource_editor,
            text="仅改当前会话该资源",
            width=160,
            command=lambda: self._save_resource_project(False),
        )
        self.current_session_button.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=6)
        self.remember_button = self._button(
            self.resource_editor,
            text="以后该文件都归入该项目",
            width=180,
            command=lambda: self._save_resource_project(True),
        )
        self.remember_button.grid(row=1, column=3, sticky="w", padx=(0, 8), pady=6)
        self._label(self.resource_editor, text="新建项目").grid(row=2, column=0, sticky="w", padx=(8, 4), pady=(0, 6))
        self.new_project_entry = self._entry(
            self.resource_editor,
            textvariable=self.new_project_var,
            width=180,
        )
        self.new_project_entry.grid(row=2, column=1, sticky="w", padx=(0, 12), pady=(0, 6))
        self.create_project_button = self._button(
            self.resource_editor,
            text="创建",
            width=72,
            command=self._create_project_from_timeline,
        )
        self.create_project_button.grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(0, 6))
        self.resource_hint_label = self._label(self.resource_editor, text="")
        self.resource_hint_label.grid(row=3, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 8))
        self._resource_editor_widgets = [
            self.resource_project_menu,
            self.current_session_button,
            self.remember_button,
            self.new_project_entry,
            self.create_project_button,
            self.close_resource_button,
        ]
        for widget in self._resource_editor_widgets:
            widget.bind("<ButtonPress-1>", self._on_control_activity, add="+")
            widget.bind("<FocusIn>", self._on_control_activity, add="+")

    def _build_activity_editor(self) -> None:
        self.activity_editor = ctk.CTkFrame(self.editor_panel)
        self.activity_editor.grid_columnconfigure(6, weight=1)
        self.activity_editor_label = self._label(self.activity_editor, text="未选择明细", font=UI_FONT_BOLD)
        self.activity_editor_label.grid(row=0, column=0, columnspan=7, sticky="w", padx=8, pady=(8, 4))
        self._label(self.activity_editor, text="项目").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        self.activity_project_menu = self._option_menu(
            self.activity_editor,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.activity_project_var,
            width=160,
            command=lambda _name: self._mark_editor_dirty(),
        )
        self.activity_project_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)
        self.billable_box = self._checkbox(self.activity_editor, text="计费", variable=self.billable_var, command=self._mark_editor_dirty, width=70)
        self.billable_box.grid(row=1, column=2, sticky="w", padx=(0, 12), pady=4)
        self.save_activity_button = self._button(self.activity_editor, text="保存", width=72, command=self._save_activity)
        self.save_activity_button.grid(row=1, column=3, sticky="w", padx=(0, 8), pady=4)
        self.delete_activity_button = self._button(self.activity_editor, text="删除", width=72, fg_color="#a33", command=self._delete_activity)
        self.delete_activity_button.grid(row=1, column=4, sticky="w", padx=(0, 8), pady=4)
        self.close_activity_button = self._button(self.activity_editor, text="关闭", width=72, command=self._close_activity_editor)
        self.close_activity_button.grid(row=1, column=5, sticky="w", padx=(0, 8), pady=4)
        self._label(self.activity_editor, text="备注").grid(row=2, column=0, sticky="nw", padx=(8, 4), pady=(6, 8))
        self.note_text = ctk.CTkTextbox(self.activity_editor, height=64, font=UI_FONT)
        self.note_text.grid(row=2, column=1, columnspan=6, sticky="ew", padx=(0, 8), pady=(6, 8))
        self.note_text.bind("<KeyRelease>", lambda _event: self._mark_editor_dirty(), add="+")
        self._editor_widgets = [
            self.activity_project_menu,
            self.billable_box,
            self.save_activity_button,
            self.delete_activity_button,
            self.close_activity_button,
            self.note_text,
        ]
        for widget in self._editor_widgets:
            widget.bind("<ButtonPress-1>", self._on_control_activity, add="+")
            widget.bind("<FocusIn>", self._on_control_activity, add="+")

    def refresh(self) -> None:
        self._sync_status()
        date_text = self.date_var.get()
        if not self._valid_date(date_text):
            self.status_label.configure(text="日期格式错误，请使用 YYYY-MM-DD")
            return
        self._refresh_projects()
        sessions = timeline_service.get_project_sessions_by_date(date_text)
        if self.only_uncategorized.get():
            sessions = [session for session in sessions if session["is_uncategorized"]]
        self._sync_sessions(sessions)
        self._refresh_selected_session()

    def is_user_interacting(self) -> bool:
        activity_focus = any(self._widget_has_focus(widget) for widget in getattr(self, "_editor_widgets", []))
        resource_focus = any(self._widget_has_focus(widget) for widget in getattr(self, "_resource_editor_widgets", []))
        return (
            self._control_active
            or self._editor_dirty
            or self._resource_editor_visible()
            or self._activity_editor_visible()
            or activity_focus
            or resource_focus
        )

    def _sync_sessions(self, sessions: list[dict]) -> None:
        previous = self._selected_session_id
        self._sessions_by_id = {session["session_id"]: session for session in sessions}
        self._sync_tree(self.session_tree, [(session["session_id"], self._session_values(session)) for session in sessions])
        if previous in self._sessions_by_id:
            self._select_tree_item(self.session_tree, previous)
        elif sessions:
            self._selected_session_id = sessions[0]["session_id"]
            self._select_tree_item(self.session_tree, self._selected_session_id)
        else:
            self._selected_session_id = None
            self.session_project_var.set(UNCATEGORIZED_PROJECT)
            self.detail_label.configure(text="暂无项目会话")
            self._sync_resources([])
            self._sync_details([])

    def _refresh_selected_session(self) -> None:
        session = self._sessions_by_id.get(self._selected_session_id or "")
        if not session:
            return
        self.detail_label.configure(
            text=f"{self._session_time(session)}｜{session['project_name']}｜{format_duration(session['duration_seconds'])}"
        )
        self.session_project_var.set(self._project_name_by_id.get(int(session["project_id"]), UNCATEGORIZED_PROJECT))
        if self._detail_mode == "resources":
            self._sync_resources(timeline_service.get_session_resource_summary(session["activity_ids"]))
        else:
            self._sync_details(timeline_service.get_session_activity_details(session["activity_ids"]))

    def _sync_resources(self, resources: list[dict]) -> None:
        previous = self._selected_resource_id
        keep_editor_open = self._resource_editor_visible()
        self._resources_by_id = {int(row["resource_id"]): row for row in resources}
        self._sync_tree(self.resource_tree, [(str(row["resource_id"]), self._resource_values(row)) for row in resources])
        if previous in self._resources_by_id:
            self._select_tree_item(self.resource_tree, str(previous))
            if keep_editor_open:
                self._load_resource_editor(previous)
        else:
            self._selected_resource_id = None
            self.resource_tree.selection_remove(self.resource_tree.selection())
            self._show_resource_editor(False)

    def _sync_details(self, details: list[dict]) -> None:
        previous = self._selected_activity_id
        keep_editor_open = self._activity_editor_visible()
        self._details_by_id = {int(row["id"]): row for row in details}
        self._sync_tree(self.detail_tree, [(str(row["id"]), self._detail_values(row)) for row in details])
        if previous in self._details_by_id:
            self._select_tree_item(self.detail_tree, str(previous))
            if keep_editor_open:
                self._load_activity_editor(previous)
        elif not self._editor_dirty:
            self._selected_activity_id = None
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
        restore = lambda position=yview[0], target=tree: target.yview_moveto(position)
        if hasattr(self, "after_idle"):
            self.after_idle(restore)
        else:
            restore()

    def _on_session_select(self, _event=None) -> None:
        selection = self.session_tree.selection()
        if not selection:
            return
        self._selected_session_id = selection[0]
        self._selected_resource_id = None
        self._selected_activity_id = None
        self._editor_dirty = False
        self._refresh_selected_session()

    def _on_resource_select(self, _event=None) -> None:
        selection = self.resource_tree.selection()
        if not selection:
            self._selected_resource_id = None
            self._show_resource_editor(False)
            return
        self._selected_resource_id = int(selection[0])
        self._touch_resource_editor()
        if not self._load_resource_editor(self._selected_resource_id):
            self._show_resource_editor(False)
            return

    def _load_resource_editor(self, resource_id: int) -> bool:
        resource = self._resources_by_id.get(resource_id)
        if not resource:
            return False
        self._show_resource_editor(True)
        role_text = "锚点文件" if resource["resource_role"] == "anchor" else "辅助活动"
        self.resource_label.configure(
            text=f"正在纠错{role_text}：{resource['display_name']}｜当前会话内共 {resource['event_count']} 条活动"
        )
        self.resource_project_var.set(resource.get("official_project_name") or UNCATEGORIZED_PROJECT)
        if resource["can_remember_for_future"]:
            self.remember_button.configure(state="normal", text="以后该文件都归入该项目")
            hint = ""
            if resource.get("is_suggested_project"):
                hint = f"当前时间线显示为建议项目：{resource.get('project_name')}"
            self.resource_hint_label.configure(text=hint)
        else:
            self.remember_button.configure(state="disabled", text="以后该资源都归入该项目")
            self.resource_hint_label.configure(text="辅助活动不能作为项目长期判定依据，只能纠正当前会话。")
        return True

    def _on_activity_select(self, _event=None) -> None:
        selection = self.detail_tree.selection()
        if not selection:
            if not self._editor_dirty:
                self._selected_activity_id = None
                self._show_activity_editor(False)
            return
        activity_id = int(selection[0])
        if self._editor_dirty and self._selected_activity_id != activity_id:
            self._select_tree_item(self.detail_tree, str(self._selected_activity_id))
            self.activity_editor_label.configure(text="当前修改未保存，请先保存后再切换记录")
            return
        self._selected_activity_id = activity_id
        self._load_activity_editor(activity_id)

    def _toggle_detail_mode(self) -> None:
        if self._detail_mode == "resources":
            self._detail_mode = "details"
            self.resource_tree_frame.grid_remove()
            self.detail_tree_frame.grid(row=0, column=0, sticky="nsew")
            self._apply_tree_column_widths(self.detail_tree)
            self.toggle_detail_button.configure(text="返回资源汇总")
            self._show_resource_editor(False)
        else:
            self._detail_mode = "resources"
            self.detail_tree_frame.grid_remove()
            self.resource_tree_frame.grid(row=0, column=0, sticky="nsew")
            self._apply_tree_column_widths(self.resource_tree)
            self.toggle_detail_button.configure(text="查看时间顺序明细")
            self._show_activity_editor(False)
        self._editor_dirty = False
        self._refresh_selected_session()

    def _save_resource_project(self, remember: bool) -> None:
        self._touch_resource_editor()
        session = self._sessions_by_id.get(self._selected_session_id or "")
        resource = self._resources_by_id.get(self._selected_resource_id or 0)
        if not session or not resource:
            return
        project_id = self._project_by_name.get(self.resource_project_var.get())
        if project_id is None:
            self.resource_hint_label.configure(text="请选择有效项目")
            return
        try:
            timeline_service.update_resource_project_for_session(
                session["activity_ids"],
                int(resource["resource_id"]),
                project_id,
                remember_for_future=remember,
            )
        except ValueError as exc:
            self.resource_hint_label.configure(text=str(exc))
            return
        self.refresh()

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
        self.refresh()

    def _format_session_project_preview(self, preview: dict) -> str:
        parts = []
        if preview["file_project_conflicts"]:
            parts.append("以下锚点文件已有不同的逐文件归属：")
            parts.extend(self._preview_lines(preview["file_project_conflicts"]))
        if preview["folder_rule_conflicts"]:
            parts.append("以下锚点文件命中了其他项目的文件夹规则：")
            parts.extend(self._preview_lines(preview["folder_rule_conflicts"]))
        if preview["unassigned_anchor_files"]:
            parts.append("以下锚点文件还没有逐文件归属，也没有命中目标项目的文件夹规则：")
            parts.extend(self._preview_lines(preview["unassigned_anchor_files"]))
        parts.append("")
        parts.append("继续后只会修改当前会话活动归属，不会自动修改这些锚点文件的长期归属。")
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

    def _create_project_from_timeline(self) -> None:
        self._touch_resource_editor()
        name = self.new_project_var.get().strip()
        if not name:
            self.resource_hint_label.configure(text="请输入项目名称")
            return
        self._refresh_projects()
        if name in self._project_by_name:
            self.resource_project_var.set(name)
            self.resource_hint_label.configure(text=f"项目已存在，已选中：{name}")
            return
        try:
            project_service.create_project(name)
        except Exception as exc:
            self._refresh_projects()
            if name in self._project_by_name:
                self.resource_project_var.set(name)
                self.resource_hint_label.configure(text=f"项目已存在，已选中：{name}")
                return
            self.resource_hint_label.configure(text=f"创建失败：{exc}")
            return
        self._refresh_projects()
        self.resource_project_var.set(name)
        self.new_project_var.set("")
        self.resource_hint_label.configure(text=f"已创建项目：{name}")

    def _create_project_for_session(self) -> None:
        name = ctk.CTkInputDialog(text="项目名称", title="新建项目").get_input()
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self._refresh_projects()
        if name not in self._project_by_name:
            try:
                project_service.create_project(name)
            except Exception as exc:
                self._refresh_projects()
                if name not in self._project_by_name:
                    messagebox.showerror("创建失败", str(exc))
                    return
        self._refresh_projects()
        self.session_project_var.set(name)

    def _open_folder_rule_dialog(self) -> None:
        projects = project_service.list_user_projects()
        if not projects:
            messagebox.showerror("无法新增", "请先创建项目")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("文件夹项目规则")
        dialog.geometry("620x300")
        folder_var = ctk.StringVar(value=self._default_session_folder())
        selected_name = ctk.StringVar(value=projects[0]["name"])
        recursive_var = ctk.BooleanVar(value=True)

        ctk.CTkLabel(dialog, text="文件夹").pack(anchor="w", padx=14, pady=(14, 4))
        folder_row = ctk.CTkFrame(dialog)
        folder_row.pack(fill="x", padx=14, pady=(0, 8))
        folder_entry = ctk.CTkEntry(folder_row, textvariable=folder_var, width=430)
        folder_entry.pack(side="left", fill="x", expand=True)

        def browse_folder() -> None:
            folder = filedialog.askdirectory(title="选择要绑定项目的文件夹")
            if folder:
                folder_var.set(folder)

        ctk.CTkButton(folder_row, text="浏览", width=72, command=browse_folder).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(dialog, text="归属项目").pack(anchor="w", padx=14, pady=(4, 4))
        ctk.CTkOptionMenu(dialog, values=[project["name"] for project in projects], variable=selected_name, width=300).pack(anchor="w", padx=14, pady=(0, 8))
        ctk.CTkCheckBox(dialog, text="包含子文件夹", variable=recursive_var).pack(anchor="w", padx=14, pady=4)

        actions = ctk.CTkFrame(dialog)
        actions.pack(fill="x", padx=14, pady=14)

        def save_rule() -> None:
            project = project_service.get_project_by_name(selected_name.get())
            if not project:
                messagebox.showerror("保存失败", "请选择有效项目")
                return
            folder = folder_var.get().strip()
            if not folder:
                messagebox.showerror("保存失败", "请选择文件夹")
                return
            dialog.destroy()
            self._save_folder_rule(folder, int(project["id"]), bool(recursive_var.get()))

        ctk.CTkButton(actions, text="取消", width=72, command=dialog.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="保存", width=72, command=save_rule).pack(side="right")

    def _default_session_folder(self) -> str:
        session = self._sessions_by_id.get(self._selected_session_id or "")
        if not session:
            return ""
        folders = timeline_service.get_session_anchor_folders(session["activity_ids"])
        return folders[0] if folders else ""

    def _save_folder_rule(self, folder: str, project_id: int, recursive: bool) -> None:
        preview = folder_rule_service.preview_folder_rule_conflicts(folder, project_id)
        if any(int(value) for value in preview.values()):
            message = (
                f"下级已有不同项目的文件夹规则：{preview['child_folder_rule_conflicts']}\n"
                f"具体文件已有不同项目：{preview['file_default_project_conflicts']}\n"
                f"历史 activity 属于其他项目：{preview['other_project_activity_count']}\n"
                f"手动指定且 safe 回填不会覆盖：{preview['manual_activity_count']}\n\n"
                "将保留下级独立设置，且默认不自动回填历史。是否继续保存？"
            )
            if not messagebox.askyesno("规则冲突预览", message):
                return
        rule_id = folder_rule_service.create_or_update_folder_rule(folder, project_id, recursive=recursive)
        if messagebox.askyesno("已保存", "文件夹规则已保存。是否执行 safe 历史回填？"):
            result = folder_rule_service.backfill_folder_rule(rule_id, mode="safe")
            messagebox.showinfo("回填完成", f"已更新 {result['updated_activity_count']} 条记录")
        self.refresh()

    def _load_activity_editor(self, activity_id: int) -> None:
        row = self._details_by_id.get(activity_id)
        if not row:
            self._show_activity_editor(False)
            return
        self._show_activity_editor(True)
        self._loading_editor = True
        self.activity_project_var.set(row.get("official_project_name") or UNCATEGORIZED_PROJECT)
        self.billable_var.set(bool(row.get("is_billable")))
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", row.get("note") or "")
        self._loading_editor = False
        self._editor_dirty = False
        self.activity_editor_label.configure(text=f"正在编辑：{self._detail_values(row)[0]}｜{row.get('app_name') or ''}")

    def _save_activity(self) -> None:
        activity_id = self._selected_activity_id
        row = self._details_by_id.get(activity_id or 0)
        if activity_id is None or not row:
            return
        project_id = self._project_by_name.get(self.activity_project_var.get())
        if project_id is None:
            self.activity_editor_label.configure(text="请选择有效项目")
            return
        if int(row.get("project_id") or 0) != project_id:
            activity_service.update_activity_project(activity_id, project_id, manual=True)
        billable = bool(self.billable_var.get())
        if bool(row.get("is_billable")) != billable:
            activity_service.set_activity_billable(activity_id, billable)
        note = self.note_text.get("1.0", "end-1c")
        if (row.get("note") or "") != note:
            activity_service.update_activity_note(activity_id, note)
        self._editor_dirty = False
        self.refresh()

    def _delete_activity(self) -> None:
        if self._selected_activity_id is None:
            return
        activity_service.soft_delete_activity(self._selected_activity_id)
        self._selected_activity_id = None
        self._editor_dirty = False
        self.refresh()

    def _refresh_projects(self) -> None:
        projects = project_service.list_selectable_projects()
        self._project_by_name = {p["name"]: int(p["id"]) for p in projects}
        self._project_name_by_id = {int(p["id"]): p["name"] for p in projects}
        names = list(self._project_by_name)
        if UNCATEGORIZED_PROJECT not in names:
            names.insert(0, UNCATEGORIZED_PROJECT)
        for menu_name in ("session_project_menu", "resource_project_menu", "activity_project_menu"):
            menu = getattr(self, menu_name, None)
            if menu is not None:
                menu.configure(values=names or [UNCATEGORIZED_PROJECT])

    def _sync_status(self) -> None:
        status = get_setting("collector_status", "stopped")
        paused = get_bool_setting("user_paused", False)
        label = "记录中" if status == "running" else "采集器未运行"
        if paused or status == "paused":
            label = "已暂停"
        if status == "error":
            label = "状态异常"
        self.status_label.configure(text=label)
        self.pause_button.configure(text="继续" if paused else "暂停")
        self.current_activity_label.configure(text=self._current_activity_text())

    def _current_activity_text(self) -> str:
        raw = get_setting("current_activity_snapshot", "") or ""
        if not raw:
            return "当前活动：无"
        try:
            snapshot = json.loads(raw)
        except json.JSONDecodeError:
            return "当前活动：无"
        name = snapshot.get("resource_display_name") or snapshot.get("app_name") or snapshot.get("process_name") or "未知"
        project = snapshot.get("inferred_project_name") or UNCATEGORIZED_PROJECT
        elapsed = format_duration(snapshot.get("elapsed_seconds") or 0)
        state = "已进入历史" if snapshot.get("is_persisted") else "暂不入历史"
        if snapshot.get("status") == "idle":
            name = "空闲中"
        return f"当前活动：{name}｜{project}｜{elapsed}｜{state}"

    def _session_values(self, session: dict) -> tuple[str, ...]:
        return (
            self._session_time(session),
            str(session["project_name"] if session["status"] == "normal" else session["status_summary"]),
            format_duration(session["duration_seconds"]),
            str(session["event_count"]),
            str(session["status_summary"]),
        )

    def _resource_values(self, row: dict) -> tuple[str, ...]:
        return (
            str(row["display_name"]),
            str(row["resource_type"]),
            format_duration(row["total_duration_seconds"]),
            str(row["event_count"]),
            str(row.get("project_name") or UNCATEGORIZED_PROJECT),
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
            str(row.get("resource_display_name") or ""),
            format_duration(row.get("duration_seconds") or 0),
            str(row.get("project_name") or UNCATEGORIZED_PROJECT),
            "是" if row.get("is_billable") else "否",
            note,
        )

    def _session_time(self, session: dict) -> str:
        start = session.get("start_time") or ""
        end = session.get("end_time") or ""
        return f"{start[11:16] if len(start) >= 16 else start}-{end[11:16] if len(end) >= 16 else ''}"

    def _label(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        return ctk.CTkLabel(master, **kwargs)

    def _button(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        return ctk.CTkButton(master, **kwargs)

    def _checkbox(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        return ctk.CTkCheckBox(master, **kwargs)

    def _entry(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        return ctk.CTkEntry(master, **kwargs)

    def _option_menu(self, master, **kwargs):
        kwargs.setdefault("font", UI_FONT)
        kwargs.setdefault("dropdown_font", UI_FONT)
        return ctk.CTkOptionMenu(master, **kwargs)

    def _make_tree_frame(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
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
            if column in {"summary", "resource", "window", "note"}:
                minwidth = max(minwidth, 120)
            tree.heading(column, text=headings[column])
            tree.column(column, width=width, minwidth=minwidth, anchor="w", stretch=False)
        vertical_scrollbar = ttk.Scrollbar(master, orient="vertical", command=tree.yview)
        horizontal_scrollbar = ttk.Scrollbar(master, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical_scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        tree.bind("<ButtonRelease-1>", lambda _event, target=tree: self._save_tree_column_widths(target), add="+")
        self._apply_tree_column_widths(tree)
        return tree

    def _configure_tree_style(self) -> None:
        style = ttk.Style(self)
        style.configure("WorkTrace.Treeview", font=TREE_FONT, rowheight=TREE_ROWHEIGHT)
        style.configure("WorkTrace.Treeview.Heading", font=TREE_HEADING_FONT)

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

    def _show_resource_editor(self, show: bool) -> None:
        if show:
            self._show_editor_panel(True)
            self.activity_editor.grid_remove()
            self.resource_editor.grid(row=0, column=0, sticky="ew")
        else:
            self.resource_editor.grid_remove()
            if not self._activity_editor_visible():
                self._show_editor_panel(False)

    def _show_activity_editor(self, show: bool) -> None:
        if show:
            self._show_editor_panel(True)
            self.resource_editor.grid_remove()
            self.activity_editor.grid(row=0, column=0, sticky="ew")
        else:
            self.activity_editor.grid_remove()
            if not self._resource_editor_visible():
                self._show_editor_panel(False)

    def _show_editor_panel(self, show: bool) -> None:
        if show:
            self.editor_scroll_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        else:
            self.editor_scroll_frame.grid_remove()

    def _select_tree_item(self, tree: ttk.Treeview, iid: str | None) -> None:
        if iid is None or not tree.exists(iid):
            return
        tree.selection_set(iid)
        tree.focus(iid)

    def _valid_date(self, value: str) -> bool:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    def _mark_editor_dirty(self) -> None:
        if not self._loading_editor:
            self._editor_dirty = True
            self.activity_editor_label.configure(text="当前修改未保存")

    def _on_control_activity(self, _event=None) -> None:
        self._control_active = True
        self._touch_resource_editor()
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

    def _on_resource_control_change(self) -> None:
        self._touch_resource_editor()
        self._on_control_activity()

    def _touch_resource_editor(self) -> None:
        if self._selected_resource_id is not None or self._resource_editor_visible():
            self._resource_selected_at = time.monotonic()

    def _resource_editor_recently_selected(self) -> bool:
        return self._selected_resource_id is not None and time.monotonic() - self._resource_selected_at <= 5.0

    def _resource_editor_visible(self) -> bool:
        try:
            return bool(self.resource_editor.winfo_ismapped())
        except Exception:
            return False

    def _activity_editor_visible(self) -> bool:
        try:
            return bool(self.activity_editor.winfo_ismapped())
        except Exception:
            return False

    def _close_resource_editor(self) -> None:
        self._selected_resource_id = None
        if hasattr(self, "resource_tree"):
            self.resource_tree.selection_remove(self.resource_tree.selection())
        self._show_resource_editor(False)

    def _close_activity_editor(self) -> None:
        self._selected_activity_id = None
        self._editor_dirty = False
        if hasattr(self, "detail_tree"):
            self.detail_tree.selection_remove(self.detail_tree.selection())
        self._show_activity_editor(False)

    def toggle_pause(self) -> None:
        set_setting("user_paused", "false" if get_bool_setting("user_paused", False) else "true")
        self.refresh()
