from bibleit import config as _config
from bibleit.bible import Bible as _Bible
from operator import attrgetter


def debug(ctx, value):
    """Configure debug config

    set debug <true|false>"""
    if target := value.lower():
        assert target in [
            "true",
            "false",
        ], "value must be a boolean value (set debug <true|false>)"
        _config.debug = target == "true"


def bible(ctx, *args):
    """Configure bible one or more translation

    set bible <translation[, translation[, ...]]>
    
    Examples:
        set bible kjv
        set bible acf, nvi/pt"""
    translations = [value for arg in args for value in arg.split(",") if value]
    ctx.bible = sorted(
        {_Bible(translation.lower()) for translation in translations},
        key=attrgetter("version"),
    )
