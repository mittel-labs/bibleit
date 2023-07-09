from bibleit import config
from bibleit.bible import Bible, BibleNotFound


BOLD = "\033[1m"
END = "\033[0m"


class Context:
    def __init__(self):
        self._notes = set()
        self.screen = None
        try:
            self.bible = [Bible(config.default_bible)]
        except BibleNotFound as e:
            print(e)
            self.bible = []

    def __repr__(self):
        return f"✝ {BOLD}{','.join(map(str,self.bible))}{config.context_ps1}{END} "

    @property
    def notes(self):
        return self._notes

    def add_note(self, value):
        self._notes.add(value)
