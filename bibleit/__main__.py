import sys

args = sys.argv[1:]

if args:
    from bibleit import command, context

    if result := command.eval(context.Context(), *args):
        print(result)
else:
    from bibleit import repl

    repl.run()
