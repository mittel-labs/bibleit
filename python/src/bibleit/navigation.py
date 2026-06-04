from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Sequence

from rapidfuzz import fuzz, process
from textual.suggester import Suggester
from unidecode import unidecode

from bibleit import translation


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

    next_books = [bookid for bookid in book_ids_for(translation_) if bookid > state.bookid]
    if next_books:
        return translation.TranslationRef(next_books[0], 1, 1)

    return None


def previous_chapter_ref(
    translation_: translation.Translation,
    state: NavigationState,
) -> translation.TranslationRef | None:
    if state.chapter > 1:
        return translation.TranslationRef(state.bookid, state.chapter - 1, 1)

    previous_books = [bookid for bookid in book_ids_for(translation_) if bookid < state.bookid]
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
    return _book_candidates(book, navigation_book_names(translation_))


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
        if tail:
            return None
        return f"{candidate} "

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
