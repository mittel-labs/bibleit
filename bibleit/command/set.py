from bibleit import config as _config
from bibleit.bible import Bible as _Bible
from operator import attrgetter as _attrgetter


_FLAGS_ON = ["true", "on"]
_FLAGS_OFF = ["false", "off"]
_FLAGS = _FLAGS_ON + _FLAGS_OFF

def _flag(value):
    if value := value.lower():
        assert value in _FLAGS, f"value must be a boolean value ({', '.join(_FLAGS)})"
        return value in _FLAGS_ON
    return False


def debug(ctx, value):
    """Configure debug config

    set debug <true|false>"""
    _config.debug = _flag(value)


def bible(ctx, *args):
    """Configure bible one or more translation

    set bible <translation[, translation[, ...]]>

    Examples:
        set bible kjv
        set bible acf, nvi/pt"""
    translations = [value for arg in args for value in arg.split(",") if value]
    if len(translations) > 1:
        _config.color = True
    ctx.bible = sorted(
        {_Bible(translation.lower()) for translation in translations},
        key=_attrgetter("version"),
    )


def color(ctx, value):
    """Configure color mode

    set color <true|false>"""
    _config.color = _flag(value)
