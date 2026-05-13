from __future__ import annotations
import requests
import json
from pathlib import Path
from operator import attrgetter
from dataclasses import dataclass
from functools import cached_property
from typing import Optional
from functools import cache

from unidecode import unidecode

from ctypes import (
    c_uint8,
    c_uint32,
    byref,
)
from bibleit._ffi import (
    libbibleit,
    BidxRef,
    BidxIter,
    BidxRecordView,
    BtRecordView,
    BtView,
)

TIMEOUTS = (3, 10)
TRANSLATIONS_DIR = Path.home() / ".bibleit"
TRANSLATION_LANGUAGES_CONFIG_FILE_URI = (
    "https://raw.githubusercontent.com/mittel-labs/bibleit/refs/heads/main/config/languages.json"
)
TRANSLATION_BOOKS_CONFIG_FILE_URI = (
    "https://raw.githubusercontent.com/mittel-labs/bibleit/refs/heads/main/config/translations_books.json"
)
TRANSLATION_URIS = [
    "https://bolls.life/static/translations/{translation}.json",
    "https://raw.githubusercontent.com/mittel-labs/bibleit/refs/heads/main/config/{translation}.json",
]
TRANSLATION_LINE = "{book} {chapter}:{verse} {text}\n"
TRANSLATION_FILE = "{name}.bt"
TRANSLATION_INDEX_FILE = "{name}.bidx"
TRANSLATION_FILE_ENCODING = "utf-8"
TRANSLATION_CONFIG_FILE = "{name}.json"

TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)

DICTIONARIES_URI = "https://raw.githubusercontent.com/mittel-labs/bibleit/refs/heads/main/config/dictionaries.json"
DICTIONARY_URI = "https://bolls.life/static/dictionaries/{name}.json"
DICTIONARY_FILE = "{name}.dictionary.json"


@dataclass(frozen=True)
class TranslationChapter:
    bookid: int
    original_bookid: int
    name: str
    chronorder: int
    chapters: int


@dataclass(frozen=True)
class TranslationHeader:
    name: str
    slug: str
    chapters: dict[str, TranslationChapter]

    def __str__(self) -> str:
        return f"({self.slug}) {self.name}"

    def resolve_bookid(self, book_name: str):
        if found := self.chapters.get(unidecode(book_name)):
            return found.bookid


@dataclass(frozen=True)
class TranslationLanguage:
    name: str
    translations: list[TranslationHeader]


@dataclass(frozen=True)
class TranslationRef:
    bookid: int
    chapter: Optional[int] = None
    verse_start: Optional[int] = None
    verse_end: Optional[int] = None


@dataclass(frozen=True)
class StrongEntry:
    code: str
    lemma: str | None = None
    transliteration: str | None = None
    definition: str | None = None
    description: str | None = None


def get_config(name: str, uri: str) -> dict:
    cf = TRANSLATIONS_DIR / TRANSLATION_CONFIG_FILE.format(name=name)
    if not cf.exists():
        if r := requests.get(uri, timeout=TIMEOUTS):
            if r.status_code != 200:
                raise LookupError(f"failed to fetch config {name}: ({r.status_code} {r.text})")
            cf.write_bytes(r.content)
    with cf.open() as f:
        return json.load(f)


def get_languages_config():
    return get_config("languages", TRANSLATION_LANGUAGES_CONFIG_FILE_URI)


def get_translations_books(slug=None):
    tb = get_config("translations_books", TRANSLATION_BOOKS_CONFIG_FILE_URI)
    if slug is not None:
        return tb.get(slug)
    return tb


def _resolve_book_order(translation_book: dict):
    stb = sorted(translation_book, key=lambda b: b.get("bookid", 0))

    for nid, value in enumerate(stb, start=1):
        yield value | {"bookid": nid, "original_bookid": value.get("bookid", nid)}


