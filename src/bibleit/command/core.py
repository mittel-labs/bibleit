import sys
import webbrowser as _wb
import textwrap
from itertools import zip_longest as _zip

from bibleit import command as _command
from bibleit import config as _config
from bibleit import bible as _bible

from operator import attrgetter as _attrgetter


def _format_lines(lines):
    if _config.textwrap:
        lines = map(
            lambda x: ("\n" * _config.linesep).join(x),
            map(lambda x: textwrap.wrap(x, width=120, fix_sentence_endings=True), lines),
        )
    return ("\n" * _config.linesep).join(lines)


def _ref_parse(ctx, bible_fn, target, term):
    refs = max([bible_fn(bible)(target) for bible in ctx.bible], key=len)
    refs = [bible.ref_parse(refs) for bible in ctx.bible]
    result = _format_lines(
        _format_lines(verses) for verses in _zip(*refs, fillvalue=f"{term} not found")
    )
    return result if result else f"{term} '{' '.join(target)}' not found"


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
        ref john 1:2           (get chapter and verse)
        ref john 1:2+          (get chapter and verses with starting)
        ref john 8:31-32       (get verses range)
        ref john 8:31^2-32^2   (get verses with extra)"""
    assert args, "you should use <book> [<chapter>[:<verse[-verse]>]]"

    return _ref_parse(ctx, _attrgetter("refs"), args, "Reference")


def search(ctx, *args):
    """Search one or more words.

    search <word [word2 [...]]>

    Examples:
        search Jesus            (search for all verses with Jesus)
        search bread of life    (search exact for all verses with "bread of life")
        search bread+Jesus      (search multiple words for all verses with bread and Jesus)
    """
    target = " ".join(args)
    assert target, "You should use search <word>"

    return _ref_parse(ctx, _attrgetter("search"), target, "Term")


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
            return _format_lines(f"({label}) {c}" for label, c in refs)
        else:
            return refs[0][1]
    return None


def chapters(ctx, *args):
    """Show the chapters.

    chapters"""
    return _format_lines(_format_lines(bible.chapters()) for bible in ctx.bible)


def version(ctx, *args):
    """Prints bibleit version"""
    return f"{_config.application} v{_config.version}"


def versions(ctx, *args):
    """List available Bible versions"""
    return _format_lines(_bible.get_available_bibles())


def exit(ctx, *args):
    """Exits application."""
    print("\nGoodbye.")
    sys.exit(0)


def blb(ctx, *args):
    """Blue Letter Bible search.

         blb <term [term2 [...]]>

         Examples:
             blb John 10:2
             blb bread of life
             blb sincer*
             blb (Jesus AND faith) NOT (love OR truth)

     How to Use the Bible Search:
         https://www.blueletterbible.org/help/bible_search.cfm

    https://www.blueletterbible.org | ©2022 Blue Letter Bible"""
    target = " ".join(args)
    assert target, "you should use blb <terms>"
    _wb.open(f"https://www.blueletterbible.org/search/preSearch.cfm?Criteria={target}")
    return None


def notes(ctx, *args):
    """List all notes."""
    return _format_lines(ctx.notes) if ctx.notes else None


def note(ctx, *args):
    """Adds a new note.

    notes <string>"""
    target = " ".join(args)

    assert target, "you should use notes <string>"
    ctx.add_note(target)
    return None
