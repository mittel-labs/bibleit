import re

from bibleit import config as _config

def book(ctx, name):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(line for line in bible if re.search(f"^{name}", line, re.IGNORECASE)).rstrip()


def chapter(ctx, book, name):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(line for line in bible if re.search(f"^{book}.* {name}:", line, re.IGNORECASE)).rstrip()


def verse(ctx, book, chapter, verse):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(line for line in bible if re.search(f"^{book}.* {chapter}:{verse} (.*)", line, re.IGNORECASE)).rstrip()


def _filter(ctx, value):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return [line for line in bible if re.search(f"{value}", line, re.IGNORECASE)]


def search(ctx, value):
    return "\n".join(_filter(ctx, value)).rstrip()


def count(ctx, value):
    if target := value.lower():
        return sum(line.lower().count(target) for line in _filter(ctx, value))
    return 0
        