def _map_to_translation(translation: dict) -> TranslationHeader:
    tb = get_translations_books(translation["short_name"])
    return TranslationHeader(
        name=translation["full_name"],
        slug=translation["short_name"],
        chapters={unidecode(b["name"]): TranslationChapter(**b) for b in _resolve_book_order(tb)},
    )


def get_dictionary_path(name: str) -> Path:
    return TRANSLATIONS_DIR / DICTIONARY_FILE.format(name=name)


def install_dictionary(name: str) -> Path:
    path = get_dictionary_path(name)

    if not path.exists():
        r = requests.get(
            DICTIONARY_URI.format(name=name),
            timeout=TIMEOUTS,
        )
        if r.status_code != 200:
            raise LookupError(f"failed to download dictionary {name}: {r.status_code}")
        path.write_bytes(r.content)
    return path


@cache
def get_translations_available():
    return {
        t["short_name"]: _map_to_translation(t) for language in get_languages_config() for t in language["translations"]
    }


@cache
def get_languages_available():
    translations = get_translations_available()

    return [
        TranslationLanguage(
            name=language["language"],
            translations=[translations.get(t["short_name"]) for t in language["translations"]],
        )
        for language in get_languages_config()
    ]


def get_installed() -> dict[str, TranslationHeader]:
    translations = map(attrgetter("stem"), TRANSLATIONS_DIR.glob(TRANSLATION_FILE.format(name="*")))
    return {slug: get_translations_available().get(slug) for slug in translations}


def is_installed(slug: str) -> bool:
    translation = TRANSLATIONS_DIR / TRANSLATION_FILE.format(name=slug)
    return translation.exists()


def install(slug: str) -> Path:
    translation = TRANSLATIONS_DIR / TRANSLATION_FILE.format(name=slug)
    if not translation.exists():
        translations_books = get_translations_books()
        if slug not in translations_books:
            raise ValueError(f"translation {slug} not found on translation books")
        translation_bolls, errors = [], []
        for target_uri in TRANSLATION_URIS:
            r = requests.get(target_uri.format(translation=slug), timeout=TIMEOUTS)
            if r.status_code == 200:
                translation_bolls = r.json()
                break
            errors.append(f"failed to fetch translation from {target_uri}: ({r.text})")
        if not translation_bolls and errors:
            err = LookupError(f"failed to fetch translation '{slug}'")
            for e in errors:
                err.add_note(e)
            raise err
        translation_book = {t["bookid"]: t["name"] for t in translations_books[slug]}
        translation_lines = {(t["book"], t["chapter"], t["verse"]): t["text"] for t in translation_bolls}
        lines = (
            f"{translation_book[book]} {chapter}:{verse} {translation_lines[(book, chapter, verse)]}\n"
            for book, chapter, verse in translation_lines
        )
        with translation.open("w", encoding=TRANSLATION_FILE_ENCODING) as f:
            f.writelines(lines)
    return translation


def uninstall(slug: str):
    index = TRANSLATIONS_DIR / TRANSLATION_INDEX_FILE.format(name=slug)
    if index.exists():
        index.unlink()
    translation = TRANSLATIONS_DIR / TRANSLATION_FILE.format(name=slug)
    if translation.exists():
        translation.unlink()


def get_index(slug: str) -> Path:
    translation = get(slug)
    index = TRANSLATIONS_DIR / TRANSLATION_INDEX_FILE.format(name=slug)
    if not index.exists():
        rc = libbibleit.bidx_create(index.as_posix().encode(), translation.as_posix().encode())
        if rc == -1 or rc == 2:
            raise RuntimeError(f"failed to create index ({slug=}, {rc=})")
    return index


def get(slug: str) -> Path:
    translation = TRANSLATIONS_DIR / TRANSLATION_FILE.format(name=slug)
    if not translation.exists():
        raise RuntimeError(f"translation not found: {slug}")
    return translation


def open(slug: str) -> Translation:
    if slug not in get_translations_available():
        raise ValueError("open failure: translation not found: {slug}")
    header = get_translations_available().get(slug)
    return Translation(header)


