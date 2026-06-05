from __future__ import annotations

from textual.app import App
from textual.containers import Container, Horizontal
from textual.binding import Binding
from textual.widgets import ListView, ListItem, Input, Tree, Footer, Label, Static, Button, Switch
from textual.screen import Screen
from textual.message import Message
from textual.reactive import reactive
from textual import events
from typing import Iterable, Sequence
from html import unescape

from bibleit import translation
from bibleit.config import config_path, env_overrides, load_config, save_config, theme_is_dark
from bibleit.history import HistoryEntry, SessionHistory
from bibleit.live_publisher import LivePublisher, running_in_browser
from bibleit.navigation import (
    NavigationState,
    NavigationSuggester,
    RowRef,
    complete_navigation_value,
    navigation_completion_candidates,
    next_chapter_ref,
    parse_navigation_ref,
    previous_chapter_ref,
    select_navigation_completion,
    verse_reference_label,
)
from bibleit.text_find import TextFindResult, cached_find_index


import atexit
import inspect
import re
import asyncio

from rich.markup import escape


class HistoryScreen(Screen):
    BINDINGS = [
        ("escape", "close_screen", "Close"),
        ("ctrl+h", "close_screen", "History"),
        Binding("enter", "go_to_selected", "Go To", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._filter = ""
        self._navigating = False

    def compose(self):
        with Container(id="history-panel"):
            yield Label("History", id="history-title")
            yield Input(placeholder="Filter verses…", id="history-filter")
            yield ListView(id="history-list")

    def on_mount(self) -> None:
        self._refresh_list()
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
        bible_view = self.app.query_exactly_one(BibleView)
        self._navigating = True
        try:
            bible_view.go_to_ref(entry.as_ref())
            self.app.record_history_entry(entry)
            self.app.pop_screen()
        finally:
            self._navigating = False

    def _refresh_list(self, *, keep_index: bool = False) -> None:
        list_view = self._history_list()
        previous_index = list_view.index if keep_index else None
        list_view.clear()
        for entry in self.app.history.entries(self._filter):
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
        self._refresh_list(keep_index=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "history-list":
            return

        if not self._history_list_focused():
            return

        entry = getattr(event.item, "entry", None)
        if entry is None:
            return

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
        self.app.pop_screen()
        self.app.query_exactly_one(BibleView).focus()


class StatusBar(Horizontal):
    can_focus = False
    can_focus_children = True
    translations = reactive(list)
    strongs = reactive(False)
    live = reactive(False)
    compact = reactive(False)
    menu_open = reactive(False)
    command_mode = reactive(False)
    completions_open = reactive(False)

    def __init__(self):
        super().__init__()
        self._completing = False
        self._completion_matches: list[str] = []
        self._completion_index = 0

    def compose(self):
        yield Button("☰", id="action-menu")
        yield Static(id="status-left")
        yield Static("[#8d8478]?[/] Help", id="status-help")
        yield Input(
            placeholder=">",
            suggester=NavigationSuggester(self._active_translation),
            id="status-command",
        )
        yield Static(id="status-command-completions")
        with Container(id="status-actions"):
            yield Button("Find", id="action-find")
            yield Button("History", id="action-history")
            yield Button("Translations", id="action-translations")
            yield Button("Strongs", id="action-strongs")
            yield Button("Config", id="action-config")
            yield Button("Live", id="action-live")

    def watch_translations(self):
        self._refresh()

    def watch_strongs(self):
        self._refresh()

    def watch_live(self):
        self._refresh()

    def watch_compact(self):
        self.set_class(self.compact, "compact")

        if not self.compact:
            self.menu_open = False

    def watch_menu_open(self):
        self.set_class(self.menu_open, "open")

    def watch_command_mode(self):
        self.set_class(self.command_mode, "command-mode")
        if not self.command_mode:
            self.completions_open = False

    def watch_completions_open(self):
        self.set_class(self.completions_open, "completions-open")

    def on_mount(self):
        self.set_class(running_in_browser(), "browser")
        self._refresh()

    def on_resize(self, event: events.Resize) -> None:
        self.compact = event.size.width < 72

    def _refresh(self):
        translation_text = (
            " [#b8b0a6]·[/] ".join(f"[#d97706]{t}[/]" for t in self.translations)
            if self.translations
            else "No translation selected"
        )

        left = " [#b8b0a6]·[/] ".join(
            filter(
                None,
                [
                    "[bold]bibleit[/]",
                    translation_text,
                    "[#d97706]STRONGS[/]" if self.strongs else None,
                    "[#d97706]LIVE[/]" if self.live else None,
                ],
            )
        )

        self.query_one("#status-left", Static).update(left)

        strongs_button = self.query_one("#action-strongs", Button)
        config_button = self.query_one("#action-config", Button)
        live_button = self.query_one("#action-live", Button)
        strongs_button.set_class(self.strongs, "active")
        config_button.display = not running_in_browser()
        live_button.set_class(self.live, "active")
        live_button.disabled = running_in_browser()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bible_view = self.app.query_exactly_one(BibleView)

        actions = {
            "action-menu": self.action_toggle_menu,
            "action-find": bible_view.action_open_find,
            "action-history": bible_view.action_toggle_history,
            "action-translations": bible_view.action_open_translations,
            "action-strongs": bible_view.action_toggle_strongs,
            "action-config": bible_view.action_open_config,
            "action-live": bible_view.action_toggle_live,
        }

        if event.button.id in actions:
            event.stop()
            result = actions[event.button.id]()

            if inspect.isawaitable(result):
                await result

            if self.compact and event.button.id != "action-menu":
                self.menu_open = False

    def action_toggle_menu(self) -> None:
        self.menu_open = not self.menu_open

    def open_command(self) -> None:
        command = self.query_one("#status-command", Input)
        self.command_mode = True
        command.value = ""
        command.cursor_position = len(command.value)
        command.focus()

    def close_command(self) -> None:
        self.command_mode = False
        self.completions_open = False
        self._completion_matches = []
        self._completion_index = 0
        self.query_one("#status-command", Input).value = ""
        self.query_one("#status-command-completions", Static).update("")
        self.app.query_exactly_one(BibleView).focus()

    def _active_translation(self) -> translation.Translation | None:
        bible_view = self.app.query_exactly_one(BibleView)
        view = bible_view.focused_view() or (bible_view.views[0] if bible_view.views else None)
        return view.translation if view is not None else None

    def _set_command_value(self, value: str) -> None:
        command = self.query_one("#status-command", Input)
        command.value = value
        command.cursor_position = len(command.value)

    def _show_completions(self, completions: Sequence[str], index: int = 0) -> None:
        self._completion_matches = list(completions)
        self._completion_index = index % len(completions) if completions else 0

        def render(completion: str, completion_index: int) -> str:
            if completion_index == self._completion_index:
                return f"[#f3f1ed on #d97706]{completion}[/]"
            return f"[#d97706]{completion}[/]"

        self.query_one("#status-command-completions", Static).update(
            "  ".join(render(completion, index) for index, completion in enumerate(completions))
        )
        self.completions_open = bool(completions)

    def _hide_completions(self) -> None:
        self._completion_matches = []
        self._completion_index = 0
        self.query_one("#status-command-completions", Static).update("")
        self.completions_open = False

    def cycle_completion(self, direction: int) -> bool:
        if not self.completions_open or not self._completion_matches:
            return False

        self._show_completions(
            self._completion_matches,
            self._completion_index + direction,
        )
        return True

    def clear_command_text(self) -> None:
        command = self.query_one("#status-command", Input)
        command.value = ""
        command.cursor_position = 0
        self._hide_completions()

    def complete_command(self) -> None:
        translation_ = self._active_translation()
        if translation_ is None:
            return

        command = self.query_one("#status-command", Input)
        completed, completions, changed = complete_navigation_value(command.value, translation_)

        if self.completions_open and self._completion_matches == list(completions):
            self._show_completions(completions, self._completion_index + 1)
            return

        if changed:
            self._completing = True
            try:
                self._set_command_value(completed)
            finally:
                self._completing = False

        if len(completions) > 1:
            self._show_completions(completions)
        else:
            self._hide_completions()

    def select_completion(self) -> bool:
        if not self.completions_open or not self._completion_matches:
            return False

        completion = self._completion_matches[self._completion_index]
        command = self.query_one("#status-command", Input)
        self._completing = True
        try:
            self._set_command_value(select_navigation_completion(command.value, completion))
        finally:
            self._completing = False
        self._hide_completions()
        return True

    def refresh_command_completions(self) -> None:
        translation_ = self._active_translation()
        if translation_ is None:
            self._hide_completions()
            return

        command = self.query_one("#status-command", Input)
        if not command.value.strip():
            self._hide_completions()
            return

        completions = navigation_completion_candidates(command.value, translation_)
        if completions:
            index = self._completion_index if self._completion_matches == list(completions) else 0
            self._show_completions(completions, index)
        else:
            self._hide_completions()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "status-command":
            return

        event.stop()
        self.select_completion()

        bible_view = self.app.query_exactly_one(BibleView)
        command = self.query_one("#status-command", Input)
        if bible_view.go_to_command(command.value):
            self.close_command()

    def on_key(self, event: events.Key) -> None:
        if not self.command_mode:
            return

        if event.key == "escape":
            event.stop()
            command = self.query_one("#status-command", Input)
            if command.value or self.completions_open:
                self.clear_command_text()
            else:
                self.close_command()
        elif event.key == "tab":
            event.stop()
            self.complete_command()
        elif event.key in ("left", "right") and self.completions_open:
            event.stop()
            self.cycle_completion(-1 if event.key == "left" else 1)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "status-command" and not self._completing:
            self.refresh_command_completions()


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
        bible_view = self.app.query_exactly_one(BibleView)
        bible_view.go_to_ref(result.ref)
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


class Translations(Screen):
    AVAILABLE_NODE_LABEL = "Available"
    INSTALLED_NODE_LABEL = "Installed"
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        ("ctrl+i", "install", "Install"),
        ("ctrl+u", "uninstall", "Uninstall"),
        ("ctrl+o", "open", "Open"),
        Binding("enter", "activate", "Open/Install", priority=True),
    ]

    class Open(Message):
        def __init__(self, translation: translation.Translation):
            self.translation = translation
            super().__init__()

    def compose(self):
        yield Tree("Translations")
        yield Footer(show_command_palette=False)

    def on_mount(self):
        self._build_tree()

    def _build_tree(self, active_slug: str = None):
        tree = self.query_exactly_one(Tree)
        tree.root.remove_children()
        active_node = None
        installed = tree.root.add(self.INSTALLED_NODE_LABEL)
        available = tree.root.add(self.AVAILABLE_NODE_LABEL)
        tree.root.expand_all()

        for t in translation.get_installed().values():
            node = installed.add_leaf(str(t), t)
            if t.slug == active_slug:
                active_node = node
        installed.expand_all()

        for lang in translation.get_languages_available():
            language = available.add(lang.name)
            for t in lang.translations:
                if not translation.is_installed(t.slug):
                    language.add_leaf(str(t), t)
            if not language.children:
                language.remove()

        def select_active():
            tree.cursor_line = active_node.line if active_node else 0

        self.call_after_refresh(select_active)

    def _install_node(self, node) -> None:
        data = node.data
        if data and not translation.is_installed(data.slug):
            try:
                translation.install(data.slug)
                self.notify(data.name, title="Translation installed", timeout=7)
            except Exception as e:
                self.notify(
                    f"Failed to install translation: {e}!",
                    title=str(data),
                    severity="error",
                    timeout=7,
                )
            finally:
                self._build_tree(data.slug)
        else:
            self.notify(
                str(data),
                title="Translation already installed",
                severity="warning",
                timeout=3,
            )

    def action_install(self):
        self._install_node(self.query_exactly_one(Tree).cursor_node)

    def action_uninstall(self):
        node = self.query_exactly_one(Tree).cursor_node
        data = node.data
        if data and translation.is_installed(data.slug):
            try:
                translation.uninstall(data.slug)
                self.notify(data.name, title="Translation uninstalled", timeout=3)
            except Exception as e:
                self.notify(
                    f"Failed to uninstall translation: {e}!",
                    title=str(data),
                    severity="error",
                    timeout=7,
                )
            finally:
                self._build_tree()
        else:
            self.notify(
                str(data),
                title="Translation not installed",
                severity="warning",
                timeout=3,
            )

    def _open_node(self, node) -> None:
        data = node.data

        if not data:
            return

        if not translation.is_installed(data.slug):
            self.notify(
                "Translation not installed",
                title=str(data),
                severity="warning",
                timeout=3,
            )
            return

        self.app.query_exactly_one(BibleView).post_message(Translations.Open(translation.open(data.slug)))

        self.app.pop_screen()

    def action_open(self):
        self._open_node(self.query_exactly_one(Tree).cursor_node)

    def _activate_node(self, node) -> None:
        if node.children:
            if node.is_expanded:
                node.collapse()
            else:
                node.expand()
        elif node.data and node.parent:
            if node.parent.label.plain == self.INSTALLED_NODE_LABEL:
                self._open_node(node)
            else:
                self._install_node(node)

    def action_activate(self):
        node = self.query_exactly_one(Tree).cursor_node

        if node:
            self._activate_node(node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        self._activate_node(event.node)


class ConfigScreen(Screen):
    TEXT_CONFIGS = ("LIVE_TOKEN", "LIVE_URL")

    BINDINGS = [
        ("escape", "close", "Close"),
        ("ctrl+s", "save", "Save"),
    ]

    def compose(self):
        values = load_config()
        overrides = env_overrides()

        with Container(id="config-panel"):
            yield Label("Config", id="config-title")
            yield Label(f"Stored in {config_path()}", id="config-path")

            yield Label("Theme", classes="config-label")
            with Horizontal(id="config-theme-row"):
                yield Label("Dark mode", id="config-theme-label")
                yield Switch(value=theme_is_dark(), id="config-theme-dark")

            if "THEME" in overrides:
                yield Label(
                    "BIBLEIT_THEME is set and will take precedence.",
                    classes="config-note",
                )

            for name in self.TEXT_CONFIGS:
                yield Label(name, classes="config-label")
                input_ = Input(
                    value=values.get(name, ""),
                    placeholder=f"BIBLEIT_{name}",
                    id=f"config-{name.lower().replace('_', '-')}",
                )
                if name == "LIVE_TOKEN":
                    input_.password = True
                yield input_

                if name in overrides:
                    yield Label(
                        f"BIBLEIT_{name} is set and will take precedence.",
                        classes="config-note",
                    )

            with Horizontal(id="config-actions"):
                yield Button("Save", id="config-save")
                yield Button("Close", id="config-close")

    def _values(self) -> dict[str, str]:
        values = {
            name: self.query_one(f"#config-{name.lower().replace('_', '-')}", Input).value for name in self.TEXT_CONFIGS
        }
        values["THEME"] = "dark" if self.query_one("#config-theme-dark", Switch).value else "light"
        return values

    def action_save(self) -> None:
        values = self._values()
        save_config(values)
        self.app.apply_theme(theme_is_dark())
        self.notify("Config saved", title=str(config_path()), timeout=3)

    def action_close(self) -> None:
        self.app.apply_theme(theme_is_dark())
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-save":
            event.stop()
            self.action_save()
        elif event.button.id == "config-close":
            event.stop()
            self.action_close()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()


class StrongScreen(Screen):
    HTML_TAG_RE = re.compile(r"<[^>]+>")
    STRONG_LINK_RE = re.compile(
        r"<a\s+href=['\"]S:([^'\"]+)['\"]>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    REPLACEMENTS = [
        (r"<br\s*/?>", "\n"),
        (r"</p>", "\n\n"),
        (r"<hr\s*/?>", "\n────────────────────\n"),
        (r"<b>(.*?)</b>", r"[bold]\1[/]"),
        (r"<big>(.*?)</big>", r"[bold]\1[/]"),
        (r"<i>(.*?)</i>", r"[italic]\1[/]"),
        (r"<grk>(.*?)</grk>", r"[italic #d8c090]\1[/]"),
        (r"<heb>(.*?)</heb>", r"[italic #d8c090]\1[/]"),
        (
            r"<font color='3'>(.*?)</font>",
            r"[#d8c090]\1[/]",
        ),
        (
            r"<font color='4'>(.*?)</font>",
            r"[italic #909090]\1[/]",
        ),
        (
            r"<font color='5'>(.*?)</font>",
            r"[bold #ffb347]\1[/]",
        ),
    ]

    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
    ]

    def __init__(
        self,
        translation: translation.Translation,
        code: str,
        entry,
    ):
        super().__init__()
        self.translation = translation
        self.code = code
        self.entry = entry

    def render_strongs_html(self, html: str) -> str:
        if not html:
            return ""

        html = unescape(html)

        # Strong cross references
        def replace_link(match):
            raw_code = match.group(1).upper().strip()
            inner = match.group(2)
            inner = re.sub(r"<[^>]+>", "", inner).strip()

            if raw_code.startswith(("H", "G")):
                code = raw_code
            else:
                if self.code.startswith("H"):
                    code = f"H{raw_code}"
                else:
                    code = f"G{raw_code}"

            if code not in self.translation.strongs:
                alt = f"G{raw_code}" if code.startswith("H") else f"H{raw_code}"

                if alt in self.translation.strongs:
                    code = alt

            exists = code in self.translation.strongs

            if exists:
                return f"[bold underline #ffb347]" f"[@click=app.open_strong('{code}')]" f"{inner}" f"[/][/]"

            return f"[dim]{inner}[/]"

        html = self.STRONG_LINK_RE.sub(replace_link, html)

        for pattern, repl in self.REPLACEMENTS:
            html = re.sub(
                pattern,
                repl,
                html,
                flags=re.IGNORECASE | re.DOTALL,
            )

        html = self.HTML_TAG_RE.sub("", html)
        html = re.sub(r"\n{3,}", "\n\n", html)
        return html.strip()

    def compose(self):
        with Container():
            yield Label(
                f"""
        [bold #ffb347]{self.code}[/]

        [bold]Lemma:[/] {self.entry.lemma}

        [bold]Transliteration:[/] {self.entry.transliteration}

        [bold]Definition:[/]
        {self.entry.definition}

        [bold]Description:[/]
        {self.render_strongs_html(self.entry.description)}
        """,
                markup=True,
            )


class OverlayStatusMixin:
    def _refresh_status(self) -> None:
        try:
            bible_view = self.app.query_exactly_one(BibleView)
            status = self.query_exactly_one(StatusBar)
        except Exception:
            return

        status.translations = [view.translation.slug for view in bible_view.views]
        status.strongs = any(view.show_strongs for view in bible_view.views)
        status.live = bible_view.state.live


class ShortcutsScreen(OverlayStatusMixin, Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        ("?", "app.pop_screen", "Close"),
    ]

    SHORTCUTS = [
        ("↑ / ↓", "Previous / next verse"),
        ("Ctrl+A", "Beginning of current chapter"),
        ("Ctrl+E", "End of current chapter"),
        ("<", "Previous chapter"),
        (">", "Next chapter"),
        ("g", "Go to"),
        ("Tab", "Cycle go-to matches"),
        ("Enter", "Select match or navigate"),
        ("Ctrl+T", "Translations"),
        ("Ctrl+F", "Find text"),
        ("Ctrl+G", "Strongs"),
        ("Ctrl+H", "History"),
        ("Ctrl+P", "Config"),
        ("Ctrl+D", "Toggle theme"),
        ("Ctrl+W", "Close pane"),
        ("F2", "Toggle split layout"),
        ("Ctrl+L", "Live mode"),
        ("?", "Show shortcuts"),
        ("Esc", "Close / clear"),
    ]

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.pop_screen()

    def on_mount(self) -> None:
        self._refresh_status()

    def compose(self):
        with Container():
            yield Label("Shortcuts", id="shortcuts-title")
            for key, description in self.SHORTCUTS:
                with Horizontal(classes="shortcut-row"):
                    yield Label(key, classes="shortcut-key")
                    yield Label(description, classes="shortcut-description")
        yield StatusBar()


class WelcomeScreen(OverlayStatusMixin, Screen):
    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.pop_screen()

    def on_key(self, event: events.Key) -> None:
        event.stop()
        key = event.key
        character = event.character

        self.app.pop_screen()

        def dispatch(action):
            bible_view = self.app.query_exactly_one(BibleView)
            action(bible_view)

        actions = {
            "?": lambda view: view.action_show_shortcuts(),
            "question_mark": lambda view: view.action_show_shortcuts(),
            "ctrl+t": lambda view: view.action_open_translations(),
            "ctrl+f": lambda view: view.action_open_find(),
            "ctrl+g": lambda view: view.action_toggle_strongs(),
            "ctrl+h": lambda view: view.action_toggle_history(),
            "ctrl+l": lambda view: view.action_toggle_live(),
            "ctrl+p": lambda view: view.action_open_config(),
            "ctrl+d": lambda view: self.app.action_toggle_theme(),
            "g": lambda view: view.action_open_reference(),
            "G": lambda view: view.action_open_reference(),
            ":": lambda view: view.action_open_reference(),
            "up": lambda view: self.app.run_worker(view.action_previous_verse(), exit_on_error=False),
            "down": lambda view: self.app.run_worker(view.action_next_verse(), exit_on_error=False),
            "<": lambda view: view.action_previous_chapter(),
            ">": lambda view: view.action_next_chapter(),
            "ctrl+a": lambda view: view.action_chapter_start(),
            "ctrl+e": lambda view: view.action_chapter_end(),
            "f2": lambda view: view.action_toggle_layout(),
        }

        action = actions.get(key) or actions.get(character)
        if action is not None:
            self.app.call_after_refresh(dispatch, action)

    def on_mount(self) -> None:
        self._refresh_status()

    def compose(self):
        with Container():
            yield Label("bibleit", id="welcome-title")
            yield Label("interactive Bible reading", id="welcome-subtitle")
            yield Label(
                "Open translations, move through Scripture, and share live verses.",
                id="welcome-description",
            )
            for key, description in [
                ("↑ / ↓", "Previous / next verse"),
                ("g", "Go to book, chapter, or verse"),
                ("Ctrl+F", "Find text in the current translation"),
                ("Ctrl+T", "Open translations"),
                ("Ctrl+L", "Toggle live mode"),
                ("?", "Show all shortcuts"),
            ]:
                with Horizontal(classes="welcome-row"):
                    yield Label(key, classes="welcome-key")
                    yield Label(description, classes="welcome-row-description")
        yield StatusBar()


class View(ListView):
    INITIAL_ROWS = 25
    STRONG_RE = re.compile(r"<S>(.*?)</S>")

    class Render(Message):
        def __init__(self, slug: str, value: Iterable[str]):
            self.slug = slug
            self.value = value
            super().__init__()

    class Navigate(Message):
        def __init__(self, ref: translation.TranslationRef):
            self.ref = ref
            super().__init__()

    def __init__(
        self,
        state: NavigationState,
        translation_: translation.Translation,
        *children,
    ):
        super().__init__(*children)

        self.state = state
        self.translation = translation_
        self.cursor = None
        self.show_strongs = False
        self.syncing = False
        self.live = LivePublisher()
        self._live_publish_group = f"live-publish-{id(self)}"
        self._live_mode_group = f"live-mode-{id(self)}"
        self._pending_live_publish: dict | None = None
        self._live_publish_running = False
        self._pointer_down_y: int | None = None
        self._cursor_move_lock = asyncio.Lock()

    def _select_first(self):
        if self.children:
            self.focus()
            self.index = 0
            self.publish_current()

    def publish_current(self):
        if not self.state.live:
            return

        if self.index is None:
            return

        if 0 <= self.index < len(self.children):
            row = self.children[self.index]

            if isinstance(row, ListItem):
                self._publish_row(row)

    def set_live_mode(self, live: bool) -> None:
        self.run_worker(
            self.live.set_live(live),
            group=self._live_mode_group,
            exclusive=True,
            exit_on_error=False,
        )

    def _publish_row(self, row: ListItem) -> None:
        payload = self.live.verse_payload(row.data, self.translation.slug)

        if payload is None:
            return

        self._publish_payload(payload)

    def _publish_payload(self, payload: dict) -> None:
        self._pending_live_publish = payload

        if self._live_publish_running:
            return

        self._start_live_publish_worker()

    def _start_live_publish_worker(self) -> None:
        self._live_publish_running = True
        self.run_worker(
            self._drain_live_publish(),
            group=self._live_publish_group,
            exit_on_error=False,
        )

    async def _drain_live_publish(self) -> None:
        try:
            while self._pending_live_publish is not None:
                await asyncio.sleep(0.05)
                payload = self._pending_live_publish
                self._pending_live_publish = None
                published = await self.live.publish_payload(payload)

                if not published and self._pending_live_publish is None:
                    self._pending_live_publish = payload
                    await asyncio.sleep(0.25)
        finally:
            self._live_publish_running = False

            if self._pending_live_publish is not None and self.is_attached:
                self._start_live_publish_worker()

    def _sync_state_from_row(self, row: ListItem, publish: bool = True) -> bool:
        ref = self._row_ref(row)

        if not ref:
            return False

        self.state.bookid = ref.bookid
        self.state.chapter = ref.chapter
        self.state.verse = ref.verse
        self.state.index = self.children.index(row) if row in self.children else 0

        if publish:
            self._publish_row(row)

        return True

    def value_for_ref(self, ref: translation.TranslationRef) -> str | None:
        try:
            cursor = self.translation.cursor_from(ref)
        except RuntimeError:
            return None

        value = cursor.next()

        if value is None:
            return None

        return self._decode_row(value)

    def _is_highlighting_state(self) -> bool:
        if self.index is None or not 0 <= self.index < len(self.children):
            return False

        row = self.children[self.index]

        if not isinstance(row, ListItem):
            return False

        return self._row_ref(row) == RowRef(
            self.state.bookid,
            self.state.chapter,
            self.state.verse,
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is not self:
            return

        if event.item is None:
            return

        if self._sync_state_from_row(event.item, publish=False) and not self.syncing:
            self.scroll_to_widget(
                event.item,
                animate=False,
                immediate=True,
                force=False,
            )
            self._post_navigate()

    def _post_navigate(self) -> None:
        self.post_message(
            View.Navigate(
                translation.TranslationRef(
                    self.state.bookid,
                    self.state.chapter,
                    self.state.verse,
                )
            )
        )

    def _style_row(self, text: str) -> str:
        text = re.sub(r"(.* \d+:\d+)", r"[bold]\1 [/]", text)
        text = re.sub(r"<b>(.*?)</b>", r"[bold]\1[/]", text)
        text = re.sub(r"<i>(.*?)</i>", r"[italic]\1[/]", text)

        def replace_strong(match):
            raw = match.group(1).strip()

            if not self.translation:
                return raw

            prefix = "H"

            if self.children:
                ref = self._row_ref(self.children[0])

                if ref:
                    prefix = self._strong_prefix(ref.bookid)

            code = f"{prefix}{raw}"

            entry = self.translation.strongs.get(code)

            if not entry:
                return ""

            if not self.show_strongs:
                return ""

            label = raw

            return f"[#c96f00]" f"[@click=app.open_strong('{code}')]" f"ᴴ{label}" f"[/]"

        text = text.replace("<br>", "\n").replace("<br/>", "\n")
        text = self.STRONG_RE.sub(replace_strong, text)
        text = re.sub(
            r"<sup>(.*?)</sup>",
            r"[dim italic]\1[/]",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return text

    def _make_row(self, value: str) -> ListItem:
        label = Label(self._style_row(value), markup=True)
        row = ListItem(label)
        row.data = value
        return row

    def _decode_row(self, value) -> str:
        return value.memoryview().tobytes().decode("utf-8", "replace")

    def _append_cursor_row(self) -> bool:
        if self.cursor is None:
            return False
        value = self.cursor.next()
        if value is None:
            return False
        self.append(self._make_row(self._decode_row(value)))
        return True

    def _load_cursor_rows(self, cursor, count: int = INITIAL_ROWS) -> None:
        self.cursor = cursor
        for _ in range(count):
            if not self._append_cursor_row():
                break

    def _load_cursor_rows_around(self, ref: translation.TranslationRef, index: int) -> int:
        previous_rows: list[ListItem] = []
        previous_cursor = self.translation.cursor_from(ref)

        for _ in range(max(0, index)):
            value = previous_cursor.previous()

            if value is None:
                break

            previous_rows.insert(0, self._make_row(self._decode_row(value)))

        cursor = self.translation.cursor_from(ref)
        self.cursor = cursor

        for row in previous_rows:
            self.append(row)

        remaining = max(1, self.INITIAL_ROWS - len(previous_rows))

        for _ in range(remaining):
            if not self._append_cursor_row():
                break

        return len(previous_rows)

    def _row_ref(self, row: ListItem) -> RowRef | None:
        return self._ref_from_text(getattr(row, "data", ""))

    def _ref_from_text(self, text: str) -> RowRef | None:
        if not self.translation:
            return None

        match = re.match(r"^(?P<book>.+)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+", text)
        if not match:
            return None

        if bookid := self.translation.resolve_bookid(match.group("book")):
            return RowRef(
                bookid=bookid,
                chapter=int(match.group("chapter")),
                verse=int(match.group("verse")),
            )

    def _cursor_from_row(self, row: ListItem):
        ref = self._row_ref(row)
        if ref is None or self.translation is None:
            return None
        return self.translation.cursor_from(translation.TranslationRef(ref.bookid, ref.chapter, ref.verse))

    def _previous_row(self) -> ListItem | None:
        if not self.children:
            return None

        cursor = self._cursor_from_row(self.children[0])
        if cursor is None:
            return None

        value = cursor.previous()
        if value is None:
            return None

        return self._make_row(self._decode_row(value))

    def _next_row(self) -> ListItem | None:
        if not self.children:
            return None

        cursor = self._cursor_from_row(self.children[-1])
        if cursor is None:
            return None

        cursor.next()
        value = cursor.next()
        if value is None:
            return None

        return self._make_row(self._decode_row(value))

    def _force_highlight(self, index: int) -> None:
        for child in self.children:
            if isinstance(child, ListItem):
                child.highlighted = False

        self.index = None
        self.index = index

        if 0 <= index < len(self.children):
            row = self.children[index]

            if isinstance(row, ListItem):
                row.highlighted = True

                self.scroll_to_widget(
                    row,
                    animate=False,
                    immediate=True,
                    force=True,
                )

                if self._sync_state_from_row(row, publish=False) and not self.syncing:
                    self._post_navigate()

    def _force_highlight_row(self, row: ListItem) -> None:
        try:
            index = self.children.index(row)
        except ValueError:
            return
        self._force_highlight(index)

    def _force_highlight_row_after_refresh(self, row: ListItem) -> None:
        self.call_after_refresh(self._force_highlight_row, row)

    def _valid_index(self) -> int | None:
        if not self.children:
            self.index = None
            return None

        if self.index is None:
            return None

        index = min(max(self.index, 0), len(self.children) - 1)
        if index != self.index:
            self.index = index
        return index

    def _strong_prefix(self, bookid: int) -> str:
        return "H" if bookid <= 39 else "G"

    def on_translations_open(self, event: Translations.Open):
        self.clear()
        self.translation = event.translation

        self._load_cursor_rows(self.translation.read(translation.TranslationRef(bookid=1)))

        self.call_after_refresh(self._select_first)

    def on_view_render(self, event: Render):
        self.clear()
        self._load_cursor_rows(event.value)
        self.call_after_refresh(self._select_first)

    async def _move_cursor_down(self) -> None:
        async with self._cursor_move_lock:
            if not self.children:
                return

            self.focus()

            index = self._valid_index()
            if index is None:
                self.index = 0
                return

            if index == len(self.children) - 1:
                row = self._next_row()
                if row is None:
                    return
                await self.append(row)
                self._force_highlight_row_after_refresh(row)
                return

            try:
                self.action_cursor_down()
            except IndexError:
                self._force_highlight(min(index, len(self.children) - 1))

    async def _move_cursor_up(self) -> None:
        async with self._cursor_move_lock:
            if not self.children:
                return

            self.focus()

            index = self._valid_index()
            if index is None:
                self.index = len(self.children) - 1
                return

            if index == 0:
                row = self._previous_row()
                if row is None:
                    return
                await self.insert(0, [row])
                self._force_highlight_row_after_refresh(row)
                return

            try:
                self.action_cursor_up()
            except IndexError:
                self._force_highlight(min(index, len(self.children) - 1))

    async def on_key(self, event: events.Key):
        if event.key == "down":
            event.stop()
            await self._move_cursor_down()

        elif event.key == "up":
            event.stop()
            await self._move_cursor_up()

    async def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        await self._move_cursor_down()

    async def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        await self._move_cursor_up()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not running_in_browser():
            self.focus()
        self._pointer_down_y = event.screen_y

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        event.stop()

        if not running_in_browser():
            self.focus()

        try:
            self.index = self._nodes.index(event.item)
        except ValueError:
            return

        self.post_message(self.Selected(self, event.item, self.index))

    async def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pointer_down_y is None:
            return

        delta_y = self._pointer_down_y - event.screen_y
        self._pointer_down_y = None

        if abs(delta_y) < 2:
            return

        event.stop()
        steps = min(5, max(1, abs(delta_y) // 3))
        move = self._move_cursor_down if delta_y > 0 else self._move_cursor_up

        for _ in range(steps):
            await move()

    def sync_to_state(self, focus: bool = False):
        if not self.is_attached:
            return

        if self._is_highlighting_state():
            if focus:
                self.focus()
            return

        ref = translation.TranslationRef(
            self.state.bookid,
            self.state.chapter,
            self.state.verse,
        )

        try:
            self.syncing = True
            self.clear()

            if not self.is_attached:
                self.syncing = False
                return

            index = self._load_cursor_rows_around(ref, self.state.index)

            def restore():
                if not self.is_attached:
                    self.syncing = False
                    return

                self._force_highlight(index)
                if focus:
                    self.focus()
                self.syncing = False

            self.call_after_refresh(restore)
        except RuntimeError as e:
            self.log.error("error on cursor_from", e)
            self.notify(
                "Reference not found",
                severity="error",
                timeout=3,
            )

    def action_toggle_strongs(self):
        self.show_strongs = not self.show_strongs

        rows = [child.data for child in self.children]

        current_index = self.index or 0

        self.clear()

        for row in rows:
            self.append(self._make_row(row))

        status = self.app.query_exactly_one(StatusBar)
        status.strongs = self.show_strongs

        def restore():
            if self.children:
                self.index = min(current_index, len(self.children) - 1)
                self.focus()

        self.call_after_refresh(restore)


class BibleView(Horizontal):
    can_focus = True

    BINDINGS = [
        ("ctrl+t", "open_translations", "Translations"),
        ("ctrl+f", "open_find", "Find"),
        ("ctrl+g", "toggle_strongs", "Strongs"),
        ("ctrl+h", "toggle_history", "History"),
        ("ctrl+p", "open_config", "Config"),
        ("ctrl+l", "toggle_live", "Live"),
        ("ctrl+w", "close_pane", "Close Pane"),
        ("ctrl+a", "chapter_start", "Chapter Start"),
        ("ctrl+e", "chapter_end", "Chapter End"),
        ("<", "previous_chapter", "Previous Chapter"),
        (">", "next_chapter", "Next Chapter"),
        ("g", "open_reference", "Go To"),
        ("G", "open_reference", "Go To"),
        (":", "open_reference", "Go To"),
        ("?", "show_shortcuts", "Shortcuts"),
        ("f2", "toggle_layout", "Toggle Layout"),
    ]

    def __init__(self):
        super().__init__()
        self.state = NavigationState()
        self.views: list[View] = []
        self.vertical_layout = False

    def compose(self):
        yield Button("↑", id="nav-previous", classes="verse-nav")
        yield Button("↓", id="nav-next", classes="verse-nav")

    async def add_translation(
        self,
        translation: translation.Translation,
    ) -> None:
        view = View(self.state, translation)
        self.views.append(view)
        await self.mount(view)
        view.sync_to_state(focus=True)
        self.refresh_status()

        if self.state.live:
            self.publish_live_state()

    async def on_translations_open(
        self,
        event: Translations.Open,
    ) -> None:
        for view in self.views:
            if view.translation.slug == event.translation.slug:
                return
        await self.add_translation(event.translation)

    def on_view_navigate(self, event: View.Navigate):
        view = event.control

        for other in self.views:
            if other is view:
                continue

            if not other.is_attached:
                continue

            other.sync_to_state()

        self.publish_live_state()

    def go_to_ref(self, ref: translation.TranslationRef) -> None:
        self.state.bookid = ref.bookid
        self.state.chapter = ref.chapter or 1
        self.state.verse = ref.verse_start or 1
        self.state.index = 0

        focused_view = self.focused_view() or (self.views[0] if self.views else None)
        for view in self.views:
            view.sync_to_state(focus=view is focused_view)

        self.publish_live_state()

    def action_open_reference(self) -> None:
        if not self.views:
            self.notify(
                "Please open a translation first",
                severity="warning",
            )
            return
        self.app.query_exactly_one(StatusBar).open_command()

    def go_to_command(self, value: str) -> bool:
        view = self.focused_view() or (self.views[0] if self.views else None)
        if not view:
            self.notify(
                "Please open a translation first",
                severity="warning",
            )
            return False

        try:
            ref = parse_navigation_ref(value, view.translation, self.state)
            if view.value_for_ref(ref) is None:
                raise ValueError("Chapter/Verse not found")
        except (RuntimeError, ValueError) as error:
            self.notify(str(error), severity="error", timeout=3)
            return False

        self.go_to_ref(ref)
        self.app.record_history(view.translation, ref)
        return True

    def on_mount(self):
        self.app.install_screen(Translations(), name="translations")
        self.set_class(running_in_browser(), "browser")
        self.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav-previous":
            event.stop()
            await self.action_previous_verse()
        elif event.button.id == "nav-next":
            event.stop()
            await self.action_next_verse()

    def action_open_translations(self):
        if isinstance(self.screen, Translations):
            self.app.pop_screen()
        else:
            self.app.push_screen("translations")

    def action_open_find(self):
        if not self.views:
            self.notify(
                "Please open a translation first",
                severity="warning",
            )
            return

        view = self.focused_view()

        if not view:
            view = self.views[0]

        self.app.push_screen(Find(view, self.views))

    def action_open_config(self):
        if running_in_browser():
            return

        self.app.push_screen(ConfigScreen())

    def action_toggle_history(self) -> None:
        if isinstance(self.app.screen, HistoryScreen):
            self.app.pop_screen()
            self.focus()
        else:
            self.app.push_screen(HistoryScreen())

    async def action_previous_verse(self):
        view = self.focused_view() or (self.views[0] if self.views else None)

        if view:
            await view._move_cursor_up()

    async def action_next_verse(self):
        view = self.focused_view() or (self.views[0] if self.views else None)

        if view:
            await view._move_cursor_down()

    def _active_view(self) -> View | None:
        return self.focused_view() or (self.views[0] if self.views else None)

    def _chapter_end_ref(self, view: View) -> translation.TranslationRef | None:
        try:
            cursor = view.translation.cursor_chapter(translation.TranslationRef(self.state.bookid, self.state.chapter))
        except RuntimeError:
            return None

        last_ref = None
        while value := cursor.next():
            last_ref = view._ref_from_text(view._decode_row(value))

        if last_ref is None:
            return None

        return translation.TranslationRef(last_ref.bookid, last_ref.chapter, last_ref.verse)

    def action_chapter_start(self):
        view = self._active_view()
        if not view:
            return

        self.go_to_ref(translation.TranslationRef(self.state.bookid, self.state.chapter, 1))

    def action_chapter_end(self):
        view = self._active_view()
        if not view:
            return

        ref = self._chapter_end_ref(view)
        if ref is None:
            self.notify("Chapter end not found", severity="warning", timeout=3)
            return

        self.go_to_ref(ref)

    def action_next_chapter(self):
        view = self._active_view()
        if not view:
            return

        ref = next_chapter_ref(view.translation, self.state)
        if ref is None:
            return

        self.go_to_ref(ref)

    def action_previous_chapter(self):
        view = self._active_view()
        if not view:
            return

        ref = previous_chapter_ref(view.translation, self.state)
        if ref is None:
            return

        self.go_to_ref(ref)

    def action_show_shortcuts(self):
        self.app.push_screen(ShortcutsScreen())

    def action_toggle_layout(self):
        self.vertical_layout = not self.vertical_layout
        self.set_class(self.vertical_layout, "vertical")

    def action_toggle_strongs(self):
        view = self.focused_view()

        if not view:
            if self.views:
                view = self.views[0]
            else:
                return

        view.action_toggle_strongs()

    def action_toggle_live(self):
        if running_in_browser():
            return

        self.state.live = not self.state.live
        self.refresh_status()

        if self.state.live:
            view = self.focused_view() or (self.views[0] if self.views else None)

            if view:
                view.set_live_mode(True)
                self.publish_live_state()
        else:
            view = self.focused_view() or (self.views[0] if self.views else None)

            if view:
                view.set_live_mode(False)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "toggle_live" and running_in_browser():
            return False
        if action == "open_config" and running_in_browser():
            return False
        return True

    def disable_live_now(self) -> None:
        if not self.state.live:
            return

        self.state.live = False

        if self.views:
            self.views[0].live.set_live_blocking(False)

        if self.is_attached:
            self.refresh_status()

    def refresh_status(self):
        status = self.app.query_exactly_one(StatusBar)
        status.translations = [view.translation.slug for view in self.views]
        status.live = self.state.live

    def publish_live_state(self):
        if not self.state.live or not self.views:
            return

        ref = translation.TranslationRef(
            self.state.bookid,
            self.state.chapter,
            self.state.verse,
        )
        values = []

        for view in self.views:
            value = view.value_for_ref(ref)

            if value is not None:
                values.append((view.translation.slug, value))

        payload = self.views[0].live.bundle_payload(values)

        if payload is not None:
            self.views[0]._publish_payload(payload)

    async def action_close_pane(self):
        view = self.focused_view()
        if not view:
            return

        if len(self.views) <= 1:
            return

        index = self.views.index(view)
        self.views.remove(view)
        await view.remove()
        self.refresh_status()

        next_view = self.views[min(index, len(self.views) - 1)]
        next_view.focus()
        next_view.sync_to_state(focus=True)

        if self.state.live:
            self.publish_live_state()

    def focused_view(self) -> View | None:
        focused = self.app.focused

        while focused and not isinstance(focused, View):
            focused = focused.parent

        return focused


class Bibleit(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+d", "toggle_theme", "Theme"),
    ]

    def __init__(self):
        super().__init__()
        self.history = SessionHistory()
        self.dark_theme = theme_is_dark()
        atexit.register(self._disable_live_on_shutdown)

    def on_mount(self) -> None:
        self.apply_theme(self.dark_theme)
        self.push_screen(WelcomeScreen())

    def exit(self, *args, **kwargs) -> None:
        self._disable_live_on_shutdown()
        super().exit(*args, **kwargs)

    def on_unmount(self, event: events.Unmount) -> None:
        self._disable_live_on_shutdown()

    def _disable_live_on_shutdown(self) -> None:
        try:
            bible_view = self.query_exactly_one(BibleView)
        except Exception:
            return

        bible_view.disable_live_now()

    def action_open_strong(self, code: str):
        focused = self.focused
        view = focused

        while view and not isinstance(view, View):
            view = view.parent

        if not view:
            return

        if not view.translation:
            return

        entry = view.translation.strongs.get(code)

        if not entry:
            self.notify(
                f"Strong entry not found: {code}",
                severity="warning",
            )
            return

        self.push_screen(
            StrongScreen(
                view.translation,
                code,
                entry,
            )
        )

    def action_toggle_theme(self):
        self.apply_theme(not self.dark_theme)

        if not running_in_browser():
            save_config({"THEME": "dark" if self.dark_theme else "light"})

    def apply_theme(self, dark: bool) -> None:
        self.dark_theme = dark
        self.theme = "textual-dark" if dark else "textual-light"
        self.set_class(self.dark_theme, "dark")

    def record_history(
        self,
        translation_: translation.Translation,
        ref: translation.TranslationRef,
    ) -> None:
        chapter = ref.chapter or 1
        verse = ref.verse_start or 1
        label = verse_reference_label(translation_, ref.bookid, chapter, verse)
        self.record_history_entry(
            HistoryEntry(
                bookid=ref.bookid,
                chapter=chapter,
                verse=verse,
                label=label,
            )
        )

    def record_history_entry(self, entry: HistoryEntry) -> None:
        self.history.record(entry)

    def compose(self):
        with Horizontal(id="workspace"):
            yield BibleView()
        yield StatusBar()
