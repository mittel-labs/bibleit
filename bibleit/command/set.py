"""Set a context value for a sub-command

 set <sub-command> <value> (e.g set debug true)
"""

from bibleit import config

def debug(ctx, value):
    """Configure debug config

 set debug <true|false>
"""
    if target := value.lower():
        assert target in ["true", "false"], "value must be a boolean value (set debug <true|false>)"
        config.debug = target == "true"