class Translation:
    def __init__(self, header: TranslationHeader):
        self.header = header
        translation = get(self.header.slug)
        fp = libbibleit.bt_open(translation.as_posix().encode())
        if not fp:
            raise RuntimeError(f"failed to open translation: {translation}")
        self._fp = fp
        self._translation = translation
        self._index = Index(self.header.slug)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (Translation, TranslationHeader)):
            return self.slug == other.slug
        if isinstance(other, str):
            return self.slug == other
        return False

    def __hash__(self):
        return hash(self.slug)

    def __repr__(self):
        return f"Translation({self.header.slug})"

    def close(self):
        if self._fp:
            libbibleit.bt_close(self._fp)
            self._fp = None
        self._index.close()
        return self.slug

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _read_offset(self, offset: int):
        v = BtRecordView()

        if libbibleit.bt_read_view(self._fp, c_uint32(offset), byref(v)) != 0:
            raise OSError("bt_read_view failed")

        return BtView(v.ptr, v.len)

    def read(self, ref: TranslationRef) -> TranslationCursor:
        if ref.bookid:
            if ref.chapter:
                if ref.verse_start:
                    if ref.verse_end:
                        return self.cursor_range(ref)
                    else:
                        return self.cursor_verse(ref)
                else:
                    return self.cursor_chapter(ref)
            else:
                return self.cursor_book(ref)

    @property
    def slug(self):
        return self.header.slug

    def cursor_chapter(self, ref: TranslationRef):
        return TranslationCursor(
            self._index.cursor_chapter(ref),
            self._fp,
        )

    def cursor_book(self, ref: TranslationRef):
        return TranslationCursor(
            self._index.cursor_book(ref),
            self._fp,
        )

    def cursor_verse(self, ref: TranslationRef):
        return TranslationCursor(
            self._index.cursor_verse(ref),
            self._fp,
        )

    def cursor_from(self, ref: TranslationRef):
        return TranslationCursor(
            self._index.cursor_from(ref),
            self._fp,
        )

    def cursor_range(self, ref: TranslationRef):
        return TranslationCursor(
            self._index.cursor_range(ref),
            self._fp,
        )

    def cursor_all(self):
        return TranslationCursor(
            self._index.cursor_all(),
            self._fp,
        )

    def resolve_bookid(self, book_name: str):
        return self.header.resolve_bookid(book_name)

    @cached_property
    def strongs(self) -> dict[str, StrongEntry]:
        path = install_dictionary("SCGES")

        with path.open(encoding="utf-8") as f:
            raw = json.load(f)

        entries: dict[str, StrongEntry] = {}

        for value in raw:
            code = str(value.get("topic", "")).upper().strip()

            if not code:
                continue

            entries[code] = StrongEntry(
                code=code,
                lemma=value.get("lexeme"),
                transliteration=value.get("transliteration"),
                definition=value.get("short_definition"),
                description=value.get("definition"),
            )

        return entries


class TranslationCursor:
    __slots__ = ("_cur", "_fp", "_v")

    def __init__(self, index_cursor, fp):
        self._cur = index_cursor
        self._fp = fp
        self._v = BtRecordView()

    def __iter__(self):
        return self

    def __next__(self):
        off = self._cur.__next__()  # reuse index iterator
        return self._read_view(off)

    def next(self):
        off = self._cur.next()
        if off is None:
            return None
        return self._read_view(off)

    def previous(self):
        off = self._cur.previous()
        if off is None:
            return None
        return self._read_view(off)

    def _read_view(self, offset):
        if libbibleit.bt_read_view(self._fp, c_uint32(offset), byref(self._v)) != 0:
            raise RuntimeError("bt_read_view failed")

        return BtView(self._v.ptr, self._v.len)


