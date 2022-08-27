import readline
import sys

from bibleit import command
from bibleit.context import Context
from bibleit import config


readline.set_history_length(config.history_length)

_ctx = Context()

print(config.welcome)

while True:
  try:
    if line := input(_ctx).strip():
      if (result := command.eval(_ctx, *line.split())) is not None:
        print(result)
  except EOFError:
    sys.exit(0)