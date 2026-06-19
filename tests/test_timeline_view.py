import time

from worktrace.services import activity_service, project_service, timeline_service
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


def test_editor_panel_is_explicit_scrollable_container(monkeypatch):
    created = []

    def fake_scrollable(master, **kwargs):
        widget = FakeWidget(master=master)
        widget.config.update(kwargs)
        created.append(widget)
        return widget

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
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkScrollableFrame", fake_scrollable)
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkLabel", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkButton", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkEntry", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkCheckBox", lambda master, **_kwargs: FakeWidget(master=master))

    TimelineView._build(view)

    assert view.editor_panel is view.editor_scroll_frame
    assert created
    assert view.editor_scroll_frame.config["height"] == 260
    assert view.editor_scroll_frame.master is view


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
    assert view.new_project_entry in view._resource_editor_widgets
    assert view.create_project_button in view._resource_editor_widgets
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


def test_new_project_entry_focus_marks_user_interacting():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view.new_project_entry = FakeWidget()
    view._resource_editor_widgets = [view.new_project_entry]
    view.resource_editor = FakeWidget(mapped=True)
    view.activity_editor = FakeWidget(mapped=False)
    view._selected_resource_id = None
    view._resource_selected_at = 0.0
    view.focus_get = lambda: view.new_project_entry

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


def test_timeline_resource_editor_can_create_project_and_select_it(temp_db):
    view = _view_stub("Client")
    view._selected_session_id = "session-1"
    view._selected_resource_id = 7

    view._create_project_from_timeline()

    assert view.resource_project_var.get() == "Client"
    assert "Client" in view._project_by_name
    assert view.new_project_var.get() == ""
    assert view.resource_hint_label.config["text"] == "已创建项目：Client"
    assert view._selected_session_id == "session-1"
    assert view._selected_resource_id == 7


def test_timeline_project_create_requires_name(temp_db):
    view = _view_stub("")

    view._create_project_from_timeline()

    assert view.resource_hint_label.config["text"] == "请输入项目名称"


def test_timeline_project_create_reuses_existing_project(temp_db):
    project_service.create_project("Client")
    view = _view_stub("Client")

    view._create_project_from_timeline()

    assert view.resource_project_var.get() == "Client"
    assert view.resource_hint_label.config["text"] == "项目已存在，已选中：Client"


def test_created_project_can_be_used_for_resource_correction_immediately(temp_db):
    aid = activity_service.create_activity("Word", "winword.exe", "Spec.docx", start_time="2026-06-18 09:00:00")
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    resource = timeline_service.get_session_resource_summary(session["activity_ids"])[0]
    view = _view_stub("Client")
    view._create_project_from_timeline()
    view._sessions_by_id = {session["session_id"]: session}
    view._selected_session_id = session["session_id"]
    view._resources_by_id = {int(resource["resource_id"]): resource}
    view._selected_resource_id = int(resource["resource_id"])
    view.refresh = lambda: None

    view._save_resource_project(False)

    assert activity_service.get_activity(aid)["project_id"] == view._project_by_name["Client"]
