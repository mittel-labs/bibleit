from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

from bibleit import live_payload, reader, translation
from bibleit.navigation import (
    NavigationState,
    book_name_for,
    next_chapter_ref,
    parse_navigation_ref,
    previous_chapter_ref,
)

DEFAULT_BEFORE = 12
DEFAULT_TOTAL = 40
MAX_TOTAL = 400


class OperatorError(Exception):
    """A command the operator could not carry out, reportable to the client."""


class PublishTarget(Protocol):
    name: str

    async def publish(self, payload: dict) -> None: ...

    async def set_live(self, live: bool) -> None: ...


class HubTarget:
    name = "local"

    def __init__(self, hub):
        self.hub = hub

    async def publish(self, payload: dict) -> None:
        await self.hub.publish(payload)

    async def set_live(self, live: bool) -> None:
        await self.hub.set_live(live)

    def viewers(self) -> int:
        return self.hub.client_count()


class RelayTarget:
    name = "relay"

    def __init__(self, publisher):
        self.publisher = publisher

    async def publish(self, payload: dict) -> None:
        await self.publisher.publish_payload(payload)

    async def set_live(self, live: bool) -> None:
        await self.publisher.set_live(live)


class OperatorSession:
    def __init__(self, *, targets=(), before: int = DEFAULT_BEFORE, total: int = DEFAULT_TOTAL):
        self.state = NavigationState()
        self.translations: list[translation.Translation] = []
        self.active_slug: str | None = None
        self.targets: list[PublishTarget] = list(targets)
        self.publisher_id = uuid.uuid4().hex
        self.sequence = 0
        self.before = before
        self.total = total
        self.viewers = 0
        self.connected = False
        self.strongs = False
        self._listeners: set[asyncio.Queue] = set()

    # -- translations -------------------------------------------------------

    def find(self, slug: str) -> translation.Translation | None:
        for opened in self.translations:
            if opened.slug == slug:
                return opened

        return None

    def active(self) -> translation.Translation | None:
        return self.find(self.active_slug or "") or (self.translations[0] if self.translations else None)

    def require_active(self) -> translation.Translation:
        active = self.active()

        if active is None:
            raise OperatorError("Open a translation first")

        return active

    async def open_translation(self, slug: str) -> None:
        if self.find(slug) is not None:
            return

        loop = asyncio.get_running_loop()

        try:
            opened = await loop.run_in_executor(None, translation.open, slug)
        except (RuntimeError, ValueError) as error:
            raise OperatorError(str(error)) from error

        was_empty = not self.translations
        self.translations.append(opened)

        if self.active_slug is None:
            self.active_slug = opened.slug

        if was_empty:
            self._align_state(opened)

        await self.publish()
        await self.notify_state()

    async def close_translation(self, slug: str) -> None:
        opened = self.find(slug)

        if opened is None:
            return

        self.translations.remove(opened)

        try:
            opened.close()
        except Exception:
            pass

        if self.active_slug == slug:
            self.active_slug = self.translations[0].slug if self.translations else None

        await self.publish()
        await self.notify_state()

    async def set_active(self, slug: str) -> None:
        if self.find(slug) is None:
            raise OperatorError(f"Translation not open: {slug}")

        self.active_slug = slug
        await self.notify_state()

    def _align_state(self, opened: translation.Translation) -> None:
        """Move to the first verse a translation actually has, for the first one opened.

        Adding a translation alongside others leaves the shared reference alone,
        the way the TUI does, so opening a second translation cannot move the
        verse the audience is looking at.
        """
        if reader.verse_line(opened, self.current_ref()) is not None:
            return

        books = reader.books(opened)

        if not books:
            return

        self.state.bookid = books[0].bookid
        self.state.chapter = 1
        self.state.verse = 1
        self.state.index = 0

    # -- navigation --------------------------------------------------------

    def current_ref(self) -> translation.TranslationRef:
        return translation.TranslationRef(self.state.bookid, self.state.chapter, self.state.verse)

    def _translation_with_ref(self, ref: translation.TranslationRef) -> translation.Translation | None:
        ordered = [self.active(), *self.translations]

        for candidate in ordered:
            if candidate is not None and reader.verse_line(candidate, ref) is not None:
                return candidate

        return None

    async def goto(self, value: str) -> None:
        active = self.require_active()

        try:
            ref = parse_navigation_ref(value, active, self.state)
        except ValueError as error:
            raise OperatorError(str(error)) from error

        target = self._translation_with_ref(ref)

        if target is None:
            raise OperatorError(f"Reference not found: {value}")

        self.active_slug = target.slug
        await self.goto_ref(ref, history=True)

    async def goto_ref(self, ref: translation.TranslationRef, *, history: bool = False) -> None:
        self.state.bookid = ref.bookid
        self.state.chapter = ref.chapter or 1
        self.state.verse = ref.verse_start or 1
        self.state.index = 0
        await self.publish(history=history)
        await self.notify_state()

    async def _step(self, row: reader.RowRef | None) -> None:
        if row is None:
            return

        await self.goto_ref(translation.TranslationRef(row.bookid, row.chapter, row.verse))

    async def next_verse(self) -> None:
        await self._step(reader.next_ref(self.require_active(), self.current_ref()))

    async def previous_verse(self) -> None:
        await self._step(reader.previous_ref(self.require_active(), self.current_ref()))

    async def chapter_start(self) -> None:
        self.require_active()
        await self.goto_ref(translation.TranslationRef(self.state.bookid, self.state.chapter, 1))

    async def chapter_end(self) -> None:
        active = self.require_active()
        ref = reader.chapter_last_ref(active, self.state.bookid, self.state.chapter)

        if ref is None:
            raise OperatorError("Chapter end not found")

        await self.goto_ref(ref)

    async def next_chapter(self) -> None:
        ref = next_chapter_ref(self.require_active(), self.state)

        if ref is not None:
            await self.goto_ref(ref)

    async def previous_chapter(self) -> None:
        ref = previous_chapter_ref(self.require_active(), self.state)

        if ref is not None:
            await self.goto_ref(ref)

    # -- live --------------------------------------------------------------

    async def set_live(self, live: bool) -> None:
        self.state.live = bool(live)

        for target in self.targets:
            await target.set_live(self.state.live)

        if self.state.live:
            await self.publish()

        self.refresh_viewers()
        await self.notify_state()

    async def publish(self, *, history: bool = False) -> dict | None:
        if not self.state.live or not self.translations:
            return None

        ref = self.current_ref()
        values = []

        for opened in self.translations:
            line = reader.verse_line(opened, ref)

            if line is not None:
                values.append((opened.slug, line))

        payload = live_payload.bundle_payload(
            values,
            publisher_id=self.publisher_id,
            sequence=self.sequence + 1,
        )

        if payload is None:
            return None

        self.sequence += 1

        if history:
            payload["history"] = True

        for target in self.targets:
            await target.publish(payload)

        return payload

    def refresh_viewers(self) -> None:
        for target in self.targets:
            counter = getattr(target, "viewers", None)

            if counter is not None:
                self.viewers = counter()
                self.connected = True
                return

    def set_status(self, *, connected: bool, viewers: int) -> None:
        self.connected = connected
        self.viewers = viewers

    async def set_strongs(self, show: bool) -> None:
        self.strongs = bool(show)
        await self.notify_state()

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> dict:
        active = self.active()

        return {
            "translations": [{"slug": opened.slug, "name": opened.header.name} for opened in self.translations],
            "active": active.slug if active is not None else None,
            "ref": self.reference_payload(),
            "live": self.state.live,
            "viewers": self.viewers,
            "connected": self.connected,
            "strongs": self.strongs,
            "targets": [target.name for target in self.targets],
        }

    def reference_payload(self) -> dict:
        active = self.active()
        book = book_name_for(active, self.state.bookid) if active is not None else ""

        return {
            "bookid": self.state.bookid,
            "chapter": self.state.chapter,
            "verse": self.state.verse,
            "book": book,
            "reference": f"{book} {self.state.chapter}:{self.state.verse}".strip(),
        }

    def verses(self, *, before: int | None = None, total: int | None = None) -> dict:
        before = self.before if before is None else max(0, before)
        total = self.total if total is None else max(1, min(total, MAX_TOTAL))
        ref = self.current_ref()

        return {
            "ref": self.reference_payload(),
            "columns": [self._column(opened, ref, before, total) for opened in self.translations],
        }

    def _column(self, opened: translation.Translation, ref, before: int, total: int) -> dict:
        window = reader.window_around(opened, ref, before=before, total=total)
        bookids: dict[str, int | None] = {}
        rows = []

        for line in window.lines:
            row = self._row(opened, line, bookids)

            if row is not None:
                rows.append(row)

        return {
            "translation": opened.slug,
            "name": opened.header.name,
            "index": window.index,
            "rows": rows,
        }

    def _row(self, opened: translation.Translation, line: str, bookids: dict[str, int | None]) -> dict | None:
        parsed = reader.parse_line(line)

        if parsed is None:
            return None

        if parsed.book not in bookids:
            bookids[parsed.book] = opened.resolve_bookid(parsed.book)

        return {
            "bookid": bookids[parsed.book],
            "book": parsed.book,
            "chapter": parsed.chapter,
            "verse": parsed.verse,
            "reference": parsed.reference,
            "html": reader.render_html(parsed.text),
            "text": reader.clean_verse_text(parsed.text),
        }

    # -- events ------------------------------------------------------------

    def listen(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def forget(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    async def notify(self, event: dict) -> None:
        for queue in list(self._listeners):
            queue.put_nowait(event)

    async def notify_state(self) -> None:
        await self.notify({"type": "state", "state": self.snapshot()})

    # -- commands ----------------------------------------------------------

    async def command(self, name: str, params: dict | None = None) -> None:
        params = params or {}

        match name:
            case "goto":
                await self.goto(str(params.get("value", "")))
            case "goto_ref":
                await self.goto_ref(
                    translation.TranslationRef(
                        int(params["bookid"]),
                        int(params.get("chapter") or 1),
                        int(params.get("verse") or 1),
                    ),
                    history=bool(params.get("history")),
                )
            case "next_verse":
                await self.next_verse()
            case "previous_verse":
                await self.previous_verse()
            case "next_chapter":
                await self.next_chapter()
            case "previous_chapter":
                await self.previous_chapter()
            case "chapter_start":
                await self.chapter_start()
            case "chapter_end":
                await self.chapter_end()
            case "open_translation":
                await self.open_translation(str(params.get("slug", "")))
            case "close_translation":
                await self.close_translation(str(params.get("slug", "")))
            case "set_active":
                await self.set_active(str(params.get("slug", "")))
            case "set_live":
                await self.set_live(bool(params.get("live")))
            case "set_strongs":
                await self.set_strongs(bool(params.get("strongs")))
            case _:
                raise OperatorError(f"Unknown command: {name}")

    async def close(self) -> None:
        for opened in self.translations:
            try:
                opened.close()
            except Exception:
                pass

        self.translations.clear()
        self.active_slug = None
