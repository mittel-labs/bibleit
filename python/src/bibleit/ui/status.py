from __future__ import annotations

import inspect
from typing import Sequence

from textual import events
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Input, Static

from bibleit.live_publisher import running_in_browser
from bibleit import translation
from bibleit.navigation import (
    NavigationSuggester,
    complete_navigation_value,
    navigation_completion_candidates,
    select_navigation_completion,
)


class StatusBar(Horizontal):
    can_focus = False
    can_focus_children = True
    translations = reactive(list)
    active_translation = reactive("")
    maximized_translation = reactive("")
    strongs = reactive(False)
    live = reactive(False)
    live_connected = reactive(False)
    live_connecting = reactive(False)
    live_clients = reactive(0)
    listening = reactive(False)
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
            yield Button("Listen History", id="action-listen-history")
            yield Button("Transcripts", id="action-transcripts")
            yield Button("Translations", id="action-translations")
            yield Button("Strongs", id="action-strongs")
            yield Button("Config", id="action-config")
            yield Button("Live", id="action-live")
            yield Button("Listen", id="action-listening")

    def watch_translations(self):
        self._refresh()

    def watch_active_translation(self):
        self._refresh()

    def watch_maximized_translation(self):
        self._refresh()

    def watch_strongs(self):
        self._refresh()

    def watch_live(self):
        self._refresh()

    def watch_live_connected(self):
        self._refresh()

    def watch_live_connecting(self):
        self._refresh()

    def watch_live_clients(self):
        self._refresh()

    def watch_listening(self):
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
        self.compact = running_in_browser() and event.size.width < 72

    def _refresh(self):
        if self.translations:
            translations = []
            for slug in self.translations:
                if slug == self.active_translation:
                    translations.append(f"[#d97706]{slug}*[/]")
                else:
                    translations.append(f"[#9a5504]{slug}[/]")

            translation_text = " [#b8b0a6]·[/] ".join(translations)
        else:
            translation_text = "No translation selected"

        live_text = None
        if self.live:
            if self.live_connected:
                live_text = f"[#d97706]LIVE ({self.live_clients})[/]"
            elif self.live_connecting:
                live_text = "[#9a5504]CONNECTING...[/]"
            else:
                live_text = "[#9a5504]DISCONNECTED[/]"

        left = " [#b8b0a6]·[/] ".join(
            filter(
                None,
                [
                    "[bold]bibleit[/]",
                    translation_text,
                    "[#d97706]STRONGS[/]" if self.strongs else None,
                    "[#d97706]LISTENING[/]" if self.listening else None,
                    live_text,
                ],
            )
        )

        self.query_one("#status-left", Static).update(left)

        strongs_button = self.query_one("#action-strongs", Button)
        config_button = self.query_one("#action-config", Button)
        live_button = self.query_one("#action-live", Button)
        listening_button = self.query_one("#action-listening", Button)
        listen_history_button = self.query_one("#action-listen-history", Button)
        transcripts_button = self.query_one("#action-transcripts", Button)
        strongs_button.set_class(self.strongs, "active")
        config_button.display = not running_in_browser()
        live_button.set_class(self.live, "active")
        live_button.disabled = running_in_browser()
        listening_button.display = not running_in_browser()
        listening_button.set_class(self.listening, "active")
        listen_history_button.display = not running_in_browser()
        transcripts_button.display = not running_in_browser()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        from bibleit.ui.bible_view import BibleView

        bible_view = self.app.query_exactly_one(BibleView)

        actions = {
            "action-menu": self.action_toggle_menu,
            "action-find": bible_view.action_open_find,
            "action-history": bible_view.action_toggle_history,
            "action-listen-history": bible_view.action_toggle_listen_history,
            "action-transcripts": bible_view.action_toggle_transcripts,
            "action-translations": bible_view.action_open_translations,
            "action-strongs": bible_view.action_toggle_strongs,
            "action-config": bible_view.action_open_config,
            "action-live": bible_view.action_toggle_live,
            "action-listening": bible_view.action_toggle_listening,
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
        from bibleit.ui.bible_view import BibleView

        self.command_mode = False
        self.completions_open = False
        self._completion_matches = []
        self._completion_index = 0
        self.query_one("#status-command", Input).value = ""
        self.query_one("#status-command-completions", Static).update("")
        self.app.query_exactly_one(BibleView).focus()

    def _active_translation(self) -> translation.Translation | None:
        from bibleit.ui.bible_view import BibleView

        bible_view = self.app.query_exactly_one(BibleView)
        view = bible_view._active_view()
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
        from bibleit.ui.bible_view import BibleView

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
