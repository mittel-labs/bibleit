from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from bibleit.verse import clean_verse_text, parse_line


@dataclass(frozen=True)
class LiveVerse:
    translation: str
    book: str
    chapter: int
    verse: int
    text: str

    @property
    def reference(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}"

    def to_payload(self) -> dict:
        return asdict(self) | {"reference": self.reference}


def parse_verse_line(translation: str, value: str) -> LiveVerse | None:
    parsed = parse_line(value)

    if parsed is None:
        return None

    return LiveVerse(
        translation=translation,
        book=parsed.book,
        chapter=parsed.chapter,
        verse=parsed.verse,
        text=clean_verse_text(parsed.text),
    )


def verse_payloads(values: Sequence[tuple[str, str]]) -> list[dict]:
    payloads = []

    for translation_slug, value in values:
        verse = parse_verse_line(translation_slug, value)

        if verse is not None:
            payloads.append(verse.to_payload())

    return payloads


def bundle_payload(
    values: Sequence[tuple[str, str]],
    *,
    publisher_id: str,
    sequence: int,
) -> dict | None:
    verses = verse_payloads(values)

    if not verses:
        return None

    return verses[0] | {
        "translations": verses,
        "publisher_id": publisher_id,
        "sequence": sequence,
    }
