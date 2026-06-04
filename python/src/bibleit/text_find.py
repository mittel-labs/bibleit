from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from collections import OrderedDict
import os
import re

from unidecode import unidecode

from bibleit import translation
from bibleit.navigation import book_ids_for

DEFAULT_FIND_INDEX_CACHE_SIZE = 4


@dataclass(frozen=True)
class TextFindResult:
    ref: translation.TranslationRef
    label: str
    text: str
    findable: str = ""

    def __post_init__(self) -> None:
        if not self.findable:
            object.__setattr__(
                self,
                "findable",
                unidecode(f"{self.label} {self.text}").casefold(),
            )


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


def parse_find_result(
    translation_: translation.Translation,
    value: str,
) -> TextFindResult | None:
    text = clean_verse_text(value)
    match = re.match(r"^(?P<book>.+)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+(?P<verse_text>.*)$", text)
    if not match:
        return None

    bookid = translation_.resolve_bookid(match.group("book"))
    if not bookid:
        return None

    chapter = int(match.group("chapter"))
    verse = int(match.group("verse"))
    return TextFindResult(
        ref=translation.TranslationRef(bookid, chapter, verse),
        label=f"{match.group('book')} {chapter}:{verse}",
        text=match.group("verse_text"),
    )


def find_translation_text(
    translation_: translation.Translation,
    query: str,
    *,
    limit: int = 100,
) -> list[TextFindResult]:
    return cached_find_index(translation_).find(query, limit=limit)


class TextFindIndex:
    def __init__(self, results: list[TextFindResult]):
        self.results = results

    @classmethod
    def build(cls, translation_: translation.Translation) -> TextFindIndex:
        results: list[TextFindResult] = []
        for bookid in book_ids_for(translation_):
            cursor = translation_.read(translation.TranslationRef(bookid))

            while value := cursor.next():
                result = parse_find_result(translation_, decode_translation_value(value))
                if result is not None:
                    results.append(result)

        return cls(results)

    def find(self, query: str, *, limit: int = 100) -> list[TextFindResult]:
        normalized_query = unidecode(query).casefold().strip()
        if not normalized_query:
            return []

        results: list[TextFindResult] = []
        for result in self.results:
            if normalized_query in result.findable:
                results.append(result)

                if len(results) >= limit:
                    break

        return results


_INDEX_CACHE: OrderedDict[str, TextFindIndex] = OrderedDict()


def cached_find_index(translation_: translation.Translation) -> TextFindIndex:
    slug = translation_.slug
    if slug in _INDEX_CACHE:
        _INDEX_CACHE.move_to_end(slug)
        return _INDEX_CACHE[slug]

    index = TextFindIndex.build(translation_)
    _INDEX_CACHE[slug] = index
    _trim_index_cache()
    return index


def clear_find_index_cache() -> None:
    _INDEX_CACHE.clear()


def find_index_cache_size() -> int:
    try:
        return max(1, int(os.getenv("BIBLEIT_FIND_INDEX_CACHE_SIZE", DEFAULT_FIND_INDEX_CACHE_SIZE)))
    except ValueError:
        return DEFAULT_FIND_INDEX_CACHE_SIZE


def _trim_index_cache() -> None:
    while len(_INDEX_CACHE) > find_index_cache_size():
        _INDEX_CACHE.popitem(last=False)
