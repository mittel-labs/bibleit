from __future__ import annotations
from dataclasses import dataclass

from textual.app import App
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding
from textual.widgets import ListView, ListItem, Input, Tree, Footer, Label, Static, Button
from textual.screen import Screen
from textual.message import Message
from textual.reactive import reactive
from textual.suggester import Suggester
from textual import events
from typing import Callable, Iterable, Sequence
from html import unescape

from bibleit import translation
from bibleit.live import parse_verse_line
from unidecode import unidecode
from rapidfuzz import fuzz, process


import atexit
import collections
import inspect
import json
import os
import re
import asyncio
import uuid
import urllib.error
import urllib.request
import aiohttp

from rich.markup import escape

WEB_DRIVER = "textual.drivers.web_driver:WebDriver"


def running_in_browser() -> bool:
    return os.getenv("TEXTUAL_DRIVER") == WEB_DRIVER


def live_publish_url() -> str:
    host = os.getenv("BIBLEIT_SERVE_HOST") or "0.0.0.0"
    port = os.getenv("BIBLEIT_SERVE_PORT") or "8000"
    return (os.getenv("BIBLEIT_LIVE_URL") or os.getenv("BIBLEIT_SERVE_PUBLIC_URL") or f"http://{host}:{port}").rstrip(
        "/"
    )


@dataclass(frozen=True)
class RowRef:
    bookid: int
    chapter: int
    verse: int


@dataclass
class NavigationState:
    bookid: int = 1
    chapter: int = 1
    verse: int = 1
    index: int = 0
    live: bool = False


def book_name_for(translation_: translation.Translation, bookid: int) -> str:
    for chapter in translation_.header.chapters.values():
        if chapter.bookid == bookid:
            return chapter.name
    return f"Book {bookid}"


def verse_reference_label(
    translation_: translation.Translation,
    bookid: int,
    chapter: int,
    verse: int,
) -> str:
    return f"{book_name_for(translation_, bookid)} {chapter}:{verse}"


def book_ids_for(translation_: translation.Translation) -> list[int]:
    return sorted({chapter.bookid for chapter in translation_.header.chapters.values()})


def chapter_count_for(translation_: translation.Translation, bookid: int) -> int | None:
    for chapter in translation_.header.chapters.values():
        if chapter.bookid == bookid:
            return chapter.chapters
    return None


def next_chapter_ref(
    translation_: translation.Translation,
    state: NavigationState,
) -> translation.TranslationRef | None:
    chapter_count = chapter_count_for(translation_, state.bookid)
    if chapter_count and state.chapter < chapter_count:
        return translation.TranslationRef(state.bookid, state.chapter + 1, 1)

    book_ids = book_ids_for(translation_)
    next_books = [bookid for bookid in book_ids if bookid > state.bookid]
    if next_books:
        return translation.TranslationRef(next_books[0], 1, 1)

    return None


def previous_chapter_ref(
    translation_: translation.Translation,
    state: NavigationState,
) -> translation.TranslationRef | None:
    if state.chapter > 1:
        return translation.TranslationRef(state.bookid, state.chapter - 1, 1)

    book_ids = book_ids_for(translation_)
    previous_books = [bookid for bookid in book_ids if bookid < state.bookid]
    if previous_books:
        bookid = previous_books[-1]
        chapter_count = chapter_count_for(translation_, bookid) or 1
        return translation.TranslationRef(bookid, chapter_count, 1)

    return None


