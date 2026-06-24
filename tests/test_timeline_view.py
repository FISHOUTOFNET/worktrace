import json

from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, project_service, settings_service, timeline_service
from worktrace.services.live_time_service import snapshot_signature
from worktrace.ui import design
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
        self.text = ""

    def bind(self, *args, **kwargs):
        self.bindings.append((args, kwargs))

    def configure(self, **kwargs):
        self.config.update(kwargs)

    def cget(self, key):
        return self.config.get(key, "")

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

    def delete(self, *_args):
        self.text = ""

    def insert(self, _index, value):
        self.text += str(value)

    def get(self, *_args):
        return self.text


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
        self.xview_position = 0.0
        self.selected = []
        self.focused = None

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

    def xview(self):
        return (self.xview_position, 1.0)

    def xview_moveto(self, position):
        self.xview_position = position

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
        return tuple(self.selected)

    def selection_set(self, iid):
        self.selected = [iid]

    def selection_remove(self, _selection):
        self.selected = []

    def focus(self, iid):
        self.focused = iid

    def see(self, _iid):
        pass


def _view_stub():
    view = object.__new__(TimelineView)
    view.start_var = FakeVar("2026-06-18")
    view.end_var = FakeVar("2026-06-18")
    view.date_var = view.start_var
    view.only_uncategorized = FakeVar(False)
    view.session_project_var = FakeVar("")
    view.adjust_project_var = FakeVar("")
    view.activity_project_var = view.adjust_project_var
    view.session_project_menu = FakeWidget()
    view.activity_project_menu = FakeWidget()
    view.adjust_project_menu = view.activity_project_menu
    view.adjustment_hint_label = FakeWidget()
    view.adjustment_editor = FakeWidget(mapped=True)
    view.activity_editor = view.adjustment_editor
    view.note_text = FakeWidget()
    view.note_label = FakeWidget()
    view.session_note_text = FakeWidget()
    view.activity_editor_label = FakeWidget()
    view._project_by_name = {}
    view._project_name_by_id = {}
    view._activity_project_targets = {}
    view._details_by_id = {}
    view._selected_activity_id = None
    view._active_adjustment = None
    view._editor_dirty = False
    view._loading_editor = False
    view._session_note_dirty = False
    view._session_note_placeholder_active = False
    view._session_note_loading = False
    view._session_note_save_after_id = None
    view.focus_get = lambda: None
    return view


def _live_view_stub():
    view = _view_stub()
    view.current_activity_label = FakeWidget()
    view.detail_label = FakeWidget()
    view.session_note_text = FakeWidget()
    view.session_count_label = FakeWidget()
    view.session_tree = FakeTree()
    view.detail_tree = FakeTree()
    view._tree_values = {}
    view._tree_column_widths = {}
    view._tree_keys = {id(view.session_tree): "sessions", id(view.detail_tree): "details"}
    view._sessions_by_id = {}
    view._details_by_id = {}
    view._session_live_bases = {}
    view._detail_live_bases = {}
    view._current_snapshot = None
    view._current_signature = None
    view._short_activity_carry = None
    view._selected_session_id = "1-1"
    view._selected_activity_id = None
    view._session_project_dirty = False
    view._session_note_dirty = False
    view._session_note_placeholder_active = False
    view._session_note_loading = False
    view._session_note_save_after_id = None
    view._project_name_by_id = {1: "Client"}
    view.is_user_interacting = lambda: False
    view._valid_range = lambda show_message=True: True
    view.after_idle = lambda func, *args: func(*args)
    view.focus_get = lambda: None
    return view


def _seed_tree(view, tree, items):
    if not hasattr(view, "_tree_values"):
        view._tree_values = {}
    tree.children = [iid for iid, _values in items]
    tree.items = {iid: tuple(values) for iid, values in items}
    for iid, values in items:
        view._tree_values[f"{id(tree)}:{iid}"] = tuple(values)


def _live_snapshot(seconds=35, *, persisted=True):
    return {
        "activity_display_name": "Spec.docx",
        "app_name": "Word",
        "process_name": "word.exe",
        "inferred_project_name": "Client",
        "status": "normal",
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": seconds,
        "persisted_activity_id": 1 if persisted else None,
        "is_persisted": persisted,
    }


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("live tick must not call timeline service queries")


def test_visible_activity_editor_blocks_auto_refresh():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view.adjustment_editor = FakeWidget(mapped=True)
    view.activity_editor = view.adjustment_editor
    view._active_adjustment = {"kind": "activity"}
    view.focus_get = lambda: None

    assert view.is_user_interacting()


def test_no_visible_editor_or_focus_is_not_user_interacting():
    view = object.__new__(TimelineView)
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = []
    view.adjustment_editor = FakeWidget(mapped=False)
    view.activity_editor = view.adjustment_editor
    view._active_adjustment = None
    view.focus_get = lambda: None

    assert not view.is_user_interacting()


def test_activity_editor_widgets_are_part_of_interaction_guard():
    view = object.__new__(TimelineView)
    activity_control = FakeWidget()
    view._control_active = False
    view._editor_dirty = False
    view._editor_widgets = [activity_control]
    view.adjustment_editor = FakeWidget(mapped=False)
    view.activity_editor = view.adjustment_editor
    view._active_adjustment = None
    view.focus_get = lambda: activity_control

    assert view.is_user_interacting()


def test_detail_area_builds_activity_detail_table_only(monkeypatch):
    view = object.__new__(TimelineView)
    view.content_frame = FakeWidget()
    view.session_project_var = FakeVar()
    created_trees = []

    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkFrame", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_label", lambda _self, master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_button", lambda _self, master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_option_menu", lambda _self, master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_make_tree_frame", lambda _self, parent: FakeWidget(master=parent))

    def fake_make_tree(_self, _master, tree_key, columns, headings, widths, height=None):
        created_trees.append((tree_key, tuple(columns), dict(headings), dict(widths), height))
        return FakeTree(columns)

    monkeypatch.setattr(TimelineView, "_make_tree", fake_make_tree)

    TimelineView._build_detail_area(view)

    assert created_trees[0][0] == "details"
    assert created_trees[0][1] == ("time", "resource_type", "resource_name", "duration", "project", "note")
    assert "resource" not in created_trees[0][1]
    assert not hasattr(view, "resource_tree")
    assert hasattr(view, "session_note_text")
    assert not hasattr(view, "save_session_note_button")
    assert not hasattr(view, "session_note_frame")


def test_adjustment_editor_has_activity_controls_only(monkeypatch):
    view = object.__new__(TimelineView)
    view.editor_panel = FakeWidget()
    view.adjust_project_var = FakeVar()
    view.activity_project_var = view.adjust_project_var

    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkFrame", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr("worktrace.ui.timeline_view.ctk.CTkTextbox", lambda master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_label", lambda _self, master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_button", lambda _self, master, **_kwargs: FakeWidget(master=master))
    monkeypatch.setattr(TimelineView, "_option_menu", lambda _self, master, **_kwargs: FakeWidget(master=master))

    TimelineView._build_adjustment_editor(view)

    assert view.adjustment_editor.master is view.editor_panel
    assert view.activity_editor is view.adjustment_editor
    assert view.activity_rule_button in view._editor_widgets
    assert view.delete_activity_button in view._editor_widgets
    assert not hasattr(view, "resource_editor")
    assert not hasattr(view, "resource_rule_button")
    assert not hasattr(view, "delete_resource_button")
    assert not hasattr(view, "remember_button")


def test_tree_column_widths_are_saved_and_restored():
    view = object.__new__(TimelineView)
    tree = FakeTree(columns=("window", "duration"))
    tree.widths["window"] = 240
    view._tree_keys = {id(tree): "details"}
    view._tree_column_widths = {}

    TimelineView._save_tree_column_widths(view, tree)
    tree.widths["window"] = 120
    TimelineView._apply_tree_column_widths(view, tree)

    assert tree.widths["window"] == 240


def test_sync_tree_values_only_updates_values_without_layout_changes():
    view = object.__new__(TimelineView)
    tree = FakeTree()
    view._tree_values = {}
    _seed_tree(view, tree, [("1", ("old",)), ("2", ("same",))])

    assert TimelineView._sync_tree_values_only(view, tree, [("1", ("new",)), ("2", ("same",))])
    assert tree.item_calls == [("1", ("new",))]
    assert tree.moves == []
    assert tree.deleted == []


