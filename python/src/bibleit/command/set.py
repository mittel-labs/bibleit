import sys

from operator import attrgetter as _attrgetter

from bibleit import config as _config
from bibleit.bible import Bible as _Bible

_FLAGS_ON = ["true", "on"]
_FLAGS_OFF = ["false", "off"]
_FLAGS_TOGGLE = _FLAGS_ON + _FLAGS_OFF


def _flag(value):
    if value := value.lower():
        assert (
            value in _FLAGS_TOGGLE
        ), f"value must be a boolean value: <{'|'.join(_FLAGS_TOGGLE)}>"
        return value in _FLAGS_ON
    return False


for _flag_name in _config.flag_names:

    def _flag_method(name):
        def fn(ctx, value: bool):
            _config.set_flag(name, _flag(value))

        fn.__doc__ = f"Configure {_flag_name} config\n\n    set {_flag_name} <{'|'.join(_FLAGS_TOGGLE)}>"
        return fn

    setattr(sys.modules[__name__], _flag_name, _flag_method(_flag_name))


def bible(ctx, *args):
    """Configure bible one or more translation

    set bible <translation[, translation[, ...]]>

    Examples:
        set bible kjv
        set bible acf, nvi"""
    assert args, "you should use bible <translation[, translation[, ...]]>"
    translations = [value for arg in args for value in arg.split(",") if value]
    ctx.bible = sorted(
        {_Bible(translation.lower()) for translation in translations},
        key=_attrgetter("version"),
    )
    _config.flags.label = len(translations) > 1


def linesep(ctx, *args):
    """Configure line separation from results

    set linesep <int>

    Examples:
        set linesep 1
        set linesep 10"""
    value = "".join(args)
    if value.isdigit():
        value = int(value)
        assert 0 <= value <= 10, "line separation value must be a int between 0 and 10"
        _config.linesep = value
    else:
        raise AssertionError("line separation value should be an int")
