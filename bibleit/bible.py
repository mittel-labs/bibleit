from locale import normalize
import re

from bibleit import config as _config
from os.path import exists as _file_exists
from operator import itemgetter as _item


_ACCENTS = {
    "À": "A",
    "Á": "A",
    "Â": "A",
    "Ã": "A",
    "Ä": "A",
    "à": "a",
    "á": "a",
    "â": "a",
    "ã": "a",
    "ä": "a",
    "ª": "A",
    "È": "E",
    "É": "E",
    "Ê": "E",
    "Ë": "E",
    "è": "e",
    "é": "e",
    "ê": "e",
    "ë": "e",
    "Í": "I",
    "Ì": "I",
    "Î": "I",
    "Ï": "I",
    "í": "i",
    "ì": "i",
    "î": "i",
    "ï": "i",
    "Ò": "O",
    "Ó": "O",
    "Ô": "O",
    "Õ": "O",
    "Ö": "O",
    "ò": "o",
    "ó": "o",
    "ô": "o",
    "õ": "o",
    "ö": "o",
    "º": "O",
    "Ù": "U",
    "Ú": "U",
    "Û": "U",
    "Ü": "U",
    "ù": "u",
    "ú": "u",
    "û": "u",
    "ü": "u",
    "Ñ": "N",
    "ñ": "n",
    "Ç": "C",
    "ç": "c",
    "§": "S",
    "³": "3",
    "²": "2",
    "¹": "1",
}
_NORMALIZE = str.maketrans(_ACCENTS)


class Bible:
    def __init__(self, version):
        self.version = version.lower()
        target = f"{_config.translation_dir}/{self.version}"
        assert _file_exists(
            target,
        ), f"bible translation '{self.version}' not found. (available: {_config.available_bible})"
        with open(f"{_config.translation_dir}/{self.version}") as f:
            self.content = [(line, line.translate(_NORMALIZE)) for line in f]

    def __repr__(self):
        return self.version

    def book(self, name):
        return "\n".join(
            line
            for line, normalized in self.content
            if re.search(rf"^{name}", normalized, re.IGNORECASE)
        ).rstrip()

    def chapter(self, book, name):
        return "\n".join(
            line
            for line, normalized in self.content
            if re.search(rf"^{book}.* {name}:", normalized, re.IGNORECASE)
        ).rstrip()

    def verse(self, book, chapter, verse):
        return "\n".join(
            line
            for line, normalized in self.content
            if re.search(
                rf"^{book}.* {chapter}:{verse} (.*)", normalized, re.IGNORECASE
            )
        ).rstrip()

    def verseSlice(self, book, chapter, start, end):
        assert start < end, "Invalid verse slicing"
        verses = "|".join(map(str, range(start, end + 1)))
        return "\n".join(
            line
            for line, normalized in self.content
            if re.findall(
                rf"^{book}.* {chapter}:(?=({verses}))", normalized, re.IGNORECASE
            )
        ).rstrip()

    def _filter(self, value):
        return [
            (line, normalized)
            for line, normalized in self.content
            if re.search(rf"\b{value}\b", normalized, re.IGNORECASE)
        ]

    def search(self, value):
        return "\n".join(map(_item(0), self._filter(value))).rstrip()

    def count(self, value):
        if target := value.lower():
            return sum(
                normalized.lower().count(target)
                for _, normalized in self._filter(value)
            )
        return 0

    def parse(self, args):
        match args:
            case [book]:
                return self.book(book)
            case [book, value]:
                match value.split(":"):
                    case [chapter]:
                        return self.chapter(book, int(chapter))
                    case [chapter, verse]:
                        match verse.split("-"):
                            case [start]:
                                return self.verse(book, int(chapter), int(start))
                            case [start, end]:
                                return self.verseSlice(
                                    book, int(chapter), int(start), int(end)
                                )
            case [book, chapter, verse]:
                return self.verse(book, chapter, verse)
        return None
