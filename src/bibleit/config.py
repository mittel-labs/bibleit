import sys

from types import SimpleNamespace

__this = sys.modules[__name__]

# General
application = "bibleit"
version = "0.0.25"
help = 'Type "help" for more information.'
welcome = f"""
    Welcome to {application} v{version}

    {help}
"""

# Bible
default_bible = "nvi"

# Config
flags = SimpleNamespace(
    debug=False, label=False, screen=False, textwrap=False, bold=False
)
flag_names = set(flags.__dict__)
linesep = 1

# Repl
history_length = 1000
context_ps1 = ">"


def set_flag(name: str, value: bool):
    setattr(flags, name, value)
