from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from contextlib import suppress
from dataclasses import replace
from functools import wraps

from bibleit import live_payload, reader, translation
from bibleit.navigation import (
    NavigationState,
    book_name_for,
    next_chapter_ref,
    parse_navigation_ref,
    previous_chapter_ref,
)
from bibleit.operator.errors import OperatorError, PublishError
from bibleit.operator.models import (
    ChapterEnd,
    ChapterStart,
    CloseTranslation,
    Goto,
    GotoReference,
    NextChapter,
    NextVerse,
    OpenTranslation,
    OperatorCommand,
    OperatorEvent,
    OperatorState,
    PreviousChapter,
    PreviousVerse,
    Reference,
    SetActive,
    SetLive,
    SetStrongs,
    StateEvent,
    TranslationInfo,
    VerseColumn,
    VerseRow,
    VerseWindow,
    parse_command,
)
from bibleit.operator.ports import OpenedTranslation, PublishTarget

DEFAULT_BEFORE = 12
DEFAULT_TOTAL = 40
MAX_TOTAL = 400


class _MutationLock:
    """An asyncio lock that permits nested public session calls in one task."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._depth = 0

    async def __aenter__(self) -> _MutationLock:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("OperatorSession mutations require an asyncio task")
        if self._owner is task:
            self._depth += 1
            return self
        await self._lock.acquire()
        self._owner = task
        self._depth = 1
        return self

    async def __aexit__(self, *_exc) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


def _serialized(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self._mutations:
            return await method(self, *args, **kwargs)

    return wrapped


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
        if not await self.publisher.publish_payload(payload):
            raise PublishError("The relay rejected the verse payload")

    async def set_live(self, live: bool) -> None:
        if not await self.publisher.set_live(live):
            raise PublishError("The relay rejected the live-state change")


class EventSubscription(AsyncIterator[OperatorEvent]):
    """Framework-neutral event subscription owned by its consumer."""

    def __init__(self, session: OperatorSession, queue: asyncio.Queue[OperatorEvent]):
        self._session = session
        self._queue = queue
        self._closed = False
        self._close_sentinel = object()

    def __aiter__(self) -> EventSubscription:
        return self

    async def __anext__(self) -> OperatorEvent:
        if self._closed:
            raise StopAsyncIteration
        event = await self._queue.get()
        if event is self._close_sentinel:
            raise StopAsyncIteration
        return event

    async def get(self) -> OperatorEvent:
        return await self.__anext__()

    def get_nowait(self) -> OperatorEvent:
        event = self._queue.get_nowait()
        if event is self._close_sentinel:
            raise StopAsyncIteration
        return event

    def empty(self) -> bool:
        return self._closed or self._queue.empty()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._session.unsubscribe(self)
            if self._queue.full():
                self._queue.get_nowait()
            self._queue.put_nowait(self._close_sentinel)

    async def __aenter__(self) -> EventSubscription:
        return self

    async def __aexit__(self, *_exc) -> None:
        self.close()


class OperatorSession:
    """Shared operator state and publishing, with no web-framework dependency."""

    def __init__(
        self,
        *,
        targets=(),
        before: int = DEFAULT_BEFORE,
        total: int = DEFAULT_TOTAL,
        opener: Callable[[str], Awaitable[OpenedTranslation]] | None = None,
    ):
        self.state = NavigationState()
        self.translations: list[OpenedTranslation] = []
        self.active_slug: str | None = None
        self.targets: list[PublishTarget] = list(targets)
        self.publisher_id = uuid.uuid4().hex
        self.sequence = 0
        self._last_payload: dict | None = None
        self.before = before
        self.total = total
        self.viewer_counts: dict[str, int] = {}
        self.connected = any(isinstance(target, HubTarget) for target in self.targets)
        self.strongs = False
        self._subscriptions: set[EventSubscription] = set()
        self._opener = opener
        self._mutations = _MutationLock()

    def find(self, slug: str) -> OpenedTranslation | None:
        return next((opened for opened in self.translations if opened.slug == slug), None)

    def active(self) -> OpenedTranslation | None:
        return self.find(self.active_slug or "") or (self.translations[0] if self.translations else None)

    def require_active(self) -> OpenedTranslation:
        active = self.active()
        if active is None:
            raise OperatorError("Open a translation first")
        return active

    @_serialized
    async def add_translation(self, opened: OpenedTranslation) -> None:
        if self.find(opened.slug) is not None:
            with suppress(Exception):
                opened.close()
            return
        previous = (list(self.translations), self.active_slug, replace(self.state), self.sequence)
        self.translations.append(opened)
        if self.active_slug is None:
            self.active_slug = opened.slug
        if len(self.translations) == 1:
            self._align_state(opened)
        try:
            await self.publish()
        except Exception as error:
            self.translations, self.active_slug, self.state, self.sequence = previous
            if isinstance(error, PublishError) and error.committed_sequence is not None:
                self.sequence = error.committed_sequence
            with suppress(Exception):
                opened.close()
            raise
        await self.notify_state()

    @_serialized
    async def open_translation(self, slug: str) -> None:
        """Compatibility helper; new applications should open through OperatorService."""
        if self.find(slug) is not None:
            return
        try:
            opened = await self._opener(slug) if self._opener else await asyncio.to_thread(translation.open, slug)
        except (RuntimeError, ValueError) as error:
            raise OperatorError(str(error)) from error
        await self.add_translation(opened)

    @_serialized
    async def close_translation(self, slug: str) -> None:
        opened = self.find(slug)
        if opened is None:
            return
        previous = (list(self.translations), self.active_slug, self.sequence)
        self.translations.remove(opened)
        if self.active_slug == slug:
            self.active_slug = self.translations[0].slug if self.translations else None
        try:
            await self.publish()
        except Exception as error:
            self.translations, self.active_slug, self.sequence = previous
            if isinstance(error, PublishError) and error.committed_sequence is not None:
                self.sequence = error.committed_sequence
            raise
        with suppress(Exception):
            opened.close()
        await self.notify_state()

    @_serialized
    async def set_active(self, slug: str) -> None:
        if self.find(slug) is None:
            raise OperatorError(f"Translation not open: {slug}")
        self.active_slug = slug
        await self.notify_state()

    def _align_state(self, opened: OpenedTranslation) -> None:
        if reader.verse_line(opened, self.current_ref()) is not None:
            return
        books = reader.books(opened)
        if books:
            self.state.bookid = books[0].bookid
            self.state.chapter = self.state.verse = 1
            self.state.index = 0

    def current_ref(self) -> translation.TranslationRef:
        return translation.TranslationRef(self.state.bookid, self.state.chapter, self.state.verse)

    def _translation_with_ref(self, ref: translation.TranslationRef) -> OpenedTranslation | None:
        for candidate in [self.active(), *self.translations]:
            if candidate is not None and reader.verse_line(candidate, ref) is not None:
                return candidate
        return None

    @_serialized
    async def goto(self, value: str) -> None:
        active = self.require_active()
        try:
            ref = parse_navigation_ref(value, active, self.state)
        except ValueError as error:
            raise OperatorError(str(error)) from error
        target = self._translation_with_ref(ref)
        if target is None:
            raise OperatorError(f"Reference not found: {value}")
        old_active = self.active_slug
        self.active_slug = target.slug
        try:
            await self.goto_ref(ref, history=True)
        except Exception:
            self.active_slug = old_active
            raise

    @_serialized
    async def goto_ref(self, ref: translation.TranslationRef, *, history: bool = False) -> None:
        ref = translation.TranslationRef(ref.bookid, ref.chapter or 1, ref.verse_start or 1)
        if self._translation_with_ref(ref) is None:
            raise OperatorError(f"Reference not found: {ref.bookid} {ref.chapter}:{ref.verse_start}")
        previous = (replace(self.state), self.sequence)
        self.state.bookid = ref.bookid
        self.state.chapter = ref.chapter or 1
        self.state.verse = ref.verse_start or 1
        self.state.index = 0
        try:
            await self.publish(history=history)
        except Exception as error:
            self.state, self.sequence = previous
            if isinstance(error, PublishError) and error.committed_sequence is not None:
                self.sequence = error.committed_sequence
            raise
        await self.notify_state()

    async def _step(self, row: reader.RowRef | None) -> None:
        if row is not None:
            await self.goto_ref(translation.TranslationRef(row.bookid, row.chapter, row.verse))

    @_serialized
    async def next_verse(self) -> None:
        await self._step(reader.next_ref(self.require_active(), self.current_ref()))

    @_serialized
    async def previous_verse(self) -> None:
        await self._step(reader.previous_ref(self.require_active(), self.current_ref()))

    @_serialized
    async def chapter_start(self) -> None:
        self.require_active()
        await self.goto_ref(translation.TranslationRef(self.state.bookid, self.state.chapter, 1))

    @_serialized
    async def chapter_end(self) -> None:
        ref = reader.chapter_last_ref(self.require_active(), self.state.bookid, self.state.chapter)
        if ref is None:
            raise OperatorError("Chapter end not found")
        await self.goto_ref(ref)

    @_serialized
    async def next_chapter(self) -> None:
        ref = next_chapter_ref(self.require_active(), self.state)
        if ref is not None:
            await self.goto_ref(ref)

    @_serialized
    async def previous_chapter(self) -> None:
        ref = previous_chapter_ref(self.require_active(), self.state)
        if ref is not None:
            await self.goto_ref(ref)

    @_serialized
    async def set_live(self, live: bool) -> None:
        live = bool(live)
        if live:
            self.require_active()
        previous_live, previous_sequence = self.state.live, self.sequence
        changed = []
        try:
            for target in self.targets:
                await target.set_live(live)
                changed.append(target)
            self.state.live = live
            if live:
                await self.publish()
        except Exception as error:
            self.state.live, self.sequence = previous_live, previous_sequence
            if isinstance(error, PublishError) and error.committed_sequence is not None:
                self.sequence = error.committed_sequence
            for target in reversed(changed):
                with suppress(Exception):
                    await target.set_live(previous_live)
            if isinstance(error, OperatorError):
                raise
            raise PublishError(f"Could not change live state: {error}") from error
        self.refresh_viewers()
        await self.notify_state()

    @_serialized
    async def publish(self, *, history: bool = False) -> dict | None:
        if not self.state.live or not self.translations:
            return None
        values = []
        for opened in self.translations:
            line = reader.verse_line(opened, self.current_ref())
            if line is not None:
                values.append((opened.slug, line))
        next_sequence = self.sequence + 1
        payload = live_payload.bundle_payload(values, publisher_id=self.publisher_id, sequence=next_sequence)
        if payload is None:
            return None
        if history:
            payload["history"] = True
        delivered = []
        try:
            for target in self.targets:
                await target.publish(payload)
                delivered.append(target)
        except Exception as error:
            committed_sequence = await self._compensate(delivered, next_sequence)
            message = f"Could not publish verse: {error}"
            raise PublishError(message, committed_sequence=committed_sequence) from error
        self.sequence = next_sequence
        self._last_payload = payload
        return payload

    async def _compensate(self, delivered: list[PublishTarget], failed_sequence: int) -> int | None:
        """Restore targets that received a payload which was not delivered everywhere."""
        if not delivered:
            return None
        if self._last_payload is None:
            for target in delivered:
                with suppress(Exception):
                    await target.set_live(False)
            return failed_sequence

        compensation_sequence = failed_sequence + 1
        payload = deepcopy(self._last_payload)
        payload["sequence"] = compensation_sequence
        payload.pop("history", None)
        failed = []
        for target in delivered:
            try:
                await target.publish(payload)
            except Exception as error:
                failed.append(f"{target.name}: {error}")
        self.sequence = compensation_sequence
        self._last_payload = payload
        if failed:
            raise PublishError(
                f"Could not compensate published targets ({'; '.join(failed)})",
                committed_sequence=compensation_sequence,
            )
        return compensation_sequence

    @property
    def viewers(self) -> int:
        return sum(self.viewer_counts.values())

    def set_viewers(self, name: str, count: int) -> None:
        self.viewer_counts[name] = max(0, count)

    def refresh_viewers(self) -> None:
        for target in self.targets:
            counter = getattr(target, "viewers", None)
            if counter is not None:
                self.set_viewers(target.name, counter())
                self.connected = True

    @_serialized
    async def set_strongs(self, show: bool) -> None:
        self.strongs = bool(show)
        await self.notify_state()

    def reference(self) -> Reference:
        active = self.active()
        book = book_name_for(active, self.state.bookid) if active is not None else ""
        return Reference(self.state.bookid, self.state.chapter, self.state.verse, book)

    def state_model(self) -> OperatorState:
        active = self.active()
        return OperatorState(
            translations=tuple(TranslationInfo(item.slug, item.header.name) for item in self.translations),
            active=active.slug if active is not None else None,
            ref=self.reference(),
            live=self.state.live,
            viewers=self.viewers,
            viewer_counts=dict(self.viewer_counts),
            connected=self.connected,
            strongs=self.strongs,
            targets=tuple(target.name for target in self.targets),
            sequence=self.sequence,
        )

    def snapshot(self) -> dict:
        result = self.state_model().to_dict()
        for item in result["translations"]:
            item.pop("installed", None)
        result.pop("sequence", None)
        return result

    def reference_payload(self) -> dict:
        ref = self.reference()
        return {
            "bookid": ref.bookid,
            "chapter": ref.chapter,
            "verse": ref.verse,
            "book": ref.book,
            "reference": ref.label,
        }

    def verse_window(self, *, before: int | None = None, total: int | None = None) -> VerseWindow:
        before = self.before if before is None else max(0, before)
        total = self.total if total is None else max(1, min(total, MAX_TOTAL))
        ref = self.current_ref()
        return VerseWindow(
            self.reference(), tuple(self._column(item, ref, before, total) for item in self.translations)
        )

    def verses(self, *, before: int | None = None, total: int | None = None) -> dict:
        window = self.verse_window(before=before, total=total)
        return {
            "ref": self.reference_payload(),
            "columns": [
                {
                    "translation": column.translation,
                    "name": column.name,
                    "index": column.index,
                    "rows": [row.__dict__ for row in column.rows],
                }
                for column in window.columns
            ],
        }

    def _column(self, opened: OpenedTranslation, ref, before: int, total: int) -> VerseColumn:
        window = reader.window_around(opened, ref, before=before, total=total)
        bookids: dict[str, int | None] = {}
        rows = tuple(row for line in window.lines if (row := self._row(opened, line, bookids)) is not None)
        return VerseColumn(opened.slug, opened.header.name, window.index, rows)

    def _row(self, opened: OpenedTranslation, line: str, bookids: dict[str, int | None]) -> VerseRow | None:
        parsed = reader.parse_line(line)
        if parsed is None:
            return None
        if parsed.book not in bookids:
            bookids[parsed.book] = opened.resolve_bookid(parsed.book)
        bookid = bookids[parsed.book]
        return VerseRow(
            bookid,
            parsed.book,
            parsed.chapter,
            parsed.verse,
            parsed.reference,
            reader.render_html(parsed.text, prefix=reader.strong_prefix(bookid or 1)),
            reader.clean_verse_text(parsed.text),
        )

    def subscribe(self, *, max_events: int = 0) -> EventSubscription:
        subscription = EventSubscription(self, asyncio.Queue(maxsize=max_events))
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        self._subscriptions.discard(subscription)

    def listen(self) -> EventSubscription:
        """Compatibility alias for subscribe()."""
        return self.subscribe()

    def forget(self, subscription: EventSubscription) -> None:
        subscription.close()

    async def notify(self, event: OperatorEvent) -> None:
        for subscription in tuple(self._subscriptions):
            if subscription._queue.full():
                subscription._queue.get_nowait()
            subscription._queue.put_nowait(event)

    async def notify_state(self) -> None:
        await self.notify(StateEvent(self.state_model()))

    @_serialized
    async def execute(self, command: OperatorCommand) -> None:
        match command:
            case Goto(value):
                await self.goto(value)
            case GotoReference(bookid, chapter, verse, history):
                await self.goto_ref(translation.TranslationRef(bookid, chapter, verse), history=history)
            case NextVerse():
                await self.next_verse()
            case PreviousVerse():
                await self.previous_verse()
            case NextChapter():
                await self.next_chapter()
            case PreviousChapter():
                await self.previous_chapter()
            case ChapterStart():
                await self.chapter_start()
            case ChapterEnd():
                await self.chapter_end()
            case OpenTranslation(slug):
                await self.open_translation(slug)
            case CloseTranslation(slug):
                await self.close_translation(slug)
            case SetActive(slug):
                await self.set_active(slug)
            case SetLive(live):
                await self.set_live(live)
            case SetStrongs(strongs):
                await self.set_strongs(strongs)

    @_serialized
    async def command(self, name: str, params: dict | None = None) -> None:
        """Deprecated compatibility wrapper for string-and-dict callers."""
        await self.execute(parse_command(name, params))

    @_serialized
    async def close(self) -> None:
        for target in self.targets:
            with suppress(Exception):
                await target.set_live(False)
        self.state.live = False
        for subscription in tuple(self._subscriptions):
            subscription.close()
        for opened in self.translations:
            with suppress(Exception):
                opened.close()
        self.translations.clear()
        self.active_slug = None
