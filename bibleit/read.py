import re

from bibleit import config as _config

def book(ctx, name):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(line for line in bible if re.match(f"^{name[0:3]}", line, re.IGNORECASE))

def chapter(ctx, book, name):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(line for line in bible if re.match(f"^{book[0:3]}.* {name}:", line, re.IGNORECASE))

def verse(ctx, book, chapter, verse):
    with open(f"{_config.translation_dir}/{ctx.bible}") as bible:
        return "\n".join(line for line in bible if re.match(f"{book[0:3]}.* {chapter}:{verse} (.*)", line, re.IGNORECASE))