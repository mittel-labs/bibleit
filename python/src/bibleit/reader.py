from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bibleit import translation
from bibleit.verse import (
    HTML_TAG_RE,
    OLD_TESTAMENT_LAST_BOOKID,
    STRONG_RE,
    VERSE_LINE_RE,
    ParsedLine,
    RowRef,
    clean_verse_text,
    decode,
    parse_line,
    render_textual_markup,
    strong_prefix,
)

DEFAULT_WINDOW = 25

__all__ = [
    "Book",
    "DEFAULT_WINDOW",
    "HTML_TAG_RE",
    "OLD_TESTAMENT_LAST_BOOKID",
    "ParsedLine",
    "ReadableTranslation",
    "RowRef",
    "STRONG_RE",
    "VERSE_LINE_RE",
    "VerseWindow",
    "books",
    "chapter_last_ref",
    "chapter_lines",
    "clean_verse_text",
    "decode",
    "parse_line",
    "render_textual_markup",
    "row_ref",
    "strong_prefix",
    "target_row_ref",
    "verse_line",
    "window_around",
]


@dataclass(frozen=True)
class Book:
    bookid: int
    name: str
    chapters: int


@dataclass
class VerseWindow:
    lines: list[str]
    cursor: object | None
    index: int | None


class ReadableTranslation(Protocol):
    slug: str
    header: translation.TranslationHeader

    def resolve_bookid(self, book_name: str) -> int | None: ...

    def read(self, ref: translation.TranslationRef): ...

    def cursor_from(self, ref: translation.TranslationRef): ...


def row_ref(translation_: ReadableTranslation | None, value: str) -> RowRef | None:
    if translation_ is None:
        return None

    parsed = parse_line(value)

    if parsed is None:
        return None

    bookid = translation_.resolve_bookid(parsed.book)

    if not bookid:
        return None

    return RowRef(bookid=bookid, chapter=parsed.chapter, verse=parsed.verse)


def target_row_ref(ref: translation.TranslationRef) -> RowRef:
    return RowRef(ref.bookid, ref.chapter or 1, ref.verse_start or 1)


def verse_line(translation_: ReadableTranslation, ref: translation.TranslationRef) -> str | None:
    try:
        cursor = translation_.cursor_from(ref)
    except RuntimeError:
        return None

    value = cursor.next()

    if value is None:
        return None

    line = decode(value)

    if row_ref(translation_, line) != target_row_ref(ref):
        return None

    return line


def window_around(
    translation_: ReadableTranslation,
    ref: translation.TranslationRef,
    *,
    before: int = 0,
    total: int = DEFAULT_WINDOW,
) -> VerseWindow:
    target = target_row_ref(ref)
    previous_lines: list[str] = []
    previous_cursor = translation_.cursor_from(ref)

    for _ in range(max(0, before)):
        value = previous_cursor.previous()

        if value is None:
            break

        previous_lines.insert(0, decode(value))

    cursor = translation_.cursor_from(ref)
    lines = [*previous_lines]

    for _ in range(max(1, total - len(previous_lines))):
        value = cursor.next()

        if value is None:
            break

        lines.append(decode(value))

    index = None

    for position, line in enumerate(lines):
        if row_ref(translation_, line) == target:
            index = position
            break

    return VerseWindow(lines=lines, cursor=cursor, index=index)


def chapter_lines(translation_: ReadableTranslation, bookid: int, chapter: int) -> list[str]:
    try:
        cursor = translation_.cursor_chapter(translation.TranslationRef(bookid, chapter))
    except RuntimeError:
        return []

    lines = []

    while value := cursor.next():
        lines.append(decode(value))

    return lines


def chapter_last_ref(
    translation_: ReadableTranslation,
    bookid: int,
    chapter: int,
) -> translation.TranslationRef | None:
    last_ref = None

    for line in chapter_lines(translation_, bookid, chapter):
        last_ref = row_ref(translation_, line)

    if last_ref is None:
        return None

    return translation.TranslationRef(last_ref.bookid, last_ref.chapter, last_ref.verse)


def books(translation_: ReadableTranslation) -> list[Book]:
    found: dict[int, Book] = {}

    for chapter in translation_.header.chapters.values():
        if chapter.bookid in found:
            continue

        found[chapter.bookid] = Book(
            bookid=chapter.bookid,
            name=chapter.name,
            chapters=chapter.chapters,
        )

    return sorted(found.values(), key=lambda book: book.bookid)