def test_sync_tree_values_only_rejects_structure_changes():
    view = object.__new__(TimelineView)
    tree = FakeTree()
    view._tree_values = {}
    _seed_tree(view, tree, [("1", ("old",))])

    assert not TimelineView._sync_tree_values_only(view, tree, [("2", ("new",))])
    assert tree.item_calls == []


def test_timeline_project_values_include_description():
    view = object.__new__(TimelineView)
    view.start_var = FakeVar("2026-06-18")
    view.end_var = view.start_var
    session = {
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:10:00",
        "project_name": "Client",
        "project_description": "billable",
        "duration_seconds": 600,
        "status_summary": "Spec",
    }
    detail = {
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:10:00",
        "app_name": "Word",
        "window_title": "Spec.docx",
        "duration_seconds": 600,
        "project_name": "Client",
        "project_description": "billable",
    }

    assert TimelineView._session_values(view, session)[1] == "Client (billable)"
    assert TimelineView._detail_values(view, detail)[4] == "Client (billable)"


def test_open_context_selects_requested_session_on_sync():
    view = object.__new__(TimelineView)
    view.date_var = FakeVar()
    view.start_var = view.date_var
    view.end_var = view.date_var
    view.only_uncategorized = FakeVar(False)
    view._pending_session_id = None
    view._selected_session_id = None
    view._sessions_by_id = {}
    view.session_count_label = FakeWidget()
    view.session_tree = FakeTree()
    selected = []
    view._refresh_activity_project_targets = lambda: None
    view._activity_ids_live_seconds = lambda *_args: 0
    view._sessions_with_short_activity_carry = lambda sessions, _snapshot: sessions
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


def test_find_session_containing_activity_clears_uncategorized_filter_for_project_target(monkeypatch):
    view = object.__new__(TimelineView)
    view.start_var = FakeVar("2026-06-18")
    view.end_var = FakeVar("2026-06-18")
    view.only_uncategorized = FakeVar(True)
    target = {"session_id": "2-2", "activity_ids": [2], "is_uncategorized": False}

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", lambda *_args, **_kwargs: [target])

    assert TimelineView._find_session_containing_activity(view, 2) == target
    assert view.only_uncategorized.get() is False


def test_sync_details_keeps_selected_activity_editor_open_when_activity_still_exists():
    view = _live_view_stub()
    view._selected_activity_id = 7
    view.adjustment_editor = FakeWidget(mapped=True)
    view._active_adjustment = {"kind": "activity"}
    selected = []
    loaded = []
    view._select_tree_item = lambda _tree, iid: selected.append(iid)
    view._load_activity_editor = lambda activity_id: loaded.append(activity_id)

    TimelineView._sync_details(
        view,
        [
            {
                "id": 7,
                "start_time": "2026-06-18 09:00:00",
                "end_time": "2026-06-18 09:05:00",
                "app_name": "Word",
                "window_title": "Spec.docx",
                "duration_seconds": 300,
                "project_name": "Client",
            }
        ],
    )

    assert view._selected_activity_id == 7
    assert selected == ["7"]
    assert loaded == [7]


def test_sync_details_hides_editor_when_selected_activity_disappears():
    view = _live_view_stub()
    view._selected_activity_id = 7
    view.adjustment_editor = FakeWidget(mapped=True)
    view._active_adjustment = {"kind": "activity"}
    hidden = []
    view._show_activity_editor = lambda show: hidden.append(show)

    TimelineView._sync_details(view, [])

    assert view._selected_activity_id is None
    assert view._active_adjustment is None
    assert hidden == [False]


def test_session_note_empty_value_uses_summary_placeholder():
    view = _live_view_stub()
    session = {
        "duration_seconds": 300,
        "event_count": 2,
        "status_summary": "Spec.docx",
        "session_note": "",
    }

    TimelineView._load_session_note(view, session)

    assert view.session_note_text.text == "00:05:00 | 2 条活动 | Spec.docx"
    assert view.session_note_text.config["text_color"] == design.color(design.MUTED_TEXT)
    assert view._session_note_placeholder_active is True
    assert TimelineView._current_session_note(view) == ""


