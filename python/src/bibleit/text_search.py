from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re

from unidecode import unidecode

from bibleit import translation
from bibleit.navigation import book_ids_for


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
