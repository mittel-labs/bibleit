from bibleit import config as _config
from os.path import exists as _file_exists


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
        assert _file_exists(
            f"{_config.translation_dir}/{target}"
        ), f"bible translation '{target}' not found. (available: {_config.available_bible})"
        ctx.bible = target
