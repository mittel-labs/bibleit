from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import AsyncIterator, Callable

from unidecode import unidecode

from bibleit import translation
from bibleit.config import config_value, CONFIG_DIR
from bibleit.navigation import NavigationState, chapter_count_for, parse_navigation_ref

MODEL_SEARCH_DIR = CONFIG_DIR / "models"
VOSK_LOG_FILE = CONFIG_DIR / "recordings" / "vosk.debug.log"

CHAPTER_MARKERS = {
    "capitulo",
    "capitulos",
    "chapter",
    "chapters",
    "kapitel",
}
VERSE_MARKERS = {
    "verso",
    "versos",
    "versiculo",
    "versiculos",
    "verse",
    "verses",
    "vers",
}
CONTEXT_CONNECTORS = {
    "a",
    "as",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "and",
    "in",
    "of",
    "the",
    "to",
    "am",
    "an",
    "das",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "im",
    "und",
    "von",
    "zum",
    "zur",
}


class ListeningUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ListeningMatch:
    text: str
    command: str
    ref: translation.TranslationRef


def configured_model_path() -> Path | None:
    value = config_value("LISTENING_MODEL").strip()
    if not value:
        return None
    return Path(value).expanduser()


def available_model_paths() -> list[Path]:
    paths: list[Path] = []
    if MODEL_SEARCH_DIR.exists():
        paths.extend(path for path in MODEL_SEARCH_DIR.iterdir() if path.is_dir() and path.name.startswith("vosk-model"))
    return sorted(paths, key=lambda path: path.name.lower())


def spoken_reference_matches(
    text: str,
    translation_: translation.Translation,
    state: NavigationState | None = None,
) -> list[ListeningMatch]:
    candidates = spoken_reference_candidates(text)
    matches: list[ListeningMatch] = []
    seen: set[translation.TranslationRef] = set()

    for candidate in candidates:
        try:
            ref = parse_navigation_ref(candidate, translation_, state or NavigationState())
        except (RuntimeError, ValueError):
            continue

        if not _reference_exists(translation_, ref):
            continue

        if ref in seen:
            continue

        seen.add(ref)
        matches.append(ListeningMatch(text=text, command=candidate, ref=ref))

    return matches


def _reference_exists(
    translation_: translation.Translation,
    ref: translation.TranslationRef,
) -> bool:
    chapter_count = chapter_count_for(translation_, ref.bookid)
    if chapter_count is None:
        return False

    chapter = ref.chapter or 1
    verse = ref.verse_start or 1
    if chapter < 1 or chapter > chapter_count or verse < 1:
        return False

    cursor_verse = getattr(translation_, "cursor_verse", None)
    if cursor_verse is None:
        return True

    try:
        cursor = cursor_verse(translation.TranslationRef(ref.bookid, chapter, verse))
        return cursor.next() is not None
    except (RuntimeError, OSError, ValueError):
        return False


def spoken_reference_candidates(text: str) -> list[str]:
    tokens = _spoken_tokens(text)
    candidates: list[str] = _contextual_chapter_verse_candidates(tokens)

    for index, token in enumerate(tokens):
        if not _is_number_token(token):
            continue

        next_number_index = _next_number_index(tokens, index + 1)
        if next_number_index is None:
            continue

        chapter = token
        verse = tokens[next_number_index]
        book_end = index

        while book_end > 0 and tokens[book_end - 1] in CHAPTER_MARKERS | VERSE_MARKERS:
            book_end -= 1

        for start in range(max(0, book_end - 7), book_end):
            book_tokens = tokens[start:book_end]
            if not book_tokens:
                continue

            if any(_is_noise_token(value) for value in book_tokens):
                continue

            book = " ".join(book_tokens)
            candidates.append(f"{book} {chapter}:{verse}")

    return _unique(candidates)


def _contextual_chapter_verse_candidates(tokens: list[str]) -> list[str]:
    candidates: list[str] = []

    for chapter_marker, token in enumerate(tokens):
        if token not in CHAPTER_MARKERS:
            continue

        chapter_index = _next_number_index(tokens, chapter_marker + 1)
        if chapter_index is None:
            continue

        verse_marker = _next_verse_marker_index(tokens, chapter_index + 1)
        if verse_marker is None:
            continue

        verse_index = _next_number_index(tokens, verse_marker + 1)
        if verse_index is None:
            continue

        chapter = tokens[chapter_index]
        verse = tokens[verse_index]
        for book in _contextual_book_candidates(tokens[chapter_index + 1 : verse_marker]):
            candidates.append(f"{book} {chapter}:{verse}")

    return candidates


def _next_verse_marker_index(tokens: list[str], start: int) -> int | None:
    for index in range(start, len(tokens)):
        if tokens[index] in VERSE_MARKERS:
            return index
    return None


def _contextual_book_candidates(tokens: list[str]) -> list[str]:
    start = 0
    end = len(tokens)
    while start < end and _is_context_connector(tokens[start]):
        start += 1
    while end > start and _is_context_connector(tokens[end - 1]):
        end -= 1

    book_tokens = tokens[start:end]
    if not book_tokens:
        return []

    candidates = [" ".join(book_tokens)]
    for index in range(1, len(book_tokens)):
        if _is_context_connector(book_tokens[index - 1]):
            candidates.append(" ".join(book_tokens[index:]))

    return candidates


def _is_context_connector(token: str) -> bool:
    return token in CONTEXT_CONNECTORS


class VoskListener:
    def __init__(
        self,
        model_path: Path | None = None,
        *,
        sample_rate: int = 16000,
    ) -> None:
        self.model_path = model_path or configured_model_path()
        self.sample_rate = sample_rate

    async def matches(
        self,
        translation_: translation.Translation,
        state: NavigationState,
        on_text: Callable[[str], None] | None = None,
    ) -> AsyncIterator[ListeningMatch]:
        model_path = self._model_path()
        sd, model_class, recognizer_class = _audio_modules()
        audio_queue = _audio_queue()

        model, recognizer = await asyncio.to_thread(
            _build_recognizer,
            model_class,
            recognizer_class,
            model_path,
            self.sample_rate,
        )

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=_audio_callback(audio_queue),
        ):
            async for text in _recognized_texts(recognizer, audio_queue):
                if on_text is not None:
                    on_text(text)
                for match in spoken_reference_matches(text, translation_, state):
                    yield match

    def _model_path(self) -> Path:
        if self.model_path is None:
            raise ListeningUnavailable("Set LISTENING_MODEL in Config first")

        if not self.model_path.exists():
            raise ListeningUnavailable(f"Listening model not found: {self.model_path}")

        return self.model_path


def _audio_modules():
    try:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
    except ModuleNotFoundError as error:
        raise ListeningUnavailable("Listening dependencies are missing; reinstall bibleit") from error

    SetLogLevel(0)
    return sd, Model, KaldiRecognizer


def _build_recognizer(model_class, recognizer_class, model_path: Path, sample_rate: int):  # noqa: ANN001
    with _vosk_debug_log(stamp=True):
        model = model_class(str(model_path))
        return model, recognizer_class(model, sample_rate)


@contextlib.contextmanager
def _vosk_debug_log(stamp: bool = False):
    VOSK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with VOSK_LOG_FILE.open("a", encoding="utf-8") as log:
        if stamp:
            log.write(f"\n--- bibleit listening {datetime.now().isoformat(timespec='seconds')} ---\n")
            log.flush()
        stderr_fd = os.dup(2)
        try:
            os.dup2(log.fileno(), 2)
            yield
        finally:
            os.dup2(stderr_fd, 2)
            os.close(stderr_fd)


def _audio_queue() -> asyncio.Queue[bytes]:
    return asyncio.Queue(maxsize=8)


def _audio_callback(audio_queue: asyncio.Queue[bytes]):
    loop = asyncio.get_running_loop()

    def callback(indata, _frames, _time, status):  # noqa: ANN001
        if status:
            return
        chunk = bytes(indata)
        loop.call_soon_threadsafe(_put_latest, audio_queue, chunk)

    return callback


async def _recognized_texts(recognizer, audio_queue: asyncio.Queue[bytes]) -> AsyncIterator[str]:  # noqa: ANN001
    while True:
        chunk = await audio_queue.get()
        accepted = await asyncio.to_thread(_accept_waveform, recognizer, chunk)
        if not accepted:
            continue

        result = json.loads(await asyncio.to_thread(_recognizer_result, recognizer))
        text = str(result.get("text", "")).strip()
        if text:
            yield text


def _accept_waveform(recognizer, chunk: bytes) -> bool:  # noqa: ANN001
    with _vosk_debug_log():
        return bool(recognizer.AcceptWaveform(chunk))


def _recognizer_result(recognizer) -> str:  # noqa: ANN001
    with _vosk_debug_log():
        return str(recognizer.Result())


def _put_latest(queue: asyncio.Queue[bytes], chunk: bytes) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(chunk)


def _spoken_tokens(text: str) -> list[str]:
    normalized = unidecode(text).lower()
    words = re.findall(r"\d+|[a-z]+", normalized)
    tokens: list[str] = []
    index = 0

    while index < len(words):
        value, consumed = _consume_number(words, index)
        if value is not None:
            tokens.append(str(value))
            index += consumed
            continue

        tokens.append(words[index])
        index += 1

    return tokens


def _consume_number(words: list[str], start: int) -> tuple[int | None, int]:
    if words[start].isdigit():
        return int(words[start]), 1

    german_compound = _german_compound_number(words[start])
    if german_compound is not None:
        return german_compound, 1

    first = _NUMBER_WORDS.get(words[start])
    if first is None:
        return None, 1

    if first < 20:
        return first, 1

    total = first
    consumed = 1

    while start + consumed < len(words):
        word = words[start + consumed]
        if word in {"e", "and"}:
            consumed += 1
            continue

        value = _NUMBER_WORDS.get(word)
        if value is None:
            break

        if value >= 100:
            break

        total += value
        consumed += 1

        if value < 10:
            break

    return total, consumed


def _german_compound_number(word: str) -> int | None:
    match = re.fullmatch(
        r"(ein|eins|zwei|drei|vier|funf|sechs|sieben|acht|neun)und"
        r"(zwanzig|dreissig|vierzig|funfzig|sechzig|siebzig|achtzig|neunzig)",
        word,
    )
    if not match:
        return None

    ones, tens = match.groups()
    return _NUMBER_WORDS[ones] + _NUMBER_WORDS[tens]


def _next_number_index(tokens: list[str], start: int) -> int | None:
    for index in range(start, min(len(tokens), start + 5)):
        if _is_number_token(tokens[index]):
            return index
    return None


def _is_number_token(value: str) -> bool:
    return value.isdigit()


def _is_noise_token(value: str) -> bool:
    noise = {
        "abrir",
        "abre",
        "em",
        "no",
        "na",
        "open",
        "read",
        "lesen",
        "lies",
        "schlage",
        "aufschlagen",
    }
    return value in noise or value in CHAPTER_MARKERS or value in VERSE_MARKERS


def _unique(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


_NUMBER_WORDS = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezsseis": 16,
    "dezessete": 17,
    "dezassete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "dezanove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "null": 0,
    "ein": 1,
    "eins": 1,
    "eine": 1,
    "einen": 1,
    "einem": 1,
    "einer": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "funf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
    "elf": 11,
    "zwolf": 12,
    "dreizehn": 13,
    "vierzehn": 14,
    "funfzehn": 15,
    "sechzehn": 16,
    "siebzehn": 17,
    "achtzehn": 18,
    "neunzehn": 19,
    "zwanzig": 20,
    "dreissig": 30,
    "vierzig": 40,
    "funfzig": 50,
    "sechzig": 60,
    "siebzig": 70,
    "achtzig": 80,
    "neunzig": 90,
    "hundert": 100,
}