def test_session_note_user_text_uses_primary_text_color():
    view = _live_view_stub()

    TimelineView._load_session_note(view, {"session_note": "follow up"})

    assert view.session_note_text.text == "follow up"
    assert view.session_note_text.config["text_color"] == design.color(design.TEXT)
    assert view._session_note_placeholder_active is False


def test_session_note_flush_persists_current_text(monkeypatch):
    view = _live_view_stub()
    view._selected_session_id = "1-1"
    view._sessions_by_id = {
        "1-1": {
            "session_id": "1-1",
            "report_date": "2026-06-18",
            "first_activity_id": 11,
            "activity_ids": [11],
            "duration_seconds": 300,
            "event_count": 1,
            "status_summary": "Spec.docx",
        }
    }
    view.session_note_text.insert("1.0", "client note")
    view._session_note_dirty = True
    saved = []
    monkeypatch.setattr(timeline_service, "update_session_note", lambda *args: saved.append(args))

    TimelineView._flush_session_note_if_dirty(view)

    assert saved == [("2026-06-18", 11, "client note")]
    assert view._sessions_by_id["1-1"]["session_note"] == "client note"
    assert view._session_note_dirty is False


def test_session_select_flushes_dirty_note_before_switch(monkeypatch):
    view = _live_view_stub()
    view._selected_session_id = "old"
    view._session_note_dirty = True
    view.session_tree.selected = ["new"]
    calls = []
    monkeypatch.setattr(TimelineView, "_flush_session_note_if_dirty", lambda self: calls.append(self._selected_session_id))
    monkeypatch.setattr(TimelineView, "_refresh_selected_session", lambda self: None)

    TimelineView._on_session_select(view)

    assert calls == ["old"]
    assert view._selected_session_id == "new"


def test_tree_copy_text_helpers_return_cell_and_row_values():
    view = object.__new__(TimelineView)
    tree = FakeTree(columns=("time", "summary"))
    view._tree_values = {}
    _seed_tree(view, tree, [("1", ("09:00-09:30", "Spec.docx"))])

    assert TimelineView._tree_cell_text(view, tree, "1", "#2") == "Spec.docx"
    assert TimelineView._tree_row_text(view, tree, "1") == "09:00-09:30\tSpec.docx"


def test_current_activity_text_uses_activity_display_name(temp_db):
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps({**_live_snapshot(35), "activity_display_name": "Spec.docx"}, ensure_ascii=False),
    )

    assert TimelineView._current_activity_text(object.__new__(TimelineView)) == "当前活动：Spec.docx｜Client｜00:00:35｜已进入历史"


def test_refresh_current_activity_updates_stable_detail_values_without_full_refresh(monkeypatch):
    view = _live_view_stub()
    snapshot = _live_snapshot(35)
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(snapshot)
    session = {
        "session_id": "1-1",
        "project_id": 1,
        "project_name": "Client",
        "project_description": "",
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:00:30",
        "report_date": "2026-06-18",
        "duration_seconds": 30,
        "activity_ids": [1],
        "event_count": 1,
        "status_summary": "Spec.docx",
        "is_uncategorized": False,
    }
    detail = {
        "id": 1,
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:00:30",
        "app_name": "Word",
        "window_title": "Spec.docx",
        "duration_seconds": 30,
        "project_name": "Client",
    }
    live_session = {**session, "duration_seconds": 35}
    live_detail = {**detail, "duration_seconds": 35}
    view._sessions_by_id = {"1-1": session}
    view._details_by_id = {1: detail}
    view._session_live_bases = {"1-1": 30}
    view._detail_live_bases = {1: 30}
    _seed_tree(view, view.session_tree, [("1-1", TimelineView._session_values(view, session))])
    _seed_tree(view, view.detail_tree, [("1", TimelineView._detail_values(view, detail))])

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", _fail_if_called)
    view.refresh = lambda **_kwargs: _fail_if_called()

    TimelineView.refresh_current_activity(view)

    assert view.current_activity_label.config["text"] == "当前活动：Spec.docx｜Client｜00:00:35｜已进入历史"
    assert view.session_tree.item_calls == [("1-1", TimelineView._session_values(view, live_session))]
    assert view.detail_tree.item_calls == [("1", TimelineView._detail_values(view, live_detail))]


