from __future__ import annotations

import asyncio

from textual import events
from textual.containers import Horizontal
from textual.widgets import Button

from bibleit import translation
from bibleit.live_publisher import running_in_browser
from bibleit.navigation import (
    NavigationState,
    next_chapter_ref,
    parse_navigation_ref,
    previous_chapter_ref,
)
from bibleit.panes import PaneRegistry
from bibleit.shortcuts import BIBLE_VIEW_BINDINGS
from bibleit.ui.status import StatusBar
from bibleit.ui.view import View
from bibleit.ui.screens.config import ConfigScreen
from bibleit.ui.screens.find import Find
from bibleit.ui.screens.history import HistoryScreen
from bibleit.ui.screens.shortcuts import ShortcutsScreen
from bibleit.ui.screens.translations import Translations


class BibleView(Horizontal):
    can_focus = True

    BINDINGS = BIBLE_VIEW_BINDINGS

    def __init__(self):
        super().__init__()
        self.state = NavigationState()
        self.panes: PaneRegistry[View] = PaneRegistry()
        self.vertical_layout = False
        self.live_connected = False
        self.live_connecting = False
        self.live_clients = 0

    @property
    def views(self) -> list[View]:
        return self.panes.views

    @property
    def active_view(self) -> View | None:
        return self.panes.active_view

    @active_view.setter
    def active_view(self, view: View | None) -> None:
        self.panes.active_view = view

    @property
    def maximized_view(self) -> View | None:
        return self.panes.maximized_view

    @maximized_view.setter
    def maximized_view(self, view: View | None) -> None:
        self.panes.maximized_view = view

    def compose(self):
        yield Button("↑", id="nav-previous", classes="verse-nav")
        yield Button("↓", id="nav-next", classes="verse-nav")

    async def add_translation(
        self,
        translation: translation.Translation,
    ) -> None:
        focus_view = self._active_view()
        was_empty = not self.views
        view = View(self.state, translation)
        self.panes.add(view)

        if focus_view is not None:
            self.panes.set_active(focus_view)

        await self.mount(view)
        if self.maximized_view is not None:
            view.display = False

        view.sync_to_state(focus=was_empty)
        if focus_view is not None:
            self.call_after_refresh(focus_view.focus)

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
        self.set_active_view(view)

        for other in self.views:
            if other is view:
                continue

            if not other.is_attached:
                continue

            other.sync_to_state()

        self.publish_live_state()

    def go_to_ref(
        self,
        ref: translation.TranslationRef,
        *,
        live_history: bool = False,
    ) -> None:
        self.state.bookid = ref.bookid
        self.state.chapter = ref.chapter or 1
        self.state.verse = ref.verse_start or 1
        self.state.index = 0

        focused_view = self._active_view()
        for view in self.views:
            view.sync_to_state(focus=view is focused_view)

        self.publish_live_state(history=live_history)

    def action_open_reference(self) -> None:
        if not self.views:
            self.notify(
                "Please open a translation first",
                severity="warning",
            )
            return
        self.app.query_exactly_one(StatusBar).open_command()

    def go_to_command(self, value: str) -> bool:
        view = self._active_view()
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

        self.go_to_ref(ref, live_history=True)
        self.app.record_history(view.translation, ref)
        return True

    def on_mount(self):
        self.app.install_screen(Translations(), name="translations")
        self.set_class(running_in_browser(), "browser")
        self.focus()

    def on_focus(self, event: events.Focus) -> None:
        view = self._active_view()
        if view:
            event.stop()
            self.call_after_refresh(view.focus)

    def action_focus_active_view(self) -> None:
        view = self._active_view()
        if view:
            view.focus()

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
        view = self._active_view()

        if view:
            await view._move_cursor_up()

    async def action_next_verse(self):
        view = self._active_view()

        if view:
            await view._move_cursor_down()

    def _active_view(self) -> View | None:
        return self.panes.active(self.focused_view())

    def _has_view(self, view: View | None) -> bool:
        return self.panes.has(view)

    def set_active_view(self, view: View | None) -> None:
        if not self.panes.set_active(view):
            return

        self.refresh_status()

    def _set_maximized_view(self, view: View | None) -> None:
        self.panes.set_maximized(view)

        for candidate in self.views:
            candidate.display = self.maximized_view is None or candidate is self.maximized_view

        self.set_class(self.maximized_view is not None, "maximized")
        self.refresh_status()

        active_view = self.panes.active()
        if active_view is not None:
            self.call_after_refresh(active_view.focus)

    def action_toggle_maximize(self):
        view = self._active_view()
        if view is None:
            return

        self._set_maximized_view(None if self.maximized_view is view else view)

    def _translation_index(self) -> int | None:
        return self.panes.index(self._active_view())

    def _switch_translation(self, direction: int) -> None:
        view = self.panes.cycle(direction, self.focused_view())
        if view is None:
            return

        if self.maximized_view is not None:
            self._set_maximized_view(view)
        else:
            self.set_active_view(view)
            self.call_after_refresh(view.focus)

    def action_next_translation(self):
        self._switch_translation(1)

    def action_previous_translation(self):
        self._switch_translation(-1)

    def action_next_maximized_translation(self):
        if self.maximized_view is not None:
            self.action_next_translation()

    def action_maximize_translation(self, number: int):
        if self.maximized_view is None:
            return

        view = self.panes.by_number(number)
        if view is None:
            return

        self._set_maximized_view(view)

    def action_restore_panes(self):
        if self.maximized_view is not None:
            self._set_maximized_view(None)

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
        view = self._active_view()
        if not view:
            return

        view.action_toggle_strongs()

    def action_toggle_live(self):
        if running_in_browser():
            return

        self.state.live = not self.state.live
        if self.state.live:
            self.live_connected = False
            self.live_connecting = True
            self.live_clients = 0
            self._start_live_status_worker()
        else:
            self.live_connected = False
            self.live_connecting = False
            self.live_clients = 0
        self.refresh_status()

        if self.state.live:
            view = self._active_view()

            if view:
                view.set_live_mode(True)
                self.publish_live_state()
        else:
            view = self._active_view()

            if view:
                view.set_live_mode(False)

    def _start_live_status_worker(self) -> None:
        self.run_worker(
            self._watch_live_status(),
            exclusive=True,
            group=f"live-status-{id(self)}",
            exit_on_error=False,
        )

    async def _watch_live_status(self) -> None:
        if not self.views:
            return

        was_connected = False

        while self.state.live:
            self.live_connected = False
            self.live_connecting = True
            self.live_clients = 0

            if self.is_attached:
                self.refresh_status()

            async for status in self.views[0].live.status_events():
                if not self.state.live:
                    break

                connected = bool(status.get("connected"))
                self.live_connected = connected
                self.live_connecting = not connected
                self.live_clients = int(status.get("clients") or 0)

                if connected and not was_connected:
                    await self._restore_remote_live_state()

                was_connected = connected

                if self.is_attached:
                    self.refresh_status()

            was_connected = False

            if self.state.live:
                self.live_connected = False
                self.live_connecting = True
                self.live_clients = 0

                if self.is_attached:
                    self.refresh_status()

                await asyncio.sleep(3)

        self.live_connected = False
        self.live_connecting = False
        self.live_clients = 0

    async def _restore_remote_live_state(self) -> None:
        if not self.state.live or not self.views:
            return

        await self.views[0].live.set_live(True)
        self.publish_live_state()

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

        self.live_connected = False
        self.live_connecting = False
        self.live_clients = 0

        if self.is_attached:
            self.refresh_status()

    def refresh_status(self):
        status = self.app.query_exactly_one(StatusBar)
        active_view = self._active_view()
        status.translations = [view.translation.slug for view in self.views]
        status.active_translation = active_view.translation.slug if active_view is not None else ""
        status.maximized_translation = (
            self.maximized_view.translation.slug
            if self.maximized_view is not None
            else ""
        )
        status.live = self.state.live
        status.live_connected = self.live_connected
        status.live_connecting = self.live_connecting
        status.live_clients = self.live_clients

    def publish_live_state(self, *, history: bool = False):
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
            if history:
                payload["history"] = True
            self.views[0]._publish_payload(payload)

    async def action_close_pane(self):
        view = self.focused_view()
        if not view:
            return

        if len(self.views) <= 1:
            return

        index = self.views.index(view)
        self.panes.remove(view)
        await view.remove()
        self._set_maximized_view(self.maximized_view)
        self.refresh_status()

        next_view = self.active_view or self.views[min(index, len(self.views) - 1)]
        if next_view is not None:
            next_view.focus()
            next_view.sync_to_state(focus=True)

        if self.state.live:
            self.publish_live_state()

    def focused_view(self) -> View | None:
        focused = self.app.focused

        while focused and not isinstance(focused, View):
            focused = focused.parent

        return focused
