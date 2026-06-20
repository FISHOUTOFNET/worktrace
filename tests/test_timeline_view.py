import json
import time

from worktrace.services import activity_service, project_service, settings_service, timeline_service
from worktrace.services.live_time_service import snapshot_signature
from worktrace.ui.timeline_view import TimelineView


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeWidget:
    def __init__(self, mapped=False, master=None):
        self.mapped = mapped
        self.master = master
        self.config = {}
        self.bindings = []
        self.grid_calls = []
        self.grid_removed = False
        self.destroyed = False

    def bind(self, *args, **kwargs):
        self.bindings.append((args, kwargs))

    def configure(self, **kwargs):
        self.config.update(kwargs)

    def grid(self, *args, **kwargs):
        self.mapped = True
        self.grid_removed = False
        self.grid_calls.append((args, kwargs))

    def grid_remove(self):
        self.mapped = False
        self.grid_removed = True

    def grid_columnconfigure(self, *_args, **_kwargs):
        pass

    def grid_rowconfigure(self, *_args, **_kwargs):
        pass

    def pack(self, *args, **kwargs):
        self.mapped = True

    def winfo_ismapped(self):
        return self.mapped

    def destroy(self):
        self.destroyed = True


class FakeTree:
    def __init__(self, columns=()):
        self.columns = tuple(columns)
        self.widths = {column: 100 for column in self.columns}
        self.bindings = []
        self.children = []
        self.items = {}
        self.moves = []
        self.deleted = []
        self.item_calls = []
        self.yview_position = 0.0

    def __getitem__(self, key):
        if key == "columns":
            return self.columns
        raise KeyError(key)

    def column(self, column, option=None, **kwargs):
        if "width" in kwargs:
            self.widths[column] = kwargs["width"]
        if option == "width":
            return self.widths[column]
        return {"width": self.widths[column]}

    def bind(self, *args, **kwargs):
        self.bindings.append((args, kwargs))

    def get_children(self):
        return tuple(self.children)

    def yview(self):
        return (self.yview_position, 1.0)

    def yview_moveto(self, position):
        self.yview_position = position

    def exists(self, iid):
        return iid in self.children

    def insert(self, _parent, index, iid, values):
        self.children.insert(index, iid)
        self.items[iid] = tuple(values)

    def item(self, iid, **kwargs):
        if "values" in kwargs:
            self.items[iid] = tuple(kwargs["values"])
            self.item_calls.append((iid, tuple(kwargs["values"])))
        return {"values": self.items.get(iid)}

    def move(self, iid, _parent, index):
        self.children.remove(iid)
        self.children.insert(index, iid)
        self.moves.append((iid, index))

    def delete(self, iid):
        if iid in self.children:
            self.children.remove(iid)
        self.items.pop(iid, None)
        self.deleted.append(iid)

    def selection(self):
        return []

    def selection_remove(self, _selection):
        pass


def _view_stub(project_name="Client"):
    view = object.__new__(TimelineView)
    view.new_project_var = FakeVar(project_name)
    view.resource_project_var = FakeVar("")
    view.resource_hint_label = FakeWidget()
    view.session_project_menu = FakeWidget()
    view.resource_project_menu = FakeWidget()
    view.activity_project_menu = FakeWidget()
    view.resource_editor = FakeWidget(mapped=True)
    view._selected_resource_id = 1
    view._resource_selected_at = 0.0
    view._project_by_name = {}
    return view


def _editor_view_stub():
    view = object.__new__(TimelineView)
    view.editor_scroll_frame = FakeWidget(mapped=True)
    view.editor_panel = view.editor_scroll_frame
    view.resource_editor = FakeWidget(mapped=False, master=view.editor_panel)
    view.activity_editor = FakeWidget(mapped=False, master=view.editor_panel)
    view.resource_tree_frame = FakeWidget(mapped=True)
    view.detail_tree_frame = FakeWidget(mapped=False)
    return view


def _live_view_stub(detail_mode="resources"):
    view = object.__new__(TimelineView)
    view.current_activity_label = FakeWidget()
    view.date_var = FakeVar("2026-06-18")
    view.only_uncategorized = FakeVar(False)
    view.session_project_var = FakeVar("")
    view.detail_label = FakeWidget()
    view.detail_hint_label = FakeWidget()
    view.session_count_label = FakeWidget()
    view.session_tree = FakeTree()
    view.resource_tree = FakeTree()
    view.detail_tree = FakeTree()
    view._tree_values = {}
    view._sessions_by_id = {}
    view._resources_by_id = {}
    view._details_by_id = {}
    view._session_live_bases = {}
    view._resource_live_bases = {}
    view._detail_live_bases = {}
    view._current_snapshot = None
    view._current_signature = None
    view._selected_session_id = "1-1"
    view._selected_resource_id = None
    view._selected_activity_id = None
    view._detail_mode = detail_mode
    view._project_name_by_id = {1: "Client"}
    view.is_user_interacting = lambda: False
    return view


