from __future__ import annotations

import atexit

from textual import events
from textual.app import App
from textual.containers import Horizontal

from bibleit import translation
from bibleit.config import config_value, save_config, theme_is_dark
from bibleit.history import HistoryEntry, SessionHistory
from bibleit.live_publisher import LivePublisher, running_in_browser
from bibleit.navigation import NavigationState, RowRef, verse_reference_label
from bibleit.ui.bible_view import BibleView
from bibleit.ui.screens.config import ConfigScreen
from bibleit.ui.screens.history import HistoryScreen
from bibleit.ui.screens.shortcuts import ShortcutsScreen
from bibleit.ui.screens.strongs import StrongScreen
from bibleit.ui.screens.welcome import WelcomeScreen
from bibleit.ui.status import StatusBar
from bibleit.ui.view import View


__all__ = [
    "BibleView",
    "Bibleit",
    "ConfigScreen",
    "HistoryEntry",
    "HistoryScreen",
    "LivePublisher",
    "NavigationState",
    "RowRef",
    "SessionHistory",
    "ShortcutsScreen",
    "StatusBar",
    "StrongScreen",
    "View",
    "WelcomeScreen",
    "running_in_browser",
]


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

    async def on_mount(self) -> None:
        self.apply_theme(self.dark_theme)
        await self._open_default_translation()
        self.push_screen(WelcomeScreen())

    async def _open_default_translation(self) -> None:
        slug = config_value("DEFAULT_TRANSLATION").strip()
        if not slug:
            return

        bible_view = self.query_exactly_one(BibleView)
        try:
            translation_ = translation.open(slug)
        except (RuntimeError, ValueError) as error:
            self.notify(str(error), severity="warning", timeout=3)
            return

        await bible_view.add_translation(translation_)

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