class Index:
    def __init__(self, slug: str):
        self.slug = slug
        index = get_index(slug)
        h = libbibleit.bidx_open(index.as_posix().encode())
        if not h:
            raise OSError("bidx_open failed")
        self._h = h

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Index):
            return self.slug == other.slug
        if isinstance(other, str):
            return self.slug == other
        return False

    def __hash__(self):
        return hash(self.slug)

    def __repr__(self):
        return f"Index({self.slug})"

    def close(self):
        if self._h:
            libbibleit.bidx_close(self._h)
            self._h = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def version(self) -> int:
        return int(libbibleit.bidx_version(self._h))

    @property
    def count(self) -> int:
        return int(libbibleit.bidx_count(self._h))

    def read(self, ref: TranslationRef) -> Optional[int]:
        ref = BidxRef(ref.bookid, ref.chapter, ref.verse_start)
        off = c_uint32()
        rc = libbibleit.bidx_read(self._h, ref, byref(off))
        if rc == 0:
            return int(off.value)
        if rc == 1:
            return None
        raise RuntimeError("offset lookup error")

    def cursor_chapter(self, ref: TranslationRef):
        it = BidxIter()

        if libbibleit.bidx_iter_init_chapter(byref(it), self._h, c_uint8(ref.bookid), c_uint8(ref.chapter)) != 0:
            raise RuntimeError("failed to init chapter cursor")

        return IndexCursor(self, it)

    def cursor_book(self, ref: TranslationRef):
        it = BidxIter()

        if libbibleit.bidx_iter_init_book(byref(it), self._h, c_uint8(ref.bookid)) != 0:
            raise RuntimeError("failed to init book cursor")

        return IndexCursor(self, it)

    def cursor_verse(self, ref: TranslationRef):
        it = BidxIter()

        r = BidxRef(ref.bookid, ref.chapter, ref.verse_start)

        if libbibleit.bidx_iter_init(byref(it), self._h, r) != 0:
            raise RuntimeError("failed to init verse cursor")

        return IndexCursor(self, it, stop=r)

    def cursor_from(self, ref: TranslationRef):
        it = BidxIter()

        r = BidxRef(ref.bookid, ref.chapter, ref.verse_start)

        if libbibleit.bidx_iter_init(byref(it), self._h, r) != 0:
            raise RuntimeError("failed to init cursor")

        return IndexCursor(self, it)

    def cursor_range(self, ref: TranslationRef):
        it = BidxIter()

        r_from = BidxRef(ref.bookid, ref.chapter, ref.verse_start)
        r_to = BidxRef(ref.bookid, ref.chapter, ref.verse_end)

        if libbibleit.bidx_iter_init(byref(it), self._h, r_from) != 0:
            raise RuntimeError("failed to init range cursor")

        return IndexCursor(self, it, stop=r_to)

    def cursor_all(self):
        it = BidxIter()

        if libbibleit.bidx_iter_init(byref(it), self._h, BidxRef(1, 1, 1)) != 0:
            raise RuntimeError("failed to init cursor_all")

        return IndexCursor(self, it)


class IndexCursor:
    __slots__ = ("_it", "_index", "_v", "_stop", "_done")

    def __init__(self, index, it, stop: BidxRef | None = None):
        self._index = index
        self._it = it
        self._v = BidxRecordView()
        self._stop = stop
        self._done = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._done:
            raise StopIteration

        rc = libbibleit.bidx_iter_next(byref(self._it), byref(self._v))
        if rc == 0:
            raise StopIteration
        if rc < 0:
            raise RuntimeError("iterator error")

        offset = int(libbibleit.bidx_view_offset(self._v))
        if self._stop is not None and (
            libbibleit.bidx_view_book(self._v) == self._stop.book
            and libbibleit.bidx_view_chapter(self._v) == self._stop.chapter
            and libbibleit.bidx_view_verse(self._v) == self._stop.verse
        ):
            self._done = True

        return offset

    def next(self):
        try:
            return self.__next__()
        except StopIteration:
            return None

    def previous(self):
        rc = libbibleit.bidx_iter_previous(byref(self._it), byref(self._v))
        if rc == 0:
            return None
        if rc < 0:
            raise RuntimeError("iterator error")

        return int(libbibleit.bidx_view_offset(self._v))
