from bibleit import config
from bibleit.bible import Bible, BibleNotFound, BOLD, END


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
        line = f"{','.join(map(str,self.bible))}{config.context_ps1}"
        if config.bold:
            line = f"{BOLD}{line}{END}"
        return f"✝ {line} "

    @property
    def notes(self):
        return self._notes

    def add_note(self, value):
        self._notes.add(value)
