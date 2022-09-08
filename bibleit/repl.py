import readline
import sys
import atexit

from bibleit import command
from bibleit.context import Context
from bibleit import config

from pathlib import Path


_ctx = Context()
_histfile = Path.home() / ".bibleit_history"


class AutoCompleter:
    def __init__(self):
        self.options = list(command.eval_methods(command.eval_module("core")))
        _histfile.touch(exist_ok=True)
        readline.read_history_file(_histfile)
        atexit.register(self.save, readline.get_current_history_length())

    def save(self, prev):
        new = readline.get_current_history_length()
        readline.set_history_length(1000)
        readline.append_history_file(new - prev, str(_histfile))

    def complete(self, text, state):
        try:
            if state == 0:
                if line := readline.get_line_buffer().split():
                    module = command.eval_module(line[0])
                    self.options = list(command.eval_methods(module))

            if text:
                self.matches = [s for s in self.options if s and s.startswith(text)]
                return self.matches[state]

            return self.options[state]
        except Exception as e:
            return None


def run():
    print(config.welcome)

    ac = AutoCompleter()

    readline.set_completer(ac.complete)
    readline.set_history_length(config.history_length)
    readline.set_completer_delims(" \t\n;")
    readline.parse_and_bind("tab: complete")

    while True:
        try:
            if line := input(_ctx).strip():
                if (result := command.eval(_ctx, *line.split())) is not None:
                    print(result)
        except EOFError:
            sys.exit(0)


if __name__ == "__main__":
    run()
