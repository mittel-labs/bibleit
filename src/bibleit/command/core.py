import sys
from itertools import zip_longest as _zip

from bibleit import command as _command
from bibleit import config as _config


def help(ctx, *args):
    """Prints this help."""
    if args:
        match args:
            case ["help", *sub_command]:
                print(_config.help)
            case [name]:
                assert name not in sys.builtin_module_names and hasattr(
                    sys.modules[__name__], name
                ), f"command '{name}' not found"
                if target := getattr(sys.modules[__name__], name).__doc__:
                    print(target)
            case [name, sub_command]:
                module = _command.eval_module(name)
                print(getattr(module, sub_command).__doc__)
            case _:
                print(
                    "Error: You must use help for command and one sub-command only.\n\nhelp <command> [<sub-command>]"
                )
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
        set bible kjv"""
    return _command.eval(ctx, *args, module="set")


def ref(ctx, *args):
    """Search a reference(s) by chapters and verses.

    ref <book> [<chapter>[:<verse[-verse]>]]

    Examples:
        ref john 1             (gets full chapter)
        ref john 1:2           (gets chapter and verse)
        ref john 1:2+          (gets chapter and verse with starting)
        ref john 8:31-32       (gets verse range)
        ref john 8:31^2-32^2   (gets verse plus start end plus end)
        ref john 1:1 john 2:1  (gets multiple chapters and verses)"""
    assert args, "you should use ref <book> [<chapter>[:<verse[-verse]>]]"

    refs = [bible.parse(args) for bible in ctx.bible]
    result = "\n\n".join(
        "\n".join(verses) for verses in _zip(*refs, fillvalue="Reference not found")
    )
    return result if result else f"Reference '{' '.join(args)}' not found"


def search(ctx, *args):
    """Search one or more words.

    search <word [word2 [...]]>

    Examples:
        search Jesus
        search Lord
        search bread of life"""
    target = " ".join(args)
    assert target, "You should use search <word>"
    refs = [bible.search(target) for bible in ctx.bible]
    result = "\n\n".join("\n".join(verses) for verses in refs)
    return result


def count(ctx, *args):
    """Count how much words.

    count <word [word2 [...]]>

    Examples:
        count Jesus
        count Lord
        count bread of life"""
    target = " ".join(args)
    assert target, "you should use count <word>"
    if refs := [(bible.version, str(bible.count(target))) for bible in ctx.bible]:
        if len(refs) > 1:
            return "\n".join("\t".join(ref) for ref in refs)
        else:
            return refs[0][1]
    return None


def versions(ctx, *args):
    """List available Bible versions"""
    return "\n{}\n".format("\n".join(_config.available_bible))


def exit(ctx, *args):
    """Exits application."""
    print("\nGoodbye.")
    sys.exit(0)