def _seed_tree(view, tree, items):
    if not hasattr(view, "_tree_values"):
        view._tree_values = {}
    tree.children = [iid for iid, _values in items]
    tree.items = {iid: tuple(values) for iid, values in items}
    for iid, values in items:
        view._tree_values[f"{id(tree)}:{iid}"] = tuple(values)


def _live_snapshot(seconds=35):
    return {
        "resource_display_name": "Spec",
        "app_name": "Word",
        "process_name": "word.exe",
        "inferred_project_name": "Client",
        "status": "normal",
        "start_time": "",
        "elapsed_seconds": seconds,
        "persisted_activity_id": 1,
        "is_persisted": True,
    }


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("live tick must not call timeline service queries")


def test_visible_resource_editor_blocks_auto_refresh_even_after_recent_selection_window():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view._resource_editor_widgets = []
    view.resource_editor = FakeWidget(mapped=True)
    view.activity_editor = FakeWidget(mapped=False)
    view._selected_resource_id = 42
    view._resource_selected_at = time.monotonic() - 60
    view.focus_get = lambda: None

    assert view.is_user_interacting()


def test_visible_activity_editor_blocks_auto_refresh():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view._resource_editor_widgets = []
    view.resource_editor = FakeWidget(mapped=False)
    view.activity_editor = FakeWidget(mapped=True)
    view.focus_get = lambda: None

    assert view.is_user_interacting()


def test_no_visible_editor_or_focus_is_not_user_interacting():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view._resource_editor_widgets = []
    view.resource_editor = FakeWidget(mapped=False)
    view.activity_editor = FakeWidget(mapped=False)
    view.focus_get = lambda: None

    assert not view.is_user_interacting()


def test_resource_editor_widgets_are_part_of_interaction_guard():
    view = object.__new__(TimelineView)
    resource_control = FakeWidget()
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view._resource_editor_widgets = [resource_control]
    view.resource_editor = FakeWidget(mapped=True)
    view.activity_editor = FakeWidget(mapped=False)
    view._selected_resource_id = 42
    view._resource_selected_at = time.monotonic()
    view.focus_get = lambda: resource_control

    assert view.is_user_interacting()


def test_main_layout_no_longer_creates_global_editor_panel(monkeypatch):
    view = object.__new__(TimelineView)
    view.grid_rowconfigure = lambda *_args, **_kwargs: None
    view.grid_columnconfigure = lambda *_args, **_kwargs: None
    view._build_session_table = lambda: None
    view._build_detail_area = lambda: None
    view._build_resource_editor = lambda: None
    view._build_activity_editor = lambda: None
    view._show_resource_editor = lambda _show: None
    view._show_activity_editor = lambda _show: None
    view.date_var = FakeVar("2026-06-18")
    view.only_uncategorized = FakeVar(False)

    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkFrame", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkLabel", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkButton", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkEntry", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkCheckBox", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkSegmentedButton", lambda master, **_kwargs: FakeWidget(master=master))

    TimelineView._build(view)

    assert not hasattr(view, "editor_scroll_frame")


def test_resource_and_activity_editors_are_children_of_editor_panel(monkeypatch):
    view = object.__new__(TimelineView)
    view.editor_panel = FakeWidget()
    view.resource_project_var = FakeVar()
    view.new_project_var = FakeVar()
    view.activity_project_var = FakeVar()

    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkFrame", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkLabel", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkOptionMenu", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkButton", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkEntry", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkCheckBox", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkTextbox", lambda master, **_kwargs: FakeWidget(master=master))

    TimelineView._build_resource_editor(view)
    TimelineView._build_activity_editor(view)

    assert view.resource_editor.master is view.editor_panel
    assert view.activity_editor.master is view.editor_panel
    assert view.close_resource_button in view._resource_editor_widgets
    assert view.close_activity_button in view._editor_widgets


