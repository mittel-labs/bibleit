import sys

from bibleit import config as _config
from bibleit import command as _command
from bibleit import read as _read


def help(ctx, *args):
    """Prints this help."""
    if args:
        match args:
            case ["help", *sub_command]:
                print(_config.help)
            case [name]:
                assert name not in sys.builtin_module_names and hasattr(sys.modules[__name__], name), f"command '{name}' not found"
                if target := getattr(sys.modules[__name__], name).__doc__:
                    print(target)
            case [name, sub_command]:
                module = _command.eval_module(name)
                print(getattr(module, sub_command).__doc__)
            case _:
                print("Error: You must use help for command and one sub-command only.\n\nhelp <command> [<sub-command>]")
    else:
        methods = sorted(
            f"{method.__name__:<20} {method.__doc__.splitlines()[0]}" 
            for method in [getattr(ctx.module, name) for name in ctx.methods]
        )

        print(f"\n{_config.application} v{_config.version}", end="\n\n")
        print("\n".join(methods), end="\n\n")


def set(ctx, *args):
    """Configure a sub-command with a new value.

    set <config> <value>

    Examples:
        set bible kjv 
"""
    return _command.eval(ctx, *args, module="set")


def ref(ctx, *args):
    """Search a reference by chapters and verses.

    ref <book> [<chapter>[:<verse>]]

    Examples:
        ref john 8:32
        ref Gen 1
        ref PSalm 23
"""
    assert args, "you should use ref <book> [<chapter>[:<verse>]]"
    result = None
    match args:
        case [book]:
            result = _read.book(ctx, book)
        case [book, value]:
            match value.split(":"):
                case [chapter]:
                    result = _read.chapter(ctx, book, int(chapter))
                case [chapter, verse]:
                    result = _read.verse(ctx, book, int(chapter), int(verse))
        case [book, chapter, verse]:
            result = _read.verse(ctx, book, chapter, verse)
    
    return result if result else f"Reference '{' '.join(args)}' not found"


def search(ctx, *args):
    """Search one or more words.

    search <word [word2 [...]]>

    Examples:
        search Jesus
        search Lord
        search bread of life
"""
    target = " ".join(args)
    assert target, "You should use search <word>"
    return _read.search(ctx, target)


def count(ctx, *args):
    """Count how much words.

    count <word [word2 [...]]>

    Examples:
        count Jesus
        count Lord
        count bread of life
"""
    target = " ".join(args)
    assert target, "you should use count <word>"
    return _read.count(ctx, target)


def versions(ctx, *args):
    """List available Bible versions"""
    return "\n{}\n".format("\n".join(_config.available_bible).replace(ctx.bible, f"{ctx.bible} *"))


def exit(ctx, *args):
    """Exits application."""
    sys.exit(0)