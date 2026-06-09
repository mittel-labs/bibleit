from __future__ import annotations

from textual import events
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Label

from bibleit.shortcuts import SHORTCUTS as SHORTCUT_ROWS
from bibleit.ui.screens.overlay import OverlayStatusMixin
from bibleit.ui.status import StatusBar


class ShortcutsScreen(OverlayStatusMixin, Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        ("?", "app.pop_screen", "Close"),
    ]

    SHORTCUTS = SHORTCUT_ROWS

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