def parse_navigation_ref(
    value: str,
    translation_: translation.Translation,
    state: NavigationState,
) -> translation.TranslationRef:
    command = value.strip()
    if command.startswith(":"):
        command = command[1:].strip()

    if match := re.fullmatch(r"[vV]\s*(\d+)", command):
        return translation.TranslationRef(state.bookid, state.chapter, int(match.group(1)))

    if match := re.fullmatch(r"[cC]\s*(\d+)", command):
        return translation.TranslationRef(state.bookid, int(match.group(1)), 1)

    if match := re.fullmatch(r"(\d+)", command):
        return translation.TranslationRef(state.bookid, state.chapter, int(match.group(1)))

    if match := re.fullmatch(r"(\d+)\s*[:.]\s*(\d+)", command):
        return translation.TranslationRef(state.bookid, int(match.group(1)), int(match.group(2)))

    if match := re.fullmatch(r"(.+?)\s+(\d+)(?:\s*[:.]\s*(\d+))?", command):
        book_name, chapter, verse = match.groups()
        bookid = translation_.resolve_bookid(book_name)
        if not bookid:
            raise ValueError(f"Book not found: {book_name}")
        return translation.TranslationRef(bookid, int(chapter), int(verse or 1))

    bookid = translation_.resolve_bookid(command)
    if not bookid:
        raise ValueError(f"Reference not found: {value}")
    return translation.TranslationRef(bookid, 1, 1)


def navigation_book_names(translation_: translation.Translation) -> list[str]:
    chapters = sorted(
        translation_.header.chapters.values(),
        key=lambda chapter: chapter.bookid,
    )
    names: list[str] = []
    seen = set()
    for chapter in chapters:
        if chapter.bookid in seen:
            continue
        names.append(chapter.name)
        seen.add(chapter.bookid)
    return names


def _navigation_book_part(value: str) -> tuple[str, str, str] | None:
    command = value.strip()
    if command.startswith(":"):
        command = command[1:].lstrip()

    if re.match(r"^([vVcC]\s*)?\d", command):
        return None

    if not command:
        return "", "", ""

    match = re.match(r"^(?P<book>.*?)(?P<tail>\s+\d.*)?$", command)
    if not match:
        return None

    book = match.group("book").rstrip()
    tail = command[len(book) :]
    return "", book, tail


def _normalized_book_name(value: str) -> str:
    return unidecode(value).strip().lower()


def _book_candidates(book: str, names: Sequence[str]) -> list[str]:
    normalized = _normalized_book_name(book)
    if not normalized:
        return list(names)

    normalized_names = [(name, _normalized_book_name(name)) for name in names]

    prefix_matches = [name for name, normalized_name in normalized_names if normalized_name.startswith(normalized)]
    if prefix_matches:
        return prefix_matches

    contains_matches = [name for name, normalized_name in normalized_names if normalized in normalized_name]
    if contains_matches:
        return contains_matches

    scored = process.extract(
        normalized,
        names,
        processor=_normalized_book_name,
        scorer=fuzz.WRatio,
        score_cutoff=68,
        limit=8,
    )
    return [name for name, _, _ in scored]


def navigation_completion_candidates(
    value: str,
    translation_: translation.Translation,
) -> list[str]:
    parts = _navigation_book_part(value)
    if parts is None:
        return []

    _, book, _ = parts
    names = navigation_book_names(translation_)

    return _book_candidates(book, names)


def navigation_suggestion_value(
    value: str,
    translation_: translation.Translation,
) -> str | None:
    parts = _navigation_book_part(value)
    if parts is None:
        return None

    _, book, tail = parts
    if not book.strip():
        return None

    candidates = navigation_completion_candidates(value, translation_)
    if not candidates:
        return None

    candidate = candidates[0]
    normalized_book = _normalized_book_name(book)
    normalized_candidate = _normalized_book_name(candidate)

    if not normalized_candidate.startswith(normalized_book):
        return None

    if tail and normalized_book != normalized_candidate:
        return None

    suffix = candidate[len(book) :]
    separator = "" if tail else " "
    return f"{book}{suffix}{tail}{separator}"


def _common_prefix(values: Sequence[str]) -> str:
    if not values:
        return ""

    prefix = values[0]
    for value in values[1:]:
        limit = min(len(prefix), len(value))
        index = 0
        while index < limit and prefix[index].lower() == value[index].lower():
            index += 1
        prefix = prefix[:index]
        if not prefix:
            break
    return prefix


