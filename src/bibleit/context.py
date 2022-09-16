from bibleit import config
from bibleit.bible import Bible, BibleNotFound


class Context:
    def __init__(self):
        try:
            self.bible = [Bible(config.default_bible)]
        except BibleNotFound as e:
            print(e)
            self.bible = []

    def __repr__(self):
        return f"{','.join(map(str,self.bible))}{config.context_ps1} "
