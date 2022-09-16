import atexit
import readline
import sys
from pathlib import Path

from bibleit import command, config
from bibleit.context import Context

_HISTORY_FILE = Path.home() / ".bibleit_history"


class AutoCompleter:
    def __init__(self):
        self.options = list(command.eval_methods(command.eval_module("core")))
        _HISTORY_FILE.touch(exist_ok=True)
        readline.read_history_file(_HISTORY_FILE)
        atexit.register(self.save, readline.get_current_history_length())

    def save(self, prev):
        new = readline.get_current_history_length()
        readline.set_history_length(1000)
        readline.append_history_file(new - prev, str(_HISTORY_FILE))

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
        except Exception:
            return None


def run():
    print(config.welcome)

    ac = AutoCompleter()

    readline.set_completer(ac.complete)
    readline.set_history_length(config.history_length)
    readline.set_completer_delims(" \t\n;")
    readline.parse_and_bind("tab: complete")

    ctx = Context()

    while True:
        try:
            if line := input(ctx).strip():
                if (result := command.eval(ctx, *line.split())) is not None:
                    print(result)
        except KeyboardInterrupt:
            print("\n")
        except EOFError:
            sys.exit(0)


if __name__ == "__main__":
    run()
