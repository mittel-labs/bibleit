from bibleit import config
from bibleit.bible import Bible


class Context:
    def __init__(self):
        self.bible = [Bible(config.default_bible)]

    def __repr__(self):
        return f"{','.join(map(str,self.bible))}{config.context_ps1} "
