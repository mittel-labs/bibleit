from __future__ import annotations

import argparse
from dataclasses import replace
import html
import os
import re
import sys
from typing import Iterable, Sequence

from rapidfuzz import fuzz, process
from unidecode import unidecode

from bibleit import translation
from bibleit.config import config_value
from bibleit.navigation import NavigationState, parse_navigation_ref

RANGE_RE = re.compile(r"^(?P<start>.+?)(?:\s*[-–]\s*(?P<end>\d+))$")
TAG_RE = re.compile(r"<[^>]+>")
DEFAULT_TRANSLATION_SLUG = "KJV"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _run_tui()

    parser = _parser()
    namespace = parser.parse_args(args)

    if namespace.tui:
        return _run_tui()

    if namespace.live is not None:
        return _run_live(_live_values(namespace.live, parser))

    if namespace.list_translations:
        return _print_translations()

    if not namespace.reference:
        parser.error("reference is required unless --tui or --list-translations is used")

    reference = " ".join(namespace.reference)
    slugs = _translation_slugs(namespace.translation)

    if not slugs:
        slugs = [_default_translation_slug()]

    try:
        rows = list(_read_reference(reference, slugs, keep_strongs=namespace.strongs))
    except (LookupError, RuntimeError, ValueError) as exc:
        print(f"bibleit: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print(f"bibleit: no verses found for {reference}", file=sys.stderr)
        return 1

    print(_format_output(rows), end="")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibleit",
        description="Read Bible verses or open the bibleit terminal app.",
    )
    parser.add_argument(
        "reference",
        nargs="*",
        help="Reference to read, e.g. 'dani 9.2' or 'dani 9:2-15'.",
    )
    parser.add_argument(
        "-t",
        "--translation",
        action="append",
        default=[],
        help="Translation slug. Can be repeated or comma-separated, e.g. -t NVIPT,KJV.",
    )
    parser.add_argument(
        "--list-translations",
        action="store_true",
        help="List installed translations and exit.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Open the terminal app even when other arguments are present.",
    )
    parser.add_argument(
        "--strongs",
        action="store_true",
        help="Keep Strong's numbers in verse output.",
    )
    parser.add_argument(
        "-l",
        "--live",
        nargs="*",
        metavar="HOST_PORT",
        help="Serve live endpoint, optionally overriding host and port: --live 0.0.0.0 8000.",
    )
    return parser


def _run_tui() -> int:
    from bibleit.app import Bibleit

    Bibleit().run()
    return 0


def _live_values(values: Sequence[str], parser: argparse.ArgumentParser) -> Sequence[str]:
    if len(values) not in (0, 2):
        parser.error("--live expects HOST PORT")
    return values


def _run_live(values: Sequence[str] = ()) -> int:
    from bibleit import live

    host = values[0] if len(values) == 2 else None
    port = values[1] if len(values) == 2 else None
    live.main(host=host, port=port)
    return 0


def _translation_slugs(values: Sequence[str]) -> list[str]:
    slugs: list[str] = []
    for value in values:
        slugs.extend(slug.strip() for slug in value.split(",") if slug.strip())
    return slugs


def _default_translation_slug() -> str:
    configured = os.getenv("BIBLEIT_TRANSLATION") or config_value("DEFAULT_TRANSLATION")
    if configured:
        return configured

    installed = [slug for slug, header in translation.get_installed().items() if header is not None]
    if installed:
        return min(installed)

    return DEFAULT_TRANSLATION_SLUG


def _read_reference(
    reference: str,
    slugs: Sequence[str],
    keep_strongs: bool = False,
) -> Iterable[tuple[str, list[str]]]:
    multiple = len(slugs) > 1
    for slug in slugs:
        resolved_slug = _resolve_translation_slug(slug)
        with translation.open(resolved_slug) as translation_:
            ref = parse_cli_ref(reference, translation_)
            lines = [_clean_row(value.decode(), keep_strongs=keep_strongs) for value in translation_.read(ref)]
            if multiple:
                yield resolved_slug, lines
            else:
                yield "", lines


def _resolve_translation_slug(value: str) -> str:
    normalized = _normalize(value)
    available = translation.get_translation_available(value)
    if available is not None and translation.is_installed(available.slug):
        return available.slug

    installed_slugs = [
        path.stem for path in translation.TRANSLATIONS_DIR.glob(translation.TRANSLATION_FILE.format(name="*"))
    ]
    for slug in installed_slugs:
        if _normalize(slug) == normalized:
            return slug

    installed = {slug: translation.get_translation_available(slug) for slug in installed_slugs}
    installed = {slug: header for slug, header in installed.items() if header is not None}

    if not installed:
        raise LookupError("no translations installed; open bibleit and add a translation first")

    candidates = {slug: f"{slug} {header.name}" for slug, header in installed.items()}
    prefix_matches = [slug for slug, label in candidates.items() if _normalize(label).startswith(normalized)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    scored = process.extractOne(
        normalized,
        candidates,
        processor=_normalize,
        scorer=fuzz.WRatio,
        score_cutoff=72,
    )
    if scored:
        _, _, slug = scored
        return slug

    raise LookupError(f"translation not installed: {value}")


def parse_cli_ref(reference: str, translation_: translation.Translation) -> translation.TranslationRef:
    command = reference.strip()
    if not command:
        raise ValueError("empty reference")

    if match := re.fullmatch(r"(.+?)\s+(\d+)", command):
        book_name, chapter = match.groups()
        bookid = translation_.resolve_bookid(book_name)
        if not bookid:
            raise ValueError(f"Book not found: {book_name}")
        return translation.TranslationRef(bookid, int(chapter))

    range_match = RANGE_RE.fullmatch(command)
    if not range_match:
        return parse_navigation_ref(command, translation_, NavigationState())

    ref = parse_navigation_ref(range_match.group("start"), translation_, NavigationState())
    if ref.chapter is None or ref.verse_start is None:
        raise ValueError(f"range must include a chapter and verse: {reference}")

    verse_end = int(range_match.group("end"))
    if verse_end < ref.verse_start:
        raise ValueError(f"range end must be greater than or equal to start verse: {reference}")

    return replace(ref, verse_end=verse_end)


def _format_output(groups: Sequence[tuple[str, list[str]]]) -> str:
    output: list[str] = []
    for slug, lines in groups:
        if slug:
            output.append(f"{slug}\n")
        output.extend(f"{line}\n" for line in lines)
        if slug:
            output.append("\n")
    return "".join(output).rstrip() + "\n"


def _print_translations() -> int:
    installed = {slug: header for slug, header in translation.get_installed().items() if header is not None}
    if not installed:
        print("No translations installed.")
        return 0

    for slug, header in sorted(installed.items()):
        print(f"{slug}\t{header.name}")
    return 0


def _clean_row(value: str, keep_strongs: bool = False) -> str:
    if not keep_strongs:
        value = re.sub(r"<S>.*?</S>", "", value, flags=re.IGNORECASE | re.DOTALL)

    value = value.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    value = TAG_RE.sub("", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize(value: str) -> str:
    return unidecode(value).casefold().strip()
