import functools
import re
import importlib.resources
import operator

from bibleit import config as _config
from bibleit import translations as _translations
from bibleit import normalize


_VERSE_SLICE_DELIMITER = ":"
_VERSE_RANGE_DELIMITER = "-"
_VERSE_CONTINUATION_DELIMITER = "+"
_VERSE_CONTINUATION_DEFAULT = f"1{_VERSE_CONTINUATION_DELIMITER}"
_VERSE_POINTER_DELIMITER = "^"
_SEARCH_MULTIPLE_WORDS_DELIMITER = "+"
_TRANSLATIONS_DIR = importlib.resources.files(_translations)
_MAX_VERSES = 200


def get_available_bibles():
    return sorted(map(operator.attrgetter("name"), _TRANSLATIONS_DIR.iterdir()))


class BibleNotFound(AssertionError):
    def __init__(self, version) -> None:
        super().__init__(f"Bible translation not found: {version}")
        self.version = version


class Bible:
    def __init__(self, version):
        self.version = version.lower()
        try:
            target = _TRANSLATIONS_DIR / self.version
            if not target.is_file():
                raise BibleNotFound(self.version)
            with target.open() as f:
                self.content = list(
                    enumerate((line.strip(), normalize.normalize(line)) for line in f)
                )
            self.display = functools.reduce(
                lambda f, g: lambda x: f(g(x)),
                [self.labeled],
                lambda x: x,
            )
        except ValueError as e:
            raise BibleNotFound(self.version) from e

    def __repr__(self):
        return self.version

    def __hash__(self):
        return hash(self.version)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.version == other.version

    def labeled(self, value):
        return f"({self.version})\t{value}" if _config.label else value

    def book(self, name):
        return [
            line
            for line, (_, normalized) in self.content
            if re.search(rf"^{name}", normalized, re.IGNORECASE)
        ]

    def chapter(self, book, name, verse):
        start, *end = verse.split(_VERSE_RANGE_DELIMITER)

        start = self._versePointer(start)

        if end:
            end = min(self._versePointer(end[0]), _MAX_VERSES)
            verse = "|".join(map(str, range(start, end + 1)))
        else:
            verse = start

        return [
            line
            for line, (_, normalized) in self.content
            if re.search(rf"^{book}.* {name}:({verse}) ", normalized, re.IGNORECASE)
        ]

    def chapters(self):
        names = {
            self.display(line[: re.search(r"\d+:\d+", line).start() - 1]): None
            for n, (line, _) in self.content
        }
        return names.keys()

    def ref(self, book, ref):
        target_ref = normalize.normalize_ref(ref).split(_VERSE_SLICE_DELIMITER)
        match target_ref:
            case [chapter, *verses]:
                verse = "".join(verses) or _VERSE_CONTINUATION_DEFAULT
                if verse.endswith(_VERSE_CONTINUATION_DELIMITER):
                    verse = f"{verse.removesuffix(_VERSE_CONTINUATION_DELIMITER)}-{_MAX_VERSES}"
                return self.chapter(book, chapter, verse)
            case []:
                return self.book(book)

    def _filter(self, *values):
        return [
            (line, normalized)
            for line, (_, normalized) in self.content
            if all(
                re.search(rf"\b{value}s??\b", normalized, re.IGNORECASE)
                for value in values
            )
        ]

    def _versePointer(self, value):
        if _VERSE_POINTER_DELIMITER in value:
            current, *adjustment = map(int, str(value).split(_VERSE_POINTER_DELIMITER))

            if adjustment:
                current += adjustment[0]

            return current
        return int(value)

    def search(self, value):
        return [
            line
            for line, _ in self._filter(*value.split(_SEARCH_MULTIPLE_WORDS_DELIMITER))
        ]

    def count(self, value):
        if target := value.lower():
            return sum(
                normalized.count(target) for _, normalized in self._filter(value)
            )
        return 0

    def refs(self, args):
        target = None
        match args:
            case [number, book, ref] if number.isdigit():
                target = self.ref(f"{number} {book}", ref)
            case [book, ref]:
                if book and book.isdigit():
                    target = self.book(f"{book} {ref}")
                target = self.ref(book, ref)
            case [book]:
                target = self.book(book)
        return target

    def ref_parse(self, args):
        return [self.display(self.content[line][1][0]) for line in args]