def test_refresh_current_activity_falls_back_when_snapshot_identity_changes(monkeypatch):
    view = _live_view_stub()
    old_snapshot = _live_snapshot(30)
    new_snapshot = {
        **old_snapshot,
        "activity_display_name": "Other.docx",
        "window_title": "Other.docx",
        "elapsed_seconds": 35,
    }
    settings_service.set_setting("current_activity_snapshot", json.dumps(new_snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(old_snapshot)
    fallback_refreshes = []

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", _fail_if_called)
    view.refresh = lambda **kwargs: fallback_refreshes.append(kwargs)

    TimelineView.refresh_current_activity(view)

    assert fallback_refreshes == [{"ensure_context": False}]
    assert view.session_tree.item_calls == []


def test_refresh_current_activity_skips_tables_while_user_interacts(monkeypatch):
    view = _live_view_stub()
    snapshot = _live_snapshot(35)
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view._current_signature = snapshot_signature(snapshot)
    view.is_user_interacting = lambda: True
    session_calls = []
    fallback_refreshes = []

    monkeypatch.setattr(timeline_service, "get_project_sessions_by_range", lambda *_args, **_kwargs: session_calls.append("called"))
    view.refresh = lambda **kwargs: fallback_refreshes.append(kwargs)

    TimelineView.refresh_current_activity(view)

    assert view.current_activity_label.config["text"] == "当前活动：Spec.docx｜Client｜00:00:35｜已进入历史"
    assert session_calls == []
    assert fallback_refreshes == []


def test_timeline_session_carries_unconfirmed_activity_without_detail_updates(temp_db):
    view = _live_view_stub()
    confirmed = _live_snapshot(300)
    transient = {
        "activity_display_name": "B.docx",
        "app_name": "Word",
        "process_name": "word.exe",
        "inferred_project_name": "Other",
        "status": "normal",
        "start_time": "2026-06-18 09:05:00",
        "elapsed_seconds": 12,
        "persisted_activity_id": None,
        "is_persisted": False,
    }
    settings_service.set_setting("current_activity_snapshot", json.dumps(transient, ensure_ascii=False))
    view._current_snapshot = confirmed
    view._current_signature = snapshot_signature(confirmed)
    view._short_activity_carry = None
    session = {
        "session_id": "1-1",
        "project_id": 1,
        "project_name": "Client",
        "project_description": "",
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:05:00",
        "report_date": "2026-06-18",
        "duration_seconds": 300,
        "activity_ids": [1],
        "event_count": 1,
        "status_summary": "A.docx",
        "is_uncategorized": False,
    }
    detail = {
        "id": 1,
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:05:00",
        "app_name": "Word",
        "window_title": "A.docx",
        "duration_seconds": 300,
        "project_name": "Client",
    }
    view._sessions_by_id = {"1-1": session}
    view._details_by_id = {1: detail}
    view._session_live_bases = {"1-1": 300}
    view._detail_live_bases = {1: 300}
    _seed_tree(view, view.session_tree, [("1-1", TimelineView._session_values(view, session))])
    _seed_tree(view, view.detail_tree, [("1", TimelineView._detail_values(view, detail))])

    def fake_refresh(**_kwargs):
        view._current_snapshot = transient
        view._current_signature = snapshot_signature(transient)
        view._sessions_by_id = {"1-1": session}
        view._session_live_bases = {"1-1": 0}
        display_session = TimelineView._session_with_short_activity_carry(view, session, transient)
        TimelineView._sync_tree_values_only(view, view.session_tree, [("1-1", TimelineView._session_values(view, display_session))])
        TimelineView._sync_selected_session_summary(view, display_session)

    view.refresh = fake_refresh

    TimelineView.refresh_current_activity(view)

    carried_session = {**session, "duration_seconds": 312}
    assert view.current_activity_label.config["text"] == "当前活动：B.docx｜Other｜00:00:12｜暂不入历史"
    assert view.session_tree.item_calls == [("1-1", TimelineView._session_values(view, carried_session))]
    assert view.session_note_text.text == "00:05:12 | 1 条活动 | A.docx"
    assert view.session_note_text.config["text_color"] == design.color(design.MUTED_TEXT)
    assert view.detail_tree.item_calls == []


def test_activity_rule_dialog_prefills_selected_anchor_activity(monkeypatch):
    view = _view_stub()
    view.adjust_project_var.set("Client")
    row = {
        "id": 42,
        "project_id": 1,
        "official_project_name": "Client",
        "project_name": "Client",
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:05:00",
        "app_name": "Word",
        "window_title": "Spec.docx",
        "duration_seconds": 300,
        "resource_is_anchor": True,
        "activity_display_name": "Spec.docx",
        "resource_path_hint": "D:\\Client\\Spec.docx",
    }
    captured = {}
    monkeypatch.setattr("worktrace.ui.timeline_view.open_project_rule_dialog", lambda *_args, **kwargs: captured.update(kwargs))

    view._active_adjustment = TimelineView._adjustment_from_activity(view, row)
    TimelineView._open_adjustment_project_rule_dialog(view)

    assert captured["initial_type"] == "folder"
    assert captured["initial_target"] == "D:\\Client"
    assert captured["initial_project_name"] == "Client"


def test_activity_rule_dialog_prefills_keyword_for_auxiliary_activity(monkeypatch):
    view = _view_stub()
    row = {
        "id": 42,
        "project_id": 1,
        "official_project_name": "Client",
        "project_name": "Client",
        "start_time": "2026-06-18 09:00:00",
        "end_time": "2026-06-18 09:05:00",
        "app_name": "Edge",
        "window_title": "Research",
        "duration_seconds": 300,
        "resource_is_anchor": False,
        "activity_display_name": "Research",
    }
    captured = {}
    monkeypatch.setattr("worktrace.ui.timeline_view.open_project_rule_dialog", lambda *_args, **kwargs: captured.update(kwargs))

    view._active_adjustment = TimelineView._adjustment_from_activity(view, row)
    TimelineView._open_adjustment_project_rule_dialog(view)

    assert captured["initial_type"] == "keyword"
    assert captured["initial_target"] == "Research"


def test_session_rule_dialog_prefills_folder_from_activity_resource(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    activity = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx - Word",
        file_path_hint="D:\\Client\\Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    activity_service.finalize_created_activity(activity)
    activity_service.close_activity(activity, "2026-06-18 09:05:00")
    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    view = _view_stub()
    view._sessions_by_id = {session["session_id"]: session}
    view._selected_session_id = session["session_id"]
    view.session_project_var.set("Client")
    captured = {}
    monkeypatch.setattr("worktrace.ui.timeline_view.open_project_rule_dialog", lambda *_args, **kwargs: captured.update(kwargs))

    TimelineView._open_project_rule_dialog(view)

    assert captured["initial_type"] == "folder"
    assert captured["initial_target"] == "D:\\Client"
    assert captured["initial_project_name"] == "Client"


def test_project_rule_saved_selects_project_immediately(temp_db):
    project_service.create_project("Client")
    view = _view_stub()
    refreshed = []
    view.refresh = lambda: refreshed.append("refresh")

    TimelineView._after_project_rule_saved(view, {"project_name": "Client"})

    assert view.session_project_var.get() == "Client"
    assert view.activity_project_var.get() == "Client"
    assert view.adjustment_hint_label.config["text"] == "已保存新建项目规则：Client"
    assert refreshed == ["refresh"]


def test_created_project_can_be_used_for_activity_correction_immediately(temp_db):
    activity = activity_service.create_activity("Word", "winword.exe", "Spec.docx", start_time="2026-06-18 09:00:00")
    activity_service.finalize_created_activity(activity)
    activity_service.close_activity(activity, "2026-06-18 09:05:00")
    project = project_service.create_project("Client")
    row = activity_service.get_activity(activity)
    view = _view_stub()
    view._project_by_name = {"Client": project}
    view._project_name_by_id = {project: "Client"}
    view.adjust_project_var.set("Client")
    view._details_by_id = {activity: row}
    view._active_adjustment = TimelineView._adjustment_from_activity(view, row)
    view.note_text.insert("1.0", "reviewed")
    focused = []
    view._focus_activity_after_refresh = lambda activity_id: focused.append(activity_id)

    TimelineView._save_adjustment(view)

    updated = activity_service.get_activity(activity)
    assert updated["project_id"] == project
    assert updated["note"] == "reviewed"
    assert focused == [activity]
