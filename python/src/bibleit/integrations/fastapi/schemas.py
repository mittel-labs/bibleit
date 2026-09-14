from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bibleit.operator import OperatorError, parse_command


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TranslationRead(ApiModel):
    slug: str
    name: str
    installed: bool = True


class TranslationLanguageRead(ApiModel):
    name: str
    translations: list[TranslationRead]


class TranslationCatalogRead(ApiModel):
    installed: list[str]
    languages: list[TranslationLanguageRead]


class ReferenceRead(ApiModel):
    bookid: int
    chapter: int
    verse: int
    book: str
    reference: str


class OperatorStateRead(ApiModel):
    translations: list[TranslationRead]
    active: str | None
    ref: ReferenceRead
    live: bool
    viewers: int
    viewer_counts: dict[str, int]
    connected: bool
    strongs: bool
    targets: list[str]
    sequence: int


class VerseRowRead(ApiModel):
    bookid: int | None
    book: str
    chapter: int
    verse: int
    reference: str
    html: str
    text: str


class VerseColumnRead(ApiModel):
    translation: str
    name: str
    index: int | None
    rows: list[VerseRowRead]


class VersesRead(ApiModel):
    ref: ReferenceRead
    columns: list[VerseColumnRead]


class BookRead(ApiModel):
    bookid: int
    name: str
    chapters: int


class BooksRead(ApiModel):
    translation: str
    books: list[BookRead]


class ResolveRead(ApiModel):
    candidates: list[str]
    suggestion: str | None
    ref: ReferenceRead | None
    exists: bool
    error: str | None = None


class FindResultRead(ApiModel):
    reference: str
    text: str
    bookid: int
    chapter: int
    verse: int


class FindRead(ApiModel):
    translation: str
    results: list[FindResultRead]


class StrongRead(ApiModel):
    code: str
    lemma: str | None = None
    transliteration: str | None = None
    definition: str | None = None
    description: str | None = None


class CommandRequest(ApiModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self):
        try:
            parse_command(self.command, self.params)
        except OperatorError as error:
            raise ValueError(str(error)) from error
        return self


class InstallRead(ApiModel):
    slug: str
    state: Literal["installing", "removed"]


class ErrorRead(ApiModel):
    detail: str
