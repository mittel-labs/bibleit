from bibleit.command import args as bargs, set
from bibleit import repl, context, config

_FLAG_PREFIX = "flag_"

args = bargs.parser.parse_args()


def get_active_flags(ctx):
    for flag in (
        flag.removeprefix(_FLAG_PREFIX)
        for flag in dir(ctx)
        if flag.startswith(_FLAG_PREFIX)
    ):
        if getattr(args, f"{_FLAG_PREFIX}{flag}"):
            yield flag


ctx = context.Context()

if args.bible:
    set.bible(ctx, ",".join(args.bible))

if args.linesep is not None:
    set.linesep(ctx, str(args.linesep))

for flag in get_active_flags(args):
    config.set_flag(flag, True)

if args.repl:
    ctx.__main__ = "__main__"
    repl.run(ctx)
else:
    if args.args:
        repl.eval(ctx, " ".join(args.args))
    else:
        bargs.parser.print_help()
