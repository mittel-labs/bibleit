from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

from bibleit import reader, translation
from bibleit.navigation import (
    navigation_completion_candidates,
    navigation_suggestion_value,
    parse_navigation_ref,
)
from bibleit.operator.errors import CapabilityError, OperatorError
from bibleit.operator.models import (
    CloseTranslation,
    InstallEvent,
    OpenTranslation,
    OperatorCommand,
    OperatorState,
    Reference,
    ResolveResult,
    SearchResult,
    StateEvent,
    TranslationCatalogState,
    TranslationInfo,
    TranslationLanguage,
    VerseColumn,
    VerseRow,
    VerseWindow,
    parse_command,
)
from bibleit.operator.ports import ConfigStore, OpenedTranslation, ReadingService, TaskSpawner, TranslationCatalog
from bibleit.operator.session import MAX_TOTAL, EventSubscription, OperatorSession
from bibleit.text_find import find_translation_text


@dataclass(frozen=True)
class OperatorCapabilities:
    install_translations: bool = False
    remove_translations: bool = False
    write_config: bool = False


class AsyncioTaskSpawner:
    def __init__(self):
        self.tasks: set[asyncio.Task] = set()

    def spawn(self, awaitable: Awaitable[Any]) -> asyncio.Task:
        task = asyncio.create_task(awaitable)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def close(self) -> None:
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class NativeTranslationCatalog:
    """Adapter for Bibleit's installed/downloadable translation functions."""

    async def list(self) -> TranslationCatalogState:
        installed, languages = await asyncio.gather(
            asyncio.to_thread(translation.get_installed),
            asyncio.to_thread(translation.get_languages_available),
        )
        installed_slugs = frozenset(installed)
        return TranslationCatalogState(
            installed=tuple(sorted(installed_slugs)),
            languages=tuple(
                TranslationLanguage(
                    language.name,
                    tuple(
                        TranslationInfo(header.slug, header.name, header.slug in installed_slugs)
                        for header in language.translations
                        if header is not None
                    ),
                )
                for language in languages
            ),
        )

    async def open(self, slug: str) -> OpenedTranslation:
        return await asyncio.to_thread(translation.open, slug)

    async def install(self, slug: str) -> None:
        await asyncio.to_thread(translation.install, slug)
        await asyncio.to_thread(translation.get_index, slug)

    async def remove(self, slug: str) -> None:
        await asyncio.to_thread(translation.uninstall, slug)


class CoreReadingService:
    def books(self, opened: OpenedTranslation):
        return reader.books(opened)

    def window(self, opened, ref, *, before, total):
        return reader.window_around(opened, ref, before=before, total=total)

    def row(self, opened: OpenedTranslation, line: str) -> VerseRow | None:
        parsed = reader.parse_line(line)
        if parsed is None:
            return None
        bookid = opened.resolve_bookid(parsed.book)
        return VerseRow(
            bookid,
            parsed.book,
            parsed.chapter,
            parsed.verse,
            parsed.reference,
            reader.render_html(parsed.text, prefix=reader.strong_prefix(bookid or 1)),
            reader.clean_verse_text(parsed.text),
        )

    def resolve(self, opened: OpenedTranslation, value: str, state: Any) -> ResolveResult:
        candidates = tuple(navigation_completion_candidates(value, opened))
        suggestion = navigation_suggestion_value(value, opened)
        try:
            ref = parse_navigation_ref(value, opened, state)
        except ValueError as error:
            return ResolveResult(candidates, suggestion, None, False, str(error))
        resolved = Reference(ref.bookid, ref.chapter or 1, ref.verse_start or 1)
        return ResolveResult(candidates, suggestion, resolved, reader.verse_line(opened, ref) is not None)

    async def search(self, opened: OpenedTranslation, query: str, *, limit: int):
        found = await asyncio.to_thread(find_translation_text, opened, query, limit=limit)
        return tuple(
            SearchResult(item.label, item.text, item.ref.bookid, item.ref.chapter or 1, item.ref.verse_start or 1)
            for item in found
        )

    async def strongs(self, opened: OpenedTranslation, code: str):
        entries = await asyncio.to_thread(lambda: opened.strongs)
        return entries.get(code.upper().strip())


class OperatorService:
    """Application API used by host integrations and Bibleit's own clients."""

    def __init__(
        self,
        *,
        session: OperatorSession,
        catalog: TranslationCatalog,
        reading: ReadingService | None = None,
        config_store: ConfigStore | None = None,
        task_spawner: TaskSpawner | None = None,
        capabilities: OperatorCapabilities | None = None,
    ):
        self.session = session
        self.catalog = catalog
        self.reading = reading or CoreReadingService()
        self.config_store = config_store
        self.task_spawner = task_spawner or AsyncioTaskSpawner()
        self.capabilities = capabilities or OperatorCapabilities()
        self._installs: dict[str, Any] = {}

    def state(self) -> OperatorState:
        return self.session.state_model()

    async def translations(self) -> TranslationCatalogState:
        return await self.catalog.list()

    async def open_translation(self, slug: str) -> OperatorState:
        if self.session.find(slug) is None:
            try:
                opened = await self.catalog.open(slug)
            except (LookupError, OSError, RuntimeError, ValueError) as error:
                raise OperatorError(str(error)) from error
            await self.session.add_translation(opened)
        return self.state()

    async def close_translation(self, slug: str) -> OperatorState:
        await self.session.close_translation(slug)
        return self.state()

    def install_translation(self, slug: str) -> Any:
        self._require(self.capabilities.install_translations, "Translation installation")
        if slug not in self._installs:
            task = self.task_spawner.spawn(self._run_install(slug))
            self._installs[slug] = task
        return self._installs[slug]

    async def _run_install(self, slug: str) -> None:
        await self.session.notify(InstallEvent(slug, "installing"))
        try:
            await self.catalog.install(slug)
        except asyncio.CancelledError:
            await self.session.notify(InstallEvent(slug, "cancelled"))
            raise
        except Exception as error:
            await self.session.notify(InstallEvent(slug, "failed", str(error)))
        else:
            await self.session.notify(InstallEvent(slug, "installed"))
        finally:
            self._installs.pop(slug, None)

    async def remove_translation(self, slug: str) -> None:
        self._require(self.capabilities.remove_translations, "Translation removal")
        await self.session.close_translation(slug)
        await self.catalog.remove(slug)
        await self.session.notify(InstallEvent(slug, "removed"))

    def verse_window(self, *, before: int | None = None, total: int | None = None) -> VerseWindow:
        before = self.session.before if before is None else max(0, before)
        total = self.session.total if total is None else max(1, min(total, MAX_TOTAL))
        ref = self.session.current_ref()
        columns = []
        for opened in self.session.translations:
            window = self.reading.window(opened, ref, before=before, total=total)
            rows = tuple(row for line in window.lines if (row := self.reading.row(opened, line)) is not None)
            columns.append(VerseColumn(opened.slug, opened.header.name, window.index, rows))
        return VerseWindow(self.session.reference(), tuple(columns))

    def books(self, slug: str | None = None):
        return tuple(self.reading.books(self._opened(slug)))

    def translation(self, slug: str | None = None) -> TranslationInfo:
        opened = self._opened(slug)
        return TranslationInfo(opened.slug, opened.header.name)

    def resolve(self, value: str, slug: str | None = None) -> ResolveResult:
        return self.reading.resolve(self._opened(slug), value, self.session.state)

    async def search(self, query: str, *, slug: str | None = None, limit: int = 100):
        if not query.strip():
            return ()
        return tuple(await self.reading.search(self._opened(slug), query, limit=max(1, min(limit, 500))))

    async def strongs(self, code: str, *, slug: str | None = None):
        entry = await self.reading.strongs(self._opened(slug), code)
        if entry is None:
            raise OperatorError(f"No Strong's entry for {code.upper().strip()}")
        return entry

    async def config(self) -> dict[str, str]:
        if self.config_store is None:
            raise CapabilityError("Configuration is not available")
        return await self.config_store.read()

    async def write_config(self, values: dict[str, str]) -> None:
        self._require(self.capabilities.write_config, "Configuration writes")
        if self.config_store is None:
            raise CapabilityError("Configuration is not available")
        await self.config_store.write(values)

    def subscribe(self, *, include_initial: bool = True, max_events: int = 0) -> EventSubscription:
        subscription = self.session.subscribe(max_events=max_events)
        if include_initial:
            subscription._queue.put_nowait(StateEvent(self.state()))
        return subscription

    async def execute(self, command: OperatorCommand) -> OperatorState:
        if isinstance(command, OpenTranslation):
            return await self.open_translation(command.slug)
        if isinstance(command, CloseTranslation):
            return await self.close_translation(command.slug)
        await self.session.execute(command)
        return self.state()

    async def command(self, name: str, params: dict | None = None) -> OperatorState:
        return await self.execute(parse_command(name, params))

    async def close(self) -> None:
        await self.task_spawner.close()
        await self.session.close()

    def _opened(self, slug: str | None) -> OpenedTranslation:
        if slug:
            opened = self.session.find(slug)
            if opened is None:
                raise OperatorError(f"Translation not open: {slug}")
            return opened
        return self.session.require_active()

    @staticmethod
    def _require(granted: bool, name: str) -> None:
        if not granted:
            raise CapabilityError(f"{name} is not enabled by this host")