def test_editor_switching_uses_editor_panel_without_destroying_widgets():
    view = _editor_view_stub()

    TimelineView._show_resource_editor(view, True)

    assert view.editor_scroll_frame.mapped
    assert view.resource_editor.mapped
    assert view.activity_editor.grid_removed
    assert view.resource_editor.master is view.editor_panel

    TimelineView._show_activity_editor(view, True)

    assert view.editor_scroll_frame.mapped
    assert view.activity_editor.mapped
    assert view.resource_editor.grid_removed
    assert not view.resource_editor.destroyed
    assert not view.activity_editor.destroyed

    TimelineView._show_activity_editor(view, False)

    assert not view.editor_scroll_frame.mapped
    assert not view.activity_editor.destroyed


def test_toggle_detail_mode_switches_tree_frames():
    view = _editor_view_stub()
    view._detail_mode = "resources"
    view.resource_tree = FakeTree(columns=("resource",))
    view.detail_tree = FakeTree(columns=("time",))
    view.toggle_detail_button = FakeWidget()
    view._tree_keys = {id(view.resource_tree): "resources", id(view.detail_tree): "details"}
    view._tree_column_widths = {}
    view._editor_dirty = False
    view._show_resource_editor = lambda _show: None
    view._show_activity_editor = lambda _show: None
    view._refresh_selected_session = lambda: None

    TimelineView._toggle_detail_mode(view)

    assert view._detail_mode == "details"
    assert view.resource_tree_frame.grid_removed
    assert view.detail_tree_frame.mapped

    TimelineView._toggle_detail_mode(view)

    assert view._detail_mode == "resources"
    assert view.detail_tree_frame.grid_removed
    assert view.resource_tree_frame.mapped


def test_resource_rule_button_focus_marks_user_interacting():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view.resource_rule_button = FakeWidget()
    view._resource_editor_widgets = [view.resource_rule_button]
    view.resource_editor = FakeWidget(mapped=True)
    view.activity_editor = FakeWidget(mapped=False)
    view._selected_resource_id = None
    view._resource_selected_at = 0.0
    view.focus_get = lambda: view.resource_rule_button

    assert view.is_user_interacting()


def test_tree_column_widths_are_saved_and_restored():
    view = object.__new__(TimelineView)
    tree = FakeTree(columns=("resource", "type"))
    tree.widths["resource"] = 240
    tree.widths["type"] = 90
    view._tree_keys = {id(tree): "resources"}
    view._tree_column_widths = {}

    TimelineView._save_tree_column_widths(view, tree)
    tree.widths["resource"] = 120
    tree.widths["type"] = 60
    TimelineView._apply_tree_column_widths(view, tree)

    assert tree.widths["resource"] == 240
    assert tree.widths["type"] == 90


def test_sync_tree_keeps_saved_column_widths():
    view = object.__new__(TimelineView)
    tree = FakeTree(columns=("resource", "type"))
    view._tree_values = {}
    view._tree_keys = {id(tree): "resources"}
    view._tree_column_widths = {"resources": {"resource": 280, "type": 80}}
    view.after_idle = lambda callback: callback()

    TimelineView._sync_tree(view, tree, [("1", ("Spec.docx", "file"))])

    assert tree.widths["resource"] == 280
    assert tree.widths["type"] == 80


def test_sync_tree_values_only_updates_values_without_layout_changes():
    view = object.__new__(TimelineView)
    tree = FakeTree()
    _seed_tree(view, tree, [("1", ("Spec.docx", "00:00:30"))])

    changed = TimelineView._sync_tree_values_only(view, tree, [("1", ("Spec.docx", "00:00:35"))])

    assert changed is True
    assert tree.item_calls == [("1", ("Spec.docx", "00:00:35"))]
    assert tree.moves == []
    assert tree.deleted == []
    assert tree.children == ["1"]


def test_sync_tree_values_only_rejects_structure_changes():
    view = object.__new__(TimelineView)
    tree = FakeTree()
    _seed_tree(view, tree, [("1", ("Spec.docx",))])

    assert TimelineView._sync_tree_values_only(view, tree, [("2", ("Spec.docx",))]) is False
    assert TimelineView._sync_tree_values_only(view, tree, [("1", ("Spec.docx",)), ("2", ("Notes.md",))]) is False
    assert tree.item_calls == []
    assert tree.children == ["1"]


