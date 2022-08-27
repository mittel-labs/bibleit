from os import walk as _walk

# General
debug = False
application="bibleit"
version="0.0.1"
help="Type \"help\" for more information."
welcome=f"""
    Welcome to {application} v{version}

    Type a search <chapter>[<verse>] to read your Bible. (e.g. john 8:16)
    {help}
"""

# Bible
translation_dir = "translations"
available_bible = [f"{parent.replace('{}'.format(translation_dir), '')}/{f[0]}"[1:] for parent, _, f in _walk(translation_dir)]
default_bible = "nvi/pt"


# Repl
history_length = 1000
context_ps1=">"