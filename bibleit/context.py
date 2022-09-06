import sys
import signal

from bibleit import config
from bibleit.bible import Bible


class Context:
    def __init__(self):
        self.bible = Bible(config.default_bible)

    def __repr__(self):
        return f"{self.bible}{config.context_ps1} "


def exit(signum, frame):
    print("\nGoodbye")
    sys.exit(0)


signal.signal(signal.SIGINT, exit)