def test_detail_toggle_uses_short_view_labels():
    view = object.__new__(TimelineView)
    view._detail_mode = "resources"
    view.resource_tree_frame = FakeWidget(mapped=True)
    view.detail_tree_frame = FakeWidget(mapped=False)
    view.resource_tree = FakeTree()
    view.detail_tree = FakeTree()
    view.toggle_detail_button = FakeWidget()
    view._apply_tree_column_widths = lambda _tree: None
    view._show_resource_editor = lambda _show: None
    view._show_activity_editor = lambda _show: None
    view._refresh_selected_session = lambda: None
    view._editor_dirty = False

    TimelineView._toggle_detail_mode(view)
    assert view._detail_mode == "details"
    assert view.toggle_detail_button.config["text"] == "查看汇总"

    TimelineView._toggle_detail_mode(view)
    assert view._detail_mode == "resources"
    assert view.toggle_detail_button.config["text"] == "查看明细"


def test_timeline_project_values_include_description():
    view = object.__new__(TimelineView)
    view.start_var = FakeVar("2026-06-18")
    view.end_var = FakeVar("2026-06-18")
    view.date_var = view.start_var
    session = {
        "project_name": "Client",
        "project_description": "billable",
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:10:00",
        "duration_seconds": 600,
        "status_summary": "Spec.docx",
    }
    resource = {
        "display_name": "Spec.docx",
        "resource_type": "file",
        "total_duration_seconds": 600,
        "event_count": 1,
        "project_name": "Client",
        "project_description": "billable",
    }

    assert TimelineView._session_values(view, session)[1] == "Client (billable)"
    assert TimelineView._resource_values(view, resource)[4] == "Client (billable)"


def test_open_context_selects_requested_session_on_sync():
    view = object.__new__(TimelineView)
    view.date_var = FakeVar()
    view.only_uncategorized = FakeVar(False)
    view._pending_session_id = None
    view._selected_session_id = None
    view._sessions_by_id = {}
    view.session_count_label = FakeWidget()
    view.session_tree = FakeTree()
    selected = []
    view._sync_tree = lambda *_args, **_kwargs: None
    view._select_tree_item = lambda _tree, iid: selected.append(iid)

    TimelineView.open_context(view, "2026-06-18", only_uncategorized=True, selected_session_id="9-10")
    TimelineView._sync_sessions(
        view,
        [
            {"session_id": "1-2", "project_name": "A", "duration_seconds": 60, "status_summary": "A"},
            {"session_id": "9-10", "project_name": "B", "duration_seconds": 90, "status_summary": "B"},
        ],
    )

    assert view.date_var.get() == "2026-06-18"
    assert view.only_uncategorized.get() is True
    assert view._selected_session_id == "9-10"
    assert selected == ["9-10"]
    assert view._pending_session_id is None


def test_refresh_keeps_selected_resource_editor_open_when_resource_still_exists():
    view = object.__new__(TimelineView)
    view._selected_resource_id = 7
    view._resource_selected_at = time.monotonic()
    view.resource_editor = FakeWidget(mapped=True)
    view.resource_tree = FakeTree()
    view._resources_by_id = {}
    loaded = []
    hidden = []
    selected = []
    view._sync_tree = lambda *_args, **_kwargs: None
    view._select_tree_item = lambda _tree, iid: selected.append(iid)
    view._load_resource_editor = lambda resource_id: loaded.append(resource_id) or True
    view._show_resource_editor = lambda show: hidden.append(show)

    view._selected_session_id = "session-1"
    view.new_project_var = FakeVar("Typing Project")

    view._sync_resources(
        [
            {
                "resource_id": 7,
                "display_name": "Spec.docx",
                "resource_type": "file",
                "total_duration_seconds": 60,
                "event_count": 1,
                "project_name": "Client",
            }
        ]
    )

    assert view._selected_resource_id == 7
    assert view._selected_session_id == "session-1"
    assert view.new_project_var.get() == "Typing Project"
    assert selected == ["7"]
    assert loaded == [7]
    assert hidden == []


def test_sync_resources_hides_editor_only_when_selected_resource_disappears():
    view = object.__new__(TimelineView)
    view._selected_resource_id = 7
    view._resource_selected_at = time.monotonic()
    view.resource_editor = FakeWidget(mapped=True)
    view.resource_tree = FakeTree()
    view._resources_by_id = {}
    hidden = []
    view._sync_tree = lambda *_args, **_kwargs: None
    view._show_resource_editor = lambda show: hidden.append(show)

    view._sync_resources([])

    assert view._selected_resource_id is None
    assert hidden == [False]


def test_current_activity_text_uses_second_level_duration(temp_db):
    view = object.__new__(TimelineView)
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps(
            {
                "resource_display_name": "Spec.docx",
                "app_name": "Word",
                "process_name": "word.exe",
                "inferred_project_name": "Client",
                "status": "normal",
                "start_time": "",
                "elapsed_seconds": 65,
                "is_persisted": True,
            },
            ensure_ascii=False,
        ),
    )

    assert TimelineView._current_activity_text(view) == "当前活动：Spec.docx｜Client｜00:01:05｜已进入历史"


def test_refresh_current_activity_updates_stable_resource_values_without_full_refresh(monkeypatch):
    view = _live_view_stub("resources")
    snapshot = _live_snapshot(35)
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(snapshot)
    old_session = {
        "session_id": "1-1",
        "project_id": 1,
        "project_name": "Client",
        "start_time": "2026-06-18 09:00:00",
        "end_time": None,
        "report_date": "2026-06-18",
        "duration_seconds": 30,
        "activity_ids": [1],
        "event_count": 1,
        "status_summary": "正常活动",
        "is_uncategorized": False,
    }
    new_session = {**old_session, "duration_seconds": 35}
    old_resource = {
        "resource_id": 7,
        "display_name": "Spec.docx",
        "resource_type": "file",
        "total_duration_seconds": 30,
        "event_count": 1,
        "activity_ids": [1],
        "project_name": "Client",
    }
    new_resource = {**old_resource, "total_duration_seconds": 35}
    view._sessions_by_id = {"1-1": old_session}
    view._resources_by_id = {7: old_resource}
    view._session_live_bases = {"1-1": 30}
    view._resource_live_bases = {7: 30}
    _seed_tree(view, view.session_tree, [("1-1", TimelineView._session_values(view, old_session))])
    _seed_tree(view, view.resource_tree, [("7", TimelineView._resource_values(view, old_resource))])
    view._selected_resource_id = 7
    fallback_refreshes = []

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", _fail_if_called)
    monkeypatch.setattr(timeline_service, "get_session_resource_summary", _fail_if_called)
    monkeypatch.setattr("worktrace.ui.timeline_view.snapshot_seconds_for_date_range", lambda *_args, **_kwargs: 35)
    view.refresh = lambda **kwargs: fallback_refreshes.append(kwargs)

    TimelineView.refresh_current_activity(view)

    assert fallback_refreshes == []
    assert view.current_activity_label.config["text"] == "当前活动：Spec｜Client｜00:00:35｜已进入历史"
    assert view.session_tree.item_calls == [("1-1", TimelineView._session_values(view, new_session))]
    assert view.resource_tree.item_calls == [("7", TimelineView._resource_values(view, new_resource))]
    assert view.session_tree.moves == []
    assert view.resource_tree.moves == []
    assert view.resource_tree.deleted == []


def test_refresh_current_activity_updates_stable_detail_values_without_full_refresh(monkeypatch):
    view = _live_view_stub("details")
    snapshot = _live_snapshot(35)
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(snapshot)
    session = {
        "session_id": "1-1",
        "project_id": 1,
        "project_name": "Client",
        "start_time": "2026-06-18 09:00:00",
        "end_time": None,
        "report_date": "2026-06-18",
        "duration_seconds": 35,
        "activity_ids": [1],
        "event_count": 1,
        "status_summary": "正常活动",
        "is_uncategorized": False,
    }
    old_detail = {
        "id": 1,
        "start_time": "2026-06-18 09:00:00",
        "end_time": None,
        "app_name": "Word",
        "window_title": "Spec.docx",
        "resource_display_name": "Spec.docx",
        "duration_seconds": 30,
        "project_name": "Client",
        "note": "",
    }
    new_detail = {**old_detail, "duration_seconds": 35}
    view._sessions_by_id = {"1-1": session}
    view._details_by_id = {1: old_detail}
    view._session_live_bases = {"1-1": 30}
    view._detail_live_bases = {1: 30}
    _seed_tree(view, view.session_tree, [("1-1", TimelineView._session_values(view, session))])
    _seed_tree(view, view.detail_tree, [("1", TimelineView._detail_values(view, old_detail))])
    view._selected_activity_id = 1
    fallback_refreshes = []

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", _fail_if_called)
    monkeypatch.setattr(timeline_service, "get_session_activity_details", _fail_if_called)
    monkeypatch.setattr("worktrace.ui.timeline_view.snapshot_seconds_for_date_range", lambda *_args, **_kwargs: 35)
    view.refresh = lambda **kwargs: fallback_refreshes.append(kwargs)

    TimelineView.refresh_current_activity(view)

    assert fallback_refreshes == []
    assert view.detail_tree.item_calls == [("1", TimelineView._detail_values(view, new_detail))]
    assert view.detail_tree.moves == []
    assert view.detail_tree.deleted == []


