import sys
import signal

from bibleit import config

class Context:
  def __init__(self, context=config.context_ps1) -> None:
     self._context = context
     self.bible = config.default_bible
  
  def __repr__(self):
    return f"{self._context} "
  
  def __rshift__(self, a, b):
    self._context = a + b
  
  def print(self, result):
    if result:
        print(f"{self} {result}")

def exit(signum, frame):
  print("\nGoodbye")
  sys.exit(0)

signal.signal(signal.SIGINT, exit)
    