def complete_navigation_value(
    value: str,
    translation_: translation.Translation,
) -> tuple[str, list[str], bool]:
    parts = _navigation_book_part(value)
    if parts is None:
        return value, [], False

    _, book, tail = parts
    candidates = navigation_completion_candidates(value, translation_)
    if not candidates:
        return value, [], False

    if len(candidates) == 1:
        separator = "" if tail else " "
        return f"{candidates[0]}{tail}{separator}", candidates, True

    common = _common_prefix(candidates)
    if len(common) > len(book):
        return f"{common}{tail}", candidates, True

    return value, candidates, False


def select_navigation_completion(value: str, completion: str) -> str:
    parts = _navigation_book_part(value)
    if parts is None:
        return value

    _, _, tail = parts
    separator = "" if tail else " "
    return f"{completion}{tail}{separator}"


class NavigationSuggester(Suggester):
    def __init__(self, translation_getter: Callable[[], translation.Translation | None]):
        super().__init__(use_cache=False, case_sensitive=True)
        self.translation_getter = translation_getter

    async def get_suggestion(self, value: str) -> str | None:
        translation_ = self.translation_getter()
        if translation_ is None:
            return None

        return navigation_suggestion_value(value, translation_)


@dataclass(frozen=True)
class HistoryEntry:
    bookid: int
    chapter: int
    verse: int
    label: str

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.bookid, self.chapter, self.verse)

    def as_ref(self) -> translation.TranslationRef:
        return translation.TranslationRef(self.bookid, self.chapter, self.verse)


@dataclass(frozen=True)
class TextSearchResult:
    ref: translation.TranslationRef
    label: str
    text: str


def decode_translation_value(value) -> str:
    if isinstance(value, str):
        return value

    return value.memoryview().tobytes().decode("utf-8", "replace")


def clean_verse_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"<S>.*?</S>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_search_result(
    translation_: translation.Translation,
    value: str,
) -> TextSearchResult | None:
    text = clean_verse_text(value)
    match = re.match(r"^(?P<book>.+)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+(?P<verse_text>.*)$", text)
    if not match:
        return None

    bookid = translation_.resolve_bookid(match.group("book"))
    if not bookid:
        return None

    chapter = int(match.group("chapter"))
    verse = int(match.group("verse"))
    return TextSearchResult(
        ref=translation.TranslationRef(bookid, chapter, verse),
        label=f"{match.group('book')} {chapter}:{verse}",
        text=match.group("verse_text"),
    )


def search_translation_text(
    translation_: translation.Translation,
    query: str,
    *,
    limit: int = 100,
) -> list[TextSearchResult]:
    normalized_query = unidecode(query).casefold().strip()
    if not normalized_query:
        return []

    results: list[TextSearchResult] = []
    for bookid in book_ids_for(translation_):
        cursor = translation_.read(translation.TranslationRef(bookid))

        while value := cursor.next():
            result = parse_search_result(translation_, decode_translation_value(value))
            if result is None:
                continue

            searchable = unidecode(f"{result.label} {result.text}").casefold()
            if normalized_query in searchable:
                results.append(result)

                if len(results) >= limit:
                    return results

    return results


class SessionHistory:
    MAX_ENTRIES = 500
    MIN_FUZZY_SCORE = 65

    def __init__(self) -> None:
        self._entries: collections.OrderedDict[tuple[int, int, int], HistoryEntry] = collections.OrderedDict()

    def record(self, entry: HistoryEntry) -> None:
        if entry.key in self._entries:
            del self._entries[entry.key]
        self._entries[entry.key] = entry
        while len(self._entries) > self.MAX_ENTRIES:
            self._entries.popitem(last=False)

    def entries(self, query: str = "") -> list[HistoryEntry]:
        ordered = list(reversed(self._entries.values()))
        normalized = unidecode(query.strip().lower())
        if not normalized:
            return ordered

        labels = [unidecode(entry.label.lower()) for entry in ordered]
        matches = process.extract(
            normalized,
            labels,
            scorer=fuzz.WRatio,
            score_cutoff=self.MIN_FUZZY_SCORE,
            limit=len(ordered),
        )
        label_to_entry = dict(zip(labels, ordered))
        return [label_to_entry[match[0]] for match in matches]


