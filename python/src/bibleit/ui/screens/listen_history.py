from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Input, Label, ListItem, ListView

from bibleit.history import HistoryEntry


class ListenHistoryScreen(Screen):
    BINDINGS = [
        ("escape", "close_screen", "Close"),
        ("ctrl+shift+h", "close_screen", "Listen History"),
        Binding("enter", "go_to_selected", "Go To", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._filter = ""

    def compose(self):
        with Container(id="history-panel"):
            yield Label("Listen History", id="history-title")
            yield Input(placeholder="Filter recognized references...", id="history-filter")
            yield ListView(id="history-list")

    def on_mount(self) -> None:
        self.refresh_entries()
        self.call_after_refresh(self.action_focus_filter)

    def _history_list(self) -> ListView:
        return self.query_one("#history-list", ListView)

    def _history_filter(self) -> Input:
        return self.query_one("#history-filter", Input)

    def _history_list_focused(self) -> bool:
        focused = self.app.focused
        list_view = self._history_list()
        if focused is list_view:
            return True
        while focused is not None and focused is not self:
            if focused.parent is list_view:
                return True
            focused = focused.parent
        return False

    def _history_filter_focused(self) -> bool:
        focused = self.app.focused
        return focused is self._history_filter() or (isinstance(focused, Input) and focused.id == "history-filter")

    def action_focus_list(self) -> None:
        list_view = self._history_list()
        if list_view.children and list_view.index is None:
            list_view.index = 0
        list_view.focus()

    def action_focus_filter(self) -> None:
        self._history_filter().focus()

    def navigate_to(self, entry: HistoryEntry) -> None:
        from bibleit.ui.bible_view import BibleView

        bible_view = self.app.query_exactly_one(BibleView)
        bible_view.go_to_ref(entry.as_ref())
        self.app.record_history_entry(entry)
        self.app.pop_screen()

    def refresh_entries(self, *, keep_index: bool = False) -> None:
        list_view = self._history_list()
        previous_index = list_view.index if keep_index else None
        list_view.clear()
        for entry in self.app.listen_history.entries(self._filter):
            item = ListItem(Label(entry.label, classes="history-entry"))
            item.entry = entry
            list_view.append(item)

        if not list_view.children:
            return

        if keep_index and previous_index is not None:
            list_view.index = min(previous_index, len(list_view.children) - 1)
        else:
            list_view.index = 0

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.action_close_screen()
            return

        if self._history_filter_focused() and event.key == "down":
            event.stop()
            self.action_focus_list()
            return

        if self._history_list_focused() and event.key in ("up", "down"):
            event.stop()
            list_view = self._history_list()
            if not list_view.children:
                return
            if event.key == "down":
                list_view.action_cursor_down()
            else:
                if list_view.index in (None, 0):
                    self.action_focus_filter()
                    return
                list_view.action_cursor_up()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "history-filter":
            return
        self._filter = event.value
        self.refresh_entries(keep_index=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "history-list":
            return

        if not self._history_list_focused():
            return

        entry = getattr(event.item, "entry", None)
        if entry is not None:
            self.navigate_to(entry)

    def action_go_to_selected(self) -> None:
        list_view = self._history_list()
        if list_view.index is None or not 0 <= list_view.index < len(list_view.children):
            return

        row = list_view.children[list_view.index]
        entry = getattr(row, "entry", None)
        if entry is not None:
            self.navigate_to(entry)

    def action_close_screen(self) -> None:
        from bibleit.ui.bible_view import BibleView

        self.app.pop_screen()
        self.app.query_exactly_one(BibleView).focus()
