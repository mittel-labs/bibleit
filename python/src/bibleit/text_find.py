from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
import os

from unidecode import unidecode

from bibleit import translation
from bibleit.navigation import book_ids_for
from bibleit.reader import clean_verse_text, decode, parse_line

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


decode_translation_value = decode


def parse_find_result(
    translation_: translation.Translation,
    value: str,
) -> TextFindResult | None:
    parsed = parse_line(clean_verse_text(value))
    if parsed is None:
        return None

    bookid = translation_.resolve_bookid(parsed.book)
    if not bookid:
        return None

    return TextFindResult(
        ref=translation.TranslationRef(bookid, parsed.chapter, parsed.verse),
        label=parsed.reference,
        text=parsed.text,
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
