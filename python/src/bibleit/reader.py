from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from bibleit import translation

VERSE_LINE_RE = re.compile(r"^(?P<book>.+)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+(?P<text>(?s:.*))$")
STRONG_RE = re.compile(r"<S>(.*?)</S>")
OLD_TESTAMENT_LAST_BOOKID = 39
DEFAULT_WINDOW = 25


@dataclass(frozen=True)
class RowRef:
    bookid: int
    chapter: int
    verse: int


@dataclass(frozen=True)
class ParsedLine:
    book: str
    chapter: int
    verse: int
    text: str

    @property
    def reference(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}"


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


def decode(value) -> str:
    if isinstance(value, str):
        return value

    return value.memoryview().tobytes().decode("utf-8", "replace")


def parse_line(value: str) -> ParsedLine | None:
    match = VERSE_LINE_RE.match(value.strip())

    if not match:
        return None

    return ParsedLine(
        book=match.group("book"),
        chapter=int(match.group("chapter")),
        verse=int(match.group("verse")),
        text=match.group("text"),
    )


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


def strong_prefix(bookid: int) -> str:
    return "H" if bookid <= OLD_TESTAMENT_LAST_BOOKID else "G"


def render_textual_markup(
    value: str,
    *,
    strongs: Mapping[str, translation.StrongEntry] | None,
    show_strongs: bool = False,
    prefix: str = "H",
) -> str:
    text = re.sub(r"(.* \d+:\d+)", r"[bold]\1 [/]", value)
    text = re.sub(r"<b>(.*?)</b>", r"[bold]\1[/]", text)
    text = re.sub(r"<i>(.*?)</i>", r"[italic]\1[/]", text)

    def replace_strong(match):
        raw = match.group(1).strip()

        if strongs is None:
            return raw

        code = f"{prefix}{raw}"
        entry = strongs.get(code)

        if not entry:
            return ""

        if not show_strongs:
            return ""

        return f"[#c96f00][@click=app.open_strong('{code}')]ᴴ{raw}[/]"

    text = text.replace("<br>", "\n").replace("<br/>", "\n")
    text = STRONG_RE.sub(replace_strong, text)
    return re.sub(
        r"<sup>(.*?)</sup>",
        r"[dim italic]\1[/]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
