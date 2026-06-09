from __future__ import annotations

import asyncio
import re
from typing import Iterable

from textual import events
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from bibleit import translation
from bibleit.live_publisher import LivePublisher, running_in_browser
from bibleit.navigation import NavigationState, RowRef
from bibleit.ui.screens.translations import Translations


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
        self._cursor_move_lock = asyncio.Lock()

    def _select_first(self):
        if self.children:
            self.focus()
            self.index = 0
            self.publish_current()

    def on_focus(self, event: events.Focus) -> None:
        self._activate_parent_view()

    def _activate_parent_view(self) -> None:
        if not self.is_attached:
            return

        from bibleit.ui.bible_view import BibleView

        try:
            self.app.query_exactly_one(BibleView).set_active_view(self)
        except Exception:
            return

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
            self._activate_parent_view()

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
            self._activate_parent_view()

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

    async def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not running_in_browser():
            self.focus()
        self._activate_parent_view()

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        event.stop()

        if not running_in_browser():
            self.focus()

        self._activate_parent_view()

        try:
            self.index = self._nodes.index(event.item)
        except ValueError:
            return

        self.post_message(self.Selected(self, event.item, self.index))

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
        from bibleit.ui.status import StatusBar

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
