import itertools
import functools
import re
import importlib.resources

from pathlib import Path

from bibleit import config as _config
from bibleit import translations as _translations

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
_COLOR_END = "\x1b[0m"
_COLOR_LEN = 255 // len(_config.available_bible)
_VERSE_SLICE_DELIMITER = ":"
_VERSE_RANGE_DELIMITER = "-"
_VERSE_CONTINUATION_DELIMITER = "+"
_VERSE_POINTER_DELIMITER = "^"


class BibleNotFound(Exception):
    def __init__(self, version) -> None:
        super().__init__(f"Bible translation not found: {version}")
        self.version = version


class BibleMeta(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)
        cls._ids = itertools.count(1)


class Bible(metaclass=BibleMeta):
    def __init__(self, version):
        self.id = next(self.__class__._ids)
        self.version = version.lower()
        self.color = "\x1b[48;2;{};{};{}m".format(
            self.id + _COLOR_LEN,
            (self.id + 2) * _COLOR_LEN,
            (self.id + 3) * _COLOR_LEN,
        )
        try:
            target = importlib.resources.path(_translations, self.version)
            if not target.is_file():
                 raise BibleNotFound(self.version)
            with target.open() as f:
                self.content = [
                    (line.strip(), line.translate(_NORMALIZE).strip()) for line in f
                ]
            self.display = functools.reduce(
                lambda f, g: lambda x: f(g(x)), [self.labeled, self.colored], lambda x: x
            )
        except ValueError as e:
            raise BibleNotFound(self.version) from e

    def __repr__(self):
        return self.colored(self.version)

    def __hash__(self):
        return hash(self.version)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.version == other.version

    def labeled(self, value):
        return f"{self.version:>10} {value}" if _config.label else value

    def colored(self, value):
        return (
            "{}{}{}".format(self.color, value, _COLOR_END) if _config.color else value
        )

    def book(self, name):
        return [
            self.display(line)
            for line, normalized in self.content
            if re.search(rf"^{name}", normalized, re.IGNORECASE)
        ]

    def chapter(self, book, name):
        return [
            self.display(line)
            for line, normalized in self.content
            if re.search(rf"^{book}.* {name}:", normalized, re.IGNORECASE)
        ]

    def verse(self, book, chapter, verse):
        return {
            self.display(line)
            for line, normalized in self.content
            if re.search(
                rf"^{book}.* {chapter}:{verse} (.*)", normalized, re.IGNORECASE
            )
        }

    def _filter(self, value):
        return [
            (line, normalized)
            for line, normalized in self.content
            if re.search(rf"\b{value}\b", normalized, re.IGNORECASE)
        ]

    def _versePointer(self, value):
        if _VERSE_POINTER_DELIMITER in value:
            return map(int, value.split(_VERSE_POINTER_DELIMITER))
        return int(value), 0

    def search(self, value):
        return [self.display(line.strip()) for line, _ in self._filter(value)]

    def count(self, value):
        if target := value.lower():
            return sum(
                normalized.lower().count(target)
                for _, normalized in self._filter(value)
            )
        return 0

    def _parseArgs(self, args):
        match args:
            case [book]:
                return self.book(book)
            case [book, value]:
                match value.split(_VERSE_SLICE_DELIMITER):
                    case [chapter]:
                        return self.chapter(book, int(chapter))
                    case [chapter, verse]:
                        if verse.endswith(_VERSE_CONTINUATION_DELIMITER):
                            verse = (
                                int(verse[: verse.index(_VERSE_CONTINUATION_DELIMITER)])
                                - 1
                            )
                            return self.chapter(book, int(chapter))[verse:]
                        match verse.split(_VERSE_RANGE_DELIMITER):
                            case [start]:
                                start, before = self._versePointer(start)
                                return self.chapter(book, int(chapter))[
                                    int(start) - (before + 1) : int(start)
                                ]
                            case [start, end]:
                                start, before = self._versePointer(start)
                                end, after = self._versePointer(end)
                                return self.chapter(book, int(chapter))[
                                    int(start) - (before + 1) : end + after
                                ]
            case [book, chapter, verse]:
                return self.verse(book, chapter, verse)
        return None

    def parse(self, args):
        ref_args = {args[n : n + 2] for n in range(0, len(args), 2)}
        result = [self._parseArgs(arg) for arg in ref_args]
        return itertools.chain.from_iterable(result)
