from __future__ import annotations

import time
from datetime import date
from tkinter import ttk
from typing import Any

import customtkinter as ctk

from ..constants import UNCATEGORIZED_PROJECT
from ..exports.markdown_exporter import format_duration
from ..services import activity_service, project_service, timeline_service
from ..services.settings_service import get_bool_setting, get_setting, set_setting


class TimelineView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.date_var = ctk.StringVar(value=date.today().isoformat())
        self.only_unconfirmed = ctk.BooleanVar(value=False)
        self.only_uncategorized = ctk.BooleanVar(value=False)
        self.resource_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.new_project_var = ctk.StringVar(value="")
        self.activity_project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.billable_var = ctk.BooleanVar(value=False)
        self.confirmed_var = ctk.BooleanVar(value=False)

        self._project_by_name: dict[str, int] = {}
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

        self._build()

    def _build(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=12)
        self.status_label = ctk.CTkLabel(top, text="采集器未运行")
        self.status_label.pack(side="left", padx=6)
        self.pause_button = ctk.CTkButton(top, text="暂停", width=90, command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=6)
        ctk.CTkLabel(top, text="日期").pack(side="left", padx=(16, 4))
        self.date_entry = ctk.CTkEntry(top, textvariable=self.date_var, width=120)
        self.date_entry.pack(side="left")
        ctk.CTkButton(top, text="刷新", width=70, command=self.refresh).pack(side="left", padx=6)
        ctk.CTkCheckBox(top, text="仅未确认", variable=self.only_unconfirmed, command=self.refresh).pack(side="left", padx=6)
        ctk.CTkCheckBox(top, text="仅未归类", variable=self.only_uncategorized, command=self.refresh).pack(side="left", padx=6)

        self._build_session_table()
        self._build_detail_area()
        self._build_resource_editor()
        self._build_activity_editor()
        self._show_resource_editor(False)
        self._show_activity_editor(False)

    def _build_session_table(self) -> None:
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self._configure_tree_style()
        columns = ("time", "project", "duration", "count", "summary")
        self.session_tree = ttk.Treeview(frame, columns=columns, show="headings", style="WorkTrace.Treeview", height=8)
        headings = {"time": "时间", "project": "项目/状态", "duration": "时长", "count": "活动数", "summary": "摘要"}
        widths = {"time": 128, "project": 180, "duration": 100, "count": 72, "summary": 420}
        for column in columns:
            self.session_tree.heading(column, text=headings[column])
            self.session_tree.column(column, width=widths[column], minwidth=56, anchor="w", stretch=column == "summary")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.session_tree.yview)
        self.session_tree.configure(yscrollcommand=scrollbar.set)
        self.session_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.session_tree.bind("<<TreeviewSelect>>", self._on_session_select)

    def _build_detail_area(self) -> None:
        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=12, pady=(0, 6))
        self.detail_label = ctk.CTkLabel(header, text="请选择项目会话")
        self.detail_label.pack(side="left", padx=6, pady=6)
        self.toggle_detail_button = ctk.CTkButton(
            header,
            text="查看时间顺序明细",
            width=150,
            command=self._toggle_detail_mode,
        )
        self.toggle_detail_button.pack(side="right", padx=6, pady=6)

        self.detail_container = ctk.CTkFrame(self)
        self.detail_container.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.detail_container.grid_rowconfigure(0, weight=1)
        self.detail_container.grid_columnconfigure(0, weight=1)

        self.resource_tree = self._make_tree(
            self.detail_container,
            ("resource", "type", "duration", "count", "project", "unconfirmed"),
            {
                "resource": "资源",
                "type": "类型",
                "duration": "时长",
                "count": "活动数",
                "project": "当前项目",
                "unconfirmed": "未确认",
            },
            {"resource": 320, "type": 92, "duration": 100, "count": 72, "project": 140, "unconfirmed": 72},
        )
        self.resource_tree.bind("<<TreeviewSelect>>", self._on_resource_select)

        self.detail_tree = self._make_tree(
            self.detail_container,
            ("time", "app", "window", "resource", "duration", "project", "billable", "confirmed", "note"),
            {
                "time": "时间",
                "app": "应用",
                "window": "窗口",
                "resource": "资源",
                "duration": "时长",
                "project": "项目",
                "billable": "计费",
                "confirmed": "确认",
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
                "confirmed": 64,
                "note": 180,
            },
        )
        self.detail_tree.bind("<<TreeviewSelect>>", self._on_activity_select)
        self.detail_tree.grid_remove()

    def _build_resource_editor(self) -> None:
        self.resource_editor = ctk.CTkFrame(self)
        self.resource_label = ctk.CTkLabel(self.resource_editor, text="未选择资源")
        self.resource_label.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))
        ctk.CTkLabel(self.resource_editor, text="改归类到").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=6)
        self.resource_project_menu = ctk.CTkOptionMenu(
            self.resource_editor,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.resource_project_var,
            width=180,
            command=lambda _name: self._on_resource_control_change(),
        )
        self.resource_project_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=6)
        self.current_session_button = ctk.CTkButton(
            self.resource_editor,
            text="仅改当前会话该资源",
            width=160,
            command=lambda: self._save_resource_project(False),
        )
        self.current_session_button.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=6)
        self.remember_button = ctk.CTkButton(
            self.resource_editor,
            text="以后该文件都归入该项目",
            width=180,
            command=lambda: self._save_resource_project(True),
        )
        self.remember_button.grid(row=1, column=3, sticky="w", padx=(0, 8), pady=6)
        ctk.CTkLabel(self.resource_editor, text="新建项目").grid(row=2, column=0, sticky="w", padx=(8, 4), pady=(0, 6))
        self.new_project_entry = ctk.CTkEntry(
            self.resource_editor,
            textvariable=self.new_project_var,
            width=180,
        )
        self.new_project_entry.grid(row=2, column=1, sticky="w", padx=(0, 12), pady=(0, 6))
        self.create_project_button = ctk.CTkButton(
            self.resource_editor,
            text="创建",
            width=72,
            command=self._create_project_from_timeline,
        )
        self.create_project_button.grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(0, 6))
        self.resource_hint_label = ctk.CTkLabel(self.resource_editor, text="")
        self.resource_hint_label.grid(row=3, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))
        self._resource_editor_widgets = [
            self.resource_project_menu,
            self.current_session_button,
            self.remember_button,
            self.new_project_entry,
            self.create_project_button,
        ]
        for widget in self._resource_editor_widgets:
            widget.bind("<ButtonPress-1>", self._on_control_activity, add="+")
            widget.bind("<FocusIn>", self._on_control_activity, add="+")

    def _build_activity_editor(self) -> None:
        self.activity_editor = ctk.CTkFrame(self)
        self.activity_editor.grid_columnconfigure(7, weight=1)
        self.activity_editor_label = ctk.CTkLabel(self.activity_editor, text="未选择明细")
        self.activity_editor_label.grid(row=0, column=0, columnspan=8, sticky="w", padx=8, pady=(8, 4))
        ctk.CTkLabel(self.activity_editor, text="项目").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        self.activity_project_menu = ctk.CTkOptionMenu(
            self.activity_editor,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.activity_project_var,
            width=160,
            command=lambda _name: self._mark_editor_dirty(),
        )
        self.activity_project_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)
        self.billable_box = ctk.CTkCheckBox(self.activity_editor, text="计费", variable=self.billable_var, command=self._mark_editor_dirty, width=70)
        self.billable_box.grid(row=1, column=2, sticky="w", padx=(0, 12), pady=4)
        self.confirmed_box = ctk.CTkCheckBox(self.activity_editor, text="确认", variable=self.confirmed_var, command=self._mark_editor_dirty, width=70)
        self.confirmed_box.grid(row=1, column=3, sticky="w", padx=(0, 12), pady=4)
        ctk.CTkButton(self.activity_editor, text="保存", width=72, command=self._save_activity).grid(row=1, column=4, sticky="w", padx=(0, 8), pady=4)
        ctk.CTkButton(self.activity_editor, text="删除", width=72, fg_color="#a33", command=self._delete_activity).grid(row=1, column=5, sticky="w", padx=(0, 8), pady=4)
        ctk.CTkLabel(self.activity_editor, text="备注").grid(row=2, column=0, sticky="nw", padx=(8, 4), pady=(6, 8))
        self.note_text = ctk.CTkTextbox(self.activity_editor, height=64)
        self.note_text.grid(row=2, column=1, columnspan=7, sticky="ew", padx=(0, 8), pady=(6, 8))
        self.note_text.bind("<KeyRelease>", lambda _event: self._mark_editor_dirty(), add="+")
        self._editor_widgets = [self.activity_project_menu, self.billable_box, self.confirmed_box, self.note_text]
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
        if self.only_unconfirmed.get():
            sessions = [session for session in sessions if session["has_unconfirmed"]]
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
            or activity_focus
            or resource_focus
            or (self._resource_editor_visible() and self._resource_editor_recently_selected())
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
        if self._detail_mode == "resources":
            self._sync_resources(timeline_service.get_session_resource_summary(session["activity_ids"]))
        else:
            self._sync_details(timeline_service.get_session_activity_details(session["activity_ids"]))

    def _sync_resources(self, resources: list[dict]) -> None:
        previous = self._selected_resource_id
        keep_editor_open = self._resource_editor_visible() or self._resource_editor_recently_selected()
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
        self._details_by_id = {int(row["id"]): row for row in details}
        self._sync_tree(self.detail_tree, [(str(row["id"]), self._detail_values(row)) for row in details])
        if previous in self._details_by_id:
            self._select_tree_item(self.detail_tree, str(previous))
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
        self.after_idle(lambda position=yview[0], target=tree: target.yview_moveto(position))

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
        self.resource_project_var.set(resource.get("project_name") or UNCATEGORIZED_PROJECT)
        if resource["can_remember_for_future"]:
            self.remember_button.configure(state="normal", text="以后该文件都归入该项目")
            self.resource_hint_label.configure(text="")
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
            self.resource_tree.grid_remove()
            self.detail_tree.grid(row=0, column=0, sticky="nsew")
            self.toggle_detail_button.configure(text="返回资源汇总")
            self._show_resource_editor(False)
        else:
            self._detail_mode = "resources"
            self.detail_tree.grid_remove()
            self.resource_tree.grid(row=0, column=0, sticky="nsew")
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

    def _load_activity_editor(self, activity_id: int) -> None:
        row = self._details_by_id.get(activity_id)
        if not row:
            self._show_activity_editor(False)
            return
        self._show_activity_editor(True)
        self._loading_editor = True
        self.activity_project_var.set(row.get("project_name") or UNCATEGORIZED_PROJECT)
        self.billable_var.set(bool(row.get("is_billable")))
        self.confirmed_var.set(bool(row.get("is_confirmed")))
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
        activity_service.set_activity_confirmed(activity_id, bool(self.confirmed_var.get()))
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
        projects = project_service.list_active_projects()
        self._project_by_name = {p["name"]: int(p["id"]) for p in projects}
        names = list(self._project_by_name)
        if UNCATEGORIZED_PROJECT not in names:
            names.insert(0, UNCATEGORIZED_PROJECT)
        self.resource_project_menu.configure(values=names or [UNCATEGORIZED_PROJECT])
        self.activity_project_menu.configure(values=names or [UNCATEGORIZED_PROJECT])

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
            str(row["unconfirmed_count"]),
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
            "是" if row.get("is_confirmed") else "否",
            note,
        )

    def _session_time(self, session: dict) -> str:
        start = session.get("start_time") or ""
        end = session.get("end_time") or ""
        return f"{start[11:16] if len(start) >= 16 else start}-{end[11:16] if len(end) >= 16 else ''}"

    def _make_tree(self, master, columns, headings, widths) -> ttk.Treeview:
        tree = ttk.Treeview(master, columns=columns, show="headings", style="WorkTrace.Treeview")
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=48, anchor="w", stretch=column in {"window", "resource", "note"})
        scrollbar = ttk.Scrollbar(master, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return tree

    def _configure_tree_style(self) -> None:
        style = ttk.Style(self)
        style.configure("WorkTrace.Treeview", rowheight=28)
        style.configure("WorkTrace.Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

    def _show_resource_editor(self, show: bool) -> None:
        if show:
            self.activity_editor.pack_forget()
            self.resource_editor.pack(fill="x", padx=12, pady=(0, 12))
        else:
            self.resource_editor.pack_forget()

    def _show_activity_editor(self, show: bool) -> None:
        if show:
            self.resource_editor.pack_forget()
            self.activity_editor.pack(fill="x", padx=12, pady=(0, 12))
        else:
            self.activity_editor.pack_forget()

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

    def toggle_pause(self) -> None:
        set_setting("user_paused", "false" if get_bool_setting("user_paused", False) else "true")
        self.refresh()
