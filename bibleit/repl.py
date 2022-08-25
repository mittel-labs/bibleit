import readline

from bibleit import command
from bibleit.context import Context
from bibleit import config

readline.set_history_length(config.history_length)

_ctx = Context()

print(config.welcome)

while True:
  if line := input(_ctx).strip():
    if result := command.eval(_ctx, *line.split()):
      print(result)