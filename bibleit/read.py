import re

from bibleit import config as _config


def book(ctx, name):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(
            line for line in bible if re.search(rf"^{name}", line, re.IGNORECASE)
        ).rstrip()


def chapter(ctx, book, name):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(
            line
            for line in bible
            if re.search(rf"^{book}.* {name}:", line, re.IGNORECASE)
        ).rstrip()


def verse(ctx, book, chapter, verse):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(
            line
            for line in bible
            if re.search(rf"^{book}.* {chapter}:{verse} (.*)", line, re.IGNORECASE)
        ).rstrip()


def verseSlice(ctx, book, chapter, start, end):
    assert start < end, "Invalid verse slicing"
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        verses = "|".join(map(str, range(start, end + 1)))
        return "\n".join(
            line
            for line in bible
            if re.findall(rf"^{book}.* {chapter}:(?=({verses}))", line, re.IGNORECASE)
        ).rstrip()


def _filter(ctx, value):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return [line for line in bible if re.search(rf"\b{value}\b", line, re.IGNORECASE)]


def search(ctx, value):
    return "\n".join(_filter(ctx, value)).rstrip()


def count(ctx, value):
    if target := value.lower():
        return sum(line.lower().count(target) for line in _filter(ctx, value))
    return 0