class HistoryPane(Vertical):
    can_focus = True
    can_focus_children = True
    pane_open = reactive(False)

    BINDINGS = [
        ("escape", "close_pane", "Close"),
        Binding("tab", "focus_filter", "Filter", show=True),
        Binding("shift+tab", "focus_list", "Verses", show=True),
        Binding("enter", "go_to_selected", "Go To", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.history = SessionHistory()
        self._filter = ""
        self._navigating = False

    def compose(self):
        yield Label("History", id="history-title")
        yield Input(placeholder="Filter verses…", id="history-filter")
        yield ListView(id="history-list")

    def watch_pane_open(self, pane_open: bool) -> None:
        self.set_class(pane_open, "open")
        if pane_open:
            self._refresh_list()
            self.call_after_refresh(self.action_focus_list)

    def toggle(self) -> None:
        self.pane_open = not self.pane_open
        if self.pane_open:
            self.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "focus_filter":
            return self._history_list_focused()
        if action == "focus_list":
            return self._history_filter_focused()
        return True

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

    def record(
        self,
        translation_: translation.Translation,
        ref: translation.TranslationRef,
    ) -> None:
        if self._navigating:
            return

        chapter = ref.chapter or 1
        verse = ref.verse_start or 1
        label = verse_reference_label(translation_, ref.bookid, chapter, verse)
        self.history.record(
            HistoryEntry(
                bookid=ref.bookid,
                chapter=chapter,
                verse=verse,
                label=label,
            )
        )

        if self.pane_open:
            self._refresh_list()

    def navigate_to(self, entry: HistoryEntry) -> None:
        bible_view = self.app.query_exactly_one(BibleView)
        self._navigating = True
        try:
            bible_view.go_to_ref(entry.as_ref())
            self.history.record(entry)
            if self.pane_open:
                self._refresh_list()
        finally:
            self._navigating = False

    def _refresh_list(self, *, keep_index: bool = False) -> None:
        list_view = self._history_list()
        previous_index = list_view.index if keep_index else None
        list_view.clear()
        for entry in self.history.entries(self._filter):
            item = ListItem(Label(entry.label))
            item.entry = entry
            list_view.append(item)

        if not list_view.children:
            return

        if keep_index and previous_index is not None:
            list_view.index = min(previous_index, len(list_view.children) - 1)
        else:
            list_view.index = 0

    async def on_key(self, event: events.Key) -> None:
        if not self.pane_open:
            return

        if event.key == "escape":
            event.stop()
            self.action_close_pane()
            return

        if self._history_list_focused() and event.key in ("up", "down"):
            event.stop()
            list_view = self._history_list()
            if not list_view.children:
                return
            if event.key == "down":
                list_view.action_cursor_down()
            else:
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

    def action_close_pane(self) -> None:
        if not self.pane_open:
            return
        self.pane_open = False
        self.app.query_exactly_one(BibleView).focus()


class LivePublisher:
    def __init__(self):
        self.url = live_publish_url()
        self.timeout = float(os.getenv("BIBLEIT_LIVE_TIMEOUT", "0.5"))
        self.token = os.getenv("BIBLEIT_LIVE_TOKEN")
        self.publisher_id = uuid.uuid4().hex
        self.sequence = 0

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def verse_payload(self, value: str, translation_slug: str) -> dict | None:
        if not self.enabled:
            return None

        verses = self._parse_verses([(translation_slug, value)])

        if not verses:
            return None

        self.sequence += 1
        primary = verses[0]
        return primary | {
            "translations": verses,
            "publisher_id": self.publisher_id,
            "sequence": self.sequence,
        }

    def bundle_payload(self, values: Sequence[tuple[str, str]]) -> dict | None:
        if not self.enabled:
            return None

        verses = self._parse_verses(values)

        if not verses:
            return None

        self.sequence += 1
        primary = verses[0]
        return primary | {
            "translations": verses,
            "publisher_id": self.publisher_id,
            "sequence": self.sequence,
        }

    def _parse_verses(self, values: Sequence[tuple[str, str]]) -> list[dict]:
        verses = []

        for translation_slug, value in values:
            verse = parse_verse_line(translation_slug, value)

            if verse is not None:
                verses.append(verse.to_payload())

        return verses

    async def publish_payload(self, payload: dict) -> bool:
        if not self.enabled:
            return False

        return await self._post("/api/publish", payload)

    async def set_live(self, live: bool) -> None:
        if not self.enabled:
            return

        await self._post("/api/live", {"live": live})

    def set_live_blocking(self, live: bool) -> bool:
        if not self.enabled:
            return False

        payload = json.dumps({"live": live}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/api/live",
            data=payload,
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return 200 <= response.status < 300
        except (OSError, TimeoutError, urllib.error.URLError):
            return False

    async def _post(self, path: str, payload: dict) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.url}{path}",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    return 200 <= response.status < 300
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers


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
            placeholder="Go to verse: Dan 9:2",
            suggester=NavigationSuggester(self._active_translation),
            id="status-command",
        )
        yield Static(id="status-command-completions")
        with Container(id="status-actions"):
            yield Button("Search", id="action-search")
            yield Button("Translations", id="action-translations")
            yield Button("Strongs", id="action-strongs")
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
        live_button = self.query_one("#action-live", Button)
        strongs_button.set_class(self.strongs, "active")
        live_button.set_class(self.live, "active")
        live_button.disabled = running_in_browser()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bible_view = self.app.query_exactly_one(BibleView)

        actions = {
            "action-menu": self.action_toggle_menu,
            "action-search": bible_view.action_open_search,
            "action-translations": bible_view.action_open_translations,
            "action-strongs": bible_view.action_toggle_strongs,
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
        return view.translation if view else None

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "status-command":
            return

        event.stop()
        if self.select_completion():
            return

        bible_view = self.app.query_exactly_one(BibleView)
        if bible_view.go_to_command(event.value):
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

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "status-command" and not self._completing:
            self._hide_completions()


class Search(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("tab", "focus_results", "Results", show=True),
        Binding("shift+tab", "focus_input", "Search", show=True),
    ]

    def __init__(
        self,
        view: View,
    ):
        super().__init__()

        self.view = view
        self.input = Input(placeholder="Search words or phrases…", id="text-search-input")
        self.results: list[TextSearchResult] = []

    def on_mount(self):
        self.input.focus()

    def compose(self):
        with Container(id="search-panel"):
            yield Label("Search", id="search-title")
            yield Label(
                f"Find text in [bold #d97706]{self.view.translation.slug}[/]",
                id="search-caption",
                markup=True,
            )
            yield self.input
            yield Static("Type a word or phrase to search rendered verse text.", id="search-summary")
            yield ListView(id="text-search-results")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "focus_results":
            return bool(self._result_list().children)
        if action == "focus_input":
            return self.app.focused is not self.input
        return True

    def _result_list(self) -> ListView:
        return self.query_one("#text-search-results", ListView)

    def action_focus_results(self) -> None:
        result_list = self._result_list()
        if result_list.children and result_list.index is None:
            result_list.index = 0
        result_list.focus()

    def action_focus_input(self) -> None:
        self.input.focus()

    def _refresh_results(self) -> None:
        query = self.input.value.strip()
        result_list = self._result_list()
        summary = self.query_one("#search-summary", Static)
        result_list.clear()

        self.results = search_translation_text(self.view.translation, query)
        if not query:
            summary.update("Type a word or phrase to search rendered verse text.")
            return

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

    def _open_result(self, result: TextSearchResult) -> None:
        bible_view = self.app.query_exactly_one(BibleView)
        bible_view.go_to_ref(result.ref)
        self.app.query_one(HistoryPane).record(self.view.translation, result.ref)
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


class ShortcutsScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        ("?", "app.pop_screen", "Close"),
    ]

    SHORTCUTS = [
        ("↑ / ↓", "Previous / next verse"),
        ("Ctrl+A", "Beginning of current chapter"),
        ("Ctrl+E", "End of current chapter"),
        ("Ctrl+<", "Previous chapter"),
        ("Ctrl+>", "Next chapter"),
        ("g", "Go to verse"),
        ("Tab", "Cycle go-to matches"),
        ("Enter", "Select match or navigate"),
        ("Ctrl+T", "Translations"),
        ("Ctrl+S", "Search text"),
        ("Ctrl+G", "Strongs"),
        ("Ctrl+W", "Close pane"),
        ("F2", "Toggle split layout"),
        ("Ctrl+L", "Live mode"),
        ("?", "Show shortcuts"),
        ("Esc", "Close / clear"),
    ]

    def compose(self):
        with Container():
            yield Label("Shortcuts", id="shortcuts-title")
            for key, description in self.SHORTCUTS:
                with Horizontal(classes="shortcut-row"):
                    yield Label(key, classes="shortcut-key")
                    yield Label(description, classes="shortcut-description")


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
        if not self.children:
            return

        self.focus()

        if self.index is None:
            self.index = 0
            return

        if self.index == len(self.children) - 1:
            row = self._next_row()
            if row is None:
                return
            await self.append(row)
            self._force_highlight_row_after_refresh(row)
            return

        self.action_cursor_down()

    async def _move_cursor_up(self) -> None:
        if not self.children:
            return

        self.focus()

        if self.index is None:
            self.index = len(self.children) - 1
            return

        if self.index == 0:
            row = self._previous_row()
            if row is None:
                return
            await self.insert(0, [row])
            self._force_highlight_row_after_refresh(row)
            return

        self.action_cursor_up()

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

        self.index = self._nodes.index(event.item)
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
                "Search reference not found",
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
        ("ctrl+s", "open_search", "Search"),
        ("ctrl+g", "toggle_strongs", "Strongs"),
        ("ctrl+l", "toggle_live", "Live"),
        ("ctrl+w", "close_pane", "Close Pane"),
        ("ctrl+a", "chapter_start", "Chapter Start"),
        ("ctrl+e", "chapter_end", "Chapter End"),
        ("ctrl+<", "previous_chapter", "Previous Chapter"),
        ("ctrl+>", "next_chapter", "Next Chapter"),
        ("g", "open_reference", "Go To Verse"),
        (":", "open_reference", "Go To Verse"),
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
        self.app.query_one(HistoryPane).record(view.translation, ref)
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

    def action_open_search(self):
        if not self.views:
            self.notify(
                "Please open a translation first",
                severity="warning",
            )
            return

        view = self.focused_view()

        if not view:
            view = self.views[0]

        self.app.push_screen(Search(view))

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
            self.notify("Already at the last chapter", severity="warning", timeout=3)
            return

        self.go_to_ref(ref)

    def action_previous_chapter(self):
        view = self._active_view()
        if not view:
            return

        ref = previous_chapter_ref(view.translation, self.state)
        if ref is None:
            self.notify("Already at the first chapter", severity="warning", timeout=3)
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

    def __init__(self):
        super().__init__()
        atexit.register(self._disable_live_on_shutdown)

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

    def compose(self):
        with Horizontal(id="workspace"):
            yield BibleView()
            yield HistoryPane()
        yield StatusBar()
