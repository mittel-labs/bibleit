"""Bibleit package."""

try:
    from bibleit._version import __version__
except ModuleNotFoundError:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("bibleit")
    except PackageNotFoundError:
        __version__ = "0+unknown"
