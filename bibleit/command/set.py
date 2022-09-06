from bibleit import config as _config
from bibleit.bible import Bible as _Bible


def debug(ctx, value):
    """Configure debug config

    set debug <true|false>"""
    if target := value.lower():
        assert target in [
            "true",
            "false",
        ], "value must be a boolean value (set debug <true|false>)"
        _config.debug = target == "true"


def bible(ctx, value):
    """Configure bible translation

    set bible <translation>"""
    if target := value.lower():
        ctx.bible = _Bible(target)
