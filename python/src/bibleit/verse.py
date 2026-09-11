from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from bibleit.translation import StrongEntry

VERSE_LINE_RE = re.compile(r"^(?P<book>.+?)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+(?P<text>(?s:.*))$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
STRONG_RE = re.compile(r"<S>(.*?)</S>", flags=re.IGNORECASE | re.DOTALL)
OLD_TESTAMENT_LAST_BOOKID = 39


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


def decode(value) -> str:
    if isinstance(value, str):
        return value

    return value.memoryview().tobytes().decode("utf-8", "replace")


def clean_verse_text(value: str) -> str:
    value = unescape(value)
    value = STRONG_RE.sub("", value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = HTML_TAG_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


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


def strong_prefix(bookid: int) -> str:
    return "H" if bookid <= OLD_TESTAMENT_LAST_BOOKID else "G"


def render_textual_markup(
    value: str,
    *,
    strongs: Mapping[str, StrongEntry] | None,
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
