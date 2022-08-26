import sys

from bibleit import config as _config
from bibleit import command as _command

def hello(ctx, *args):
    """Hello command."""
    return f"hello from command: {args}"

def version(ctx, *args):
    """Prints application version."""
    return _config.version

def help(ctx, *args):
    """Prints this help."""
    if args:
        match args:
            case ["help", *sub_command]:
                print(_config.help)
            case [name]:
                module = _command.eval_module(name)
                if target := module.__doc__:
                    print(target)
                elif target := getattr(module, name):
                    print(target.__doc__)
            case [name, sub_command]:
                module = _command.eval_module(name)
                print(getattr(module, sub_command).__doc__)
            case _:
                print("Error: You must use help for command and one sub-command only.\n\nhelp <command> [<sub-command>]\n")
    else:
        methods = sorted(
            f"{method.__name__:<20} {method.__doc__}" 
            for method in [getattr(ctx.module, name) for name in ctx.methods]
        )

        print(f"\n{_config.application} v{_config.version}", end="\n\n")
        print("\n".join(methods), end="\n\n")

def set(ctx, *args):
    """Configure a sub-command with a new value."""
    return _command.eval(ctx, *args, module="set")

def exit(ctx, *args):
    """Exits application."""
    sys.exit(0)