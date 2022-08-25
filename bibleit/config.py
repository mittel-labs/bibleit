# General
debug = False
default_translation = "kjv"
application="bibleit"
version="0.0.1"
help="Type \"help\" for more information."
welcome=f"""
    Welcome to {application} v{version}
    Type a <chapter>[<verse>] to read your Bible. (e.g. john 8:16)
    {help}
"""

# Repl
history_length = 1000
context_ps1=">"