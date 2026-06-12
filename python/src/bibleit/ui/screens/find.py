from __future__ import annotations

from typing import Sequence

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from bibleit.text_find import TextFindResult, cached_find_index
from bibleit.ui.view import View


class Find(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("down", "focus_results", "Results", priority=True, show=False),
        Binding("up", "focus_input_from_results", "Find", priority=True, show=False),
        Binding("left", "previous_translation", "Previous translation", priority=True, show=False),
        Binding("right", "next_translation", "Next translation", priority=True, show=False),
    ]

    def __init__(
        self,
        view: View,
        views: Sequence[View] = (),
    ):
        super().__init__()

        self.views = list(views) or [view]
        self.view = view
        if self.view not in self.views:
            self.views.insert(0, self.view)
        self.view_index = self.views.index(self.view)
        self.input = Input(placeholder="Find words or phrases…", id="text-find-input")
        self.results: list[TextFindResult] = []

    def on_mount(self):
        self._refresh_translation_buttons()
        self.input.focus()

    def compose(self):
        with Container(id="find-panel"):
            yield Label("Find", id="find-title")
            yield Label(
                self._caption(),
                id="find-caption",
                markup=True,
            )
            with Horizontal(id="find-translations"):
                for view in self.views:
                    yield Button(
                        view.translation.slug,
                        name=view.translation.slug,
                        classes="find-translation",
                    )
            yield self.input
            yield Static("Type a word or phrase to find verse text.", id="find-summary")
            yield ListView(id="text-find-results")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "focus_results":
            return self.app.focused is self.input and bool(self._result_list().children)
        if action == "focus_input_from_results":
            return self._result_list_focused_at_first_item()
        return True

    def _caption(self) -> str:
        position = f" {self.view_index + 1}/{len(self.views)}" if len(self.views) > 1 else ""
        return f"Find text in [bold #d97706]{self.view.translation.slug}[/]{position}"

    def _result_list(self) -> ListView:
        return self.query_one("#text-find-results", ListView)

    def _result_list_focused_at_first_item(self) -> bool:
        result_list = self._result_list()
        return self.app.focused is result_list and result_list.index in (None, 0)

    def action_focus_results(self) -> None:
        result_list = self._result_list()
        if result_list.children:
            result_list.index = 0
        result_list.focus()

    def action_focus_input_from_results(self) -> None:
        self.input.focus()

    def action_previous_translation(self) -> None:
        self._switch_translation(-1)

    def action_next_translation(self) -> None:
        self._switch_translation(1)

    def _refresh_translation_buttons(self) -> None:
        for button in self.query(".find-translation").results(Button):
            button.set_class(button.name == self.view.translation.slug, "active")

    def _select_translation(self, slug: str | None) -> None:
        if not slug:
            return

        for index, view in enumerate(self.views):
            if view.translation.slug == slug:
                self.view_index = index
                self.view = view
                break
        else:
            return

        self.query_one("#find-caption", Label).update(self._caption())
        self._refresh_translation_buttons()
        self._refresh_results()
        self.input.focus()

    def _switch_translation(self, direction: int) -> None:
        if len(self.views) <= 1:
            return

        self.view_index = (self.view_index + direction) % len(self.views)
        self.view = self.views[self.view_index]
        self.query_one("#find-caption", Label).update(self._caption())
        self._refresh_translation_buttons()
        self._refresh_results()
        self.input.focus()

    def _refresh_results(self) -> None:
        query = self.input.value.strip()
        result_list = self._result_list()
        summary = self.query_one("#find-summary", Static)
        result_list.clear()

        if not query:
            self.results = []
            summary.update("Type a word or phrase to find verse text.")
            return

        self.results = cached_find_index(self.view.translation).find(query)
        if not self.results:
            summary.update(f"No results for [bold]{escape(query)}[/]")
            return

        noun = "result" if len(self.results) == 1 else "results"
        summary.update(f"{len(self.results)} {noun} for [bold]{escape(query)}[/]")

        for result in self.results:
            item = ListItem(
                Label(
                    f"[bold #d97706]{escape(result.label)}[/]  {escape(result.text)}",
                    markup=True,
                )
            )
            item.result = result
            result_list.append(item)

        result_list.index = 0

    def _open_result(self, result: TextFindResult) -> None:
        from bibleit.ui.bible_view import BibleView

        bible_view = self.app.query_exactly_one(BibleView)
        bible_view.go_to_ref(result.ref, live_history=True)
        self.app.record_history(self.view.translation, result.ref)
        self.app.pop_screen()

    def action_open_selected(self) -> None:
        result_list = self._result_list()
        if result_list.index is None:
            return

        item = result_list.children[result_list.index]
        result = getattr(item, "result", None)
        if result is not None:
            self._open_result(result)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self.input:
            self._refresh_results()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("find-translation"):
            event.stop()
            self._select_translation(event.button.name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is not self.input:
            return

        event.stop()
        self.action_open_selected()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view is not self._result_list():
            return

        event.stop()
        result = getattr(event.item, "result", None)
        if result is not None:
            self._open_result(result)