def test_refresh_current_activity_falls_back_when_snapshot_identity_changes(monkeypatch):
    view = _live_view_stub("resources")
    old_snapshot = _live_snapshot(30)
    new_snapshot = {**old_snapshot, "persisted_activity_id": 2}
    settings_service.set_setting("current_activity_snapshot", json.dumps(new_snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(old_snapshot)
    old_session = {
        "session_id": "1-1",
        "project_id": 1,
        "project_name": "Client",
        "start_time": "2026-06-18 09:00:00",
        "end_time": None,
        "report_date": "2026-06-18",
        "duration_seconds": 30,
        "activity_ids": [1],
        "event_count": 1,
        "status_summary": "正常活动",
        "is_uncategorized": False,
    }
    view._sessions_by_id = {"1-1": old_session}
    _seed_tree(view, view.session_tree, [("1-1", TimelineView._session_values(view, old_session))])
    fallback_refreshes = []

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", _fail_if_called)
    view.refresh = lambda **kwargs: fallback_refreshes.append(kwargs)

    TimelineView.refresh_current_activity(view)

    assert fallback_refreshes == [{"ensure_context": False}]
    assert view.session_tree.item_calls == []


def test_refresh_current_activity_skips_tables_while_user_interacts(monkeypatch):
    view = _live_view_stub("resources")
    snapshot = _live_snapshot(35)
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(snapshot)
    view.is_user_interacting = lambda: True
    session_calls = []
    fallback_refreshes = []

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", lambda *_args, **_kwargs: session_calls.append("called"))
    view.refresh = lambda **kwargs: fallback_refreshes.append(kwargs)

    TimelineView.refresh_current_activity(view)

    assert view.current_activity_label.config["text"] == "当前活动：Spec｜Client｜00:00:35｜已进入历史"
    assert session_calls == []
    assert fallback_refreshes == []


def test_timeline_resource_rule_dialog_prefills_selected_resource(monkeypatch):
    view = object.__new__(TimelineView)
    view._selected_resource_id = 7
    view._resources_by_id = {
        7: {"full_path": "D:\\Client\\Spec.docx", "display_name": "Spec.docx"}
    }
    view.resource_project_var = FakeVar("Client")
    view.resource_editor = FakeWidget(mapped=True)
    view._resource_selected_at = 0.0
    calls = []
    monkeypatch.setattr(
        "worktrace.ui.timeline_view.open_project_rule_dialog",
        lambda _master, **kwargs: calls.append(kwargs),
    )

    TimelineView._open_resource_project_rule_dialog(view)

    assert calls[0]["initial_type"] == "file"
    assert calls[0]["initial_target"] == "D:\\Client\\Spec.docx"
    assert calls[0]["initial_project_name"] == "Client"


def test_project_rule_saved_selects_project_immediately(temp_db):
    project_service.create_project("Client")
    view = _view_stub("")
    view.session_project_var = FakeVar("")
    view.activity_project_var = FakeVar("")
    view.refresh = lambda: None

    TimelineView._after_project_rule_saved(view, {"project_name": "Client"})

    assert view.session_project_var.get() == "Client"
    assert view.resource_project_var.get() == "Client"
    assert view.activity_project_var.get() == "Client"
    assert "Client" in view._project_by_name
    assert view.resource_hint_label.config["text"] == "已保存新建项目规则：Client"


def test_created_project_can_be_used_for_resource_correction_immediately(temp_db):
    aid = activity_service.create_activity("Word", "winword.exe", "Spec.docx", start_time="2026-06-18 09:00:00")
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    resource = timeline_service.get_session_resource_summary(session["activity_ids"])[0]
    project_service.create_project("Client")
    view = _view_stub("")
    view.session_project_var = FakeVar("")
    view.activity_project_var = FakeVar("")
    view.refresh = lambda: None
    TimelineView._after_project_rule_saved(view, {"project_name": "Client"})
    view._sessions_by_id = {session["session_id"]: session}
    view._selected_session_id = session["session_id"]
    view._resources_by_id = {int(resource["resource_id"]): resource}
    view._selected_resource_id = int(resource["resource_id"])

    view._save_resource_project(False)

    assert activity_service.get_activity(aid)["project_id"] == view._project_by_name["Client"]
