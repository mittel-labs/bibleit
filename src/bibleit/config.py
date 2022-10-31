import importlib.resources
import bibleit.translations as _translations

# General
debug = False
color = False
label = False
application = "bibleit"
version = "0.0.7"
help = 'Type "help" for more information.'
welcome = f"""
    Welcome to {application} v{version}

    {help}
"""

# Bible
translation_dir = "translations"
available_bible = importlib.resources.contents(_translations)
default_bible = "nvi"

# Repl
history_length = 1000
context_ps1 = ">"
