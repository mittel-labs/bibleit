from __future__ import annotations

from textual import events
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Label

from bibleit.shortcuts import WELCOME_SHORTCUTS
from bibleit.ui.screens.overlay import OverlayStatusMixin
from bibleit.ui.status import StatusBar


class WelcomeScreen(OverlayStatusMixin, Screen):
    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.pop_screen()

    def on_key(self, event: events.Key) -> None:
        from bibleit.ui.bible_view import BibleView

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
            "@": lambda view: view.action_open_reference(),
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
            for key, description in WELCOME_SHORTCUTS:
                with Horizontal(classes="welcome-row"):
                    yield Label(key, classes="welcome-key")
                    yield Label(description, classes="welcome-row-description")
        yield StatusBar()
