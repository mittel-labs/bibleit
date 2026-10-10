from __future__ import annotations

import collections
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from unidecode import unidecode

from bibleit import translation


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
        direct_matches = [entry for entry, label in zip(ordered, labels) if _matches_history_text(normalized, label)]
        if len(normalized) <= 2:
            return direct_matches

        matches = process.extract(
            normalized,
            labels,
            scorer=fuzz.WRatio,
            score_cutoff=self.MIN_FUZZY_SCORE,
            limit=len(ordered),
        )
        label_to_entry = dict(zip(labels, ordered))
        fuzzy_matches = [label_to_entry[match[0]] for match in matches]
        return _unique_entries([*direct_matches, *fuzzy_matches])


def _matches_history_text(query: str, label: str) -> bool:
    if query in label:
        return True

    return any(word.startswith(query) for word in label.split())


def _unique_entries(entries: list[HistoryEntry]) -> list[HistoryEntry]:
    seen = set()
    unique = []
    for entry in entries:
        if entry.key in seen:
            continue
        unique.append(entry)
        seen.add(entry.key)
    return unique
