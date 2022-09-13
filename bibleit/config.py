from os import walk as _walk

# General
debug = True
color = False
label = False
application = "bibleit"
version = "0.0.1"
help = 'Type "help" for more information.'
welcome = f"""
    Welcome to {application} v{version}

    {help}
"""

# Bible
translation_dir = "translations"
available_bible = [
    f"{parent.replace('{}'.format(translation_dir), '')}/{version}"[1:]
    for parent, _, f in _walk(translation_dir)
    for version in f
]
default_bible = "nvi/pt"

# Repl
history_length = 1000
context_ps1 = ">"
