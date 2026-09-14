from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, TypeAlias

from bibleit.operator.errors import CommandValidationError


@dataclass(frozen=True)
class TranslationInfo:
    slug: str
    name: str
    installed: bool = True


@dataclass(frozen=True)
class TranslationLanguage:
    name: str
    translations: tuple[TranslationInfo, ...]


@dataclass(frozen=True)
class TranslationCatalogState:
    installed: tuple[str, ...]
    languages: tuple[TranslationLanguage, ...] = ()


@dataclass(frozen=True)
class Reference:
    bookid: int
    chapter: int
    verse: int
    book: str = ""

    @property
    def label(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}".strip()


@dataclass(frozen=True)
class OperatorState:
    translations: tuple[TranslationInfo, ...]
    active: str | None
    ref: Reference
    live: bool
    viewers: int
    viewer_counts: Mapping[str, int]
    connected: bool
    strongs: bool
    targets: tuple[str, ...]
    sequence: int

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["translations"] = [asdict(item) for item in self.translations]
        value["ref"]["reference"] = self.ref.label
        value["targets"] = list(self.targets)
        return value


@dataclass(frozen=True)
class VerseRow:
    bookid: int | None
    book: str
    chapter: int
    verse: int
    reference: str
    html: str
    text: str


@dataclass(frozen=True)
class VerseColumn:
    translation: str
    name: str
    index: int | None
    rows: tuple[VerseRow, ...]


@dataclass(frozen=True)
class VerseWindow:
    ref: Reference
    columns: tuple[VerseColumn, ...]


@dataclass(frozen=True)
class ResolveResult:
    candidates: tuple[str, ...]
    suggestion: str | None
    ref: Reference | None
    exists: bool
    error: str | None = None


@dataclass(frozen=True)
class SearchResult:
    reference: str
    text: str
    bookid: int
    chapter: int
    verse: int


@dataclass(frozen=True)
class StateEvent:
    state: OperatorState
    type: str = field(default="state", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "state": self.state.to_dict()}


@dataclass(frozen=True)
class InstallEvent:
    slug: str
    state: str
    error: str | None = None
    type: str = field(default="install", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


OperatorEvent: TypeAlias = StateEvent | InstallEvent


@dataclass(frozen=True)
class Goto:
    value: str


@dataclass(frozen=True)
class GotoReference:
    bookid: int
    chapter: int = 1
    verse: int = 1
    history: bool = False


@dataclass(frozen=True)
class NextVerse:
    pass


@dataclass(frozen=True)
class PreviousVerse:
    pass


@dataclass(frozen=True)
class NextChapter:
    pass


@dataclass(frozen=True)
class PreviousChapter:
    pass


@dataclass(frozen=True)
class ChapterStart:
    pass


@dataclass(frozen=True)
class ChapterEnd:
    pass


@dataclass(frozen=True)
class OpenTranslation:
    slug: str


@dataclass(frozen=True)
class CloseTranslation:
    slug: str


@dataclass(frozen=True)
class SetActive:
    slug: str


@dataclass(frozen=True)
class SetLive:
    live: bool


@dataclass(frozen=True)
class SetStrongs:
    strongs: bool


OperatorCommand: TypeAlias = (
    Goto
    | GotoReference
    | NextVerse
    | PreviousVerse
    | NextChapter
    | PreviousChapter
    | ChapterStart
    | ChapterEnd
    | OpenTranslation
    | CloseTranslation
    | SetActive
    | SetLive
    | SetStrongs
)


def _params(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CommandValidationError("Command params must be an object")
    return dict(value)


def _only(name: str, params: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise CommandValidationError(f"Unexpected params for {name}: {', '.join(sorted(unknown))}")


def _string(name: str, params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandValidationError(f"{name}.{key} must be a non-empty string")
    return value.strip()


def _integer(name: str, params: dict[str, Any], key: str, default: int | None = None) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CommandValidationError(f"{name}.{key} must be a positive integer")
    return value


def _boolean(name: str, params: dict[str, Any], key: str, default: bool | None = None) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise CommandValidationError(f"{name}.{key} must be a boolean")
    return value


def parse_command(name: str, value: Mapping[str, Any] | None = None) -> OperatorCommand:
    """Validate an untyped transport payload and return a typed command."""
    params = _params(value)
    empty = {
        "next_verse": NextVerse,
        "previous_verse": PreviousVerse,
        "next_chapter": NextChapter,
        "previous_chapter": PreviousChapter,
        "chapter_start": ChapterStart,
        "chapter_end": ChapterEnd,
    }
    if name in empty:
        _only(name, params, set())
        return empty[name]()
    if name == "goto":
        _only(name, params, {"value"})
        return Goto(_string(name, params, "value"))
    if name == "goto_ref":
        _only(name, params, {"bookid", "chapter", "verse", "history"})
        return GotoReference(
            _integer(name, params, "bookid"),
            _integer(name, params, "chapter", 1),
            _integer(name, params, "verse", 1),
            _boolean(name, params, "history", False),
        )
    string_commands = {
        "open_translation": OpenTranslation,
        "close_translation": CloseTranslation,
        "set_active": SetActive,
    }
    if name in string_commands:
        _only(name, params, {"slug"})
        return string_commands[name](_string(name, params, "slug"))
    if name == "set_live":
        _only(name, params, {"live"})
        return SetLive(_boolean(name, params, "live"))
    if name == "set_strongs":
        _only(name, params, {"strongs"})
        return SetStrongs(_boolean(name, params, "strongs"))
    raise CommandValidationError(f"Unknown command: {name}")
