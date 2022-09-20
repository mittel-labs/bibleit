import sys

from operator import attrgetter as _attrgetter

from bibleit import config as _config
from bibleit.bible import Bible as _Bible

_FLAGS_ON = ["true", "on"]
_FLAGS_OFF = ["false", "off"]
_FLAGS_TOGGLE = _FLAGS_ON + _FLAGS_OFF

_FLAGS = {"debug", "color", "label"}


def _flag(value):
    if value := value.lower():
        assert (
            value in _FLAGS_TOGGLE
        ), f"value must be a boolean value: <{'|'.join(_FLAGS_TOGGLE)}>"
        return value in _FLAGS_ON
    return False


for _flag_name in _FLAGS:

    def _flag_method(name):
        fn = lambda ctx, value: setattr(_config, name, _flag(value))
        fn.__doc__ = f"Configure {_flag_name} config\n\n    set {_flag_name} <{'|'.join(_FLAGS_TOGGLE)}>"
        return fn

    setattr(sys.modules[__name__], _flag_name, _flag_method(_flag_name))


def bible(ctx, *args):
    """Configure bible one or more translation

    set bible <translation[, translation[, ...]]>

    Examples:
        set bible kjv
        set bible acf, nvi/pt"""
    translations = [value for arg in args for value in arg.split(",") if value]
    ctx.bible = sorted(
        {_Bible(translation.lower()) for translation in translations},
        key=_attrgetter("version"),
    )
    _config.color = len(translations) > 1
