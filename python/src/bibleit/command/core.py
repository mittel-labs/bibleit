import sys
import webbrowser as _wb
import textwrap as _tw
from itertools import zip_longest as _zip

from bibleit import command as _command
from bibleit import config as _config
from bibleit import bible as _bible

from operator import attrgetter as _attrgetter

_ALIASES = {
    "!": "set",
    "@": "ref",
    "?": "help",
    "&": "search",
    "%": "count",
    "*": "note",
    "\\": "notes",
    "+": "plus",
    "-": "minus",
}


def _format_alias(name):
    if alias := next((alias for alias, cmd in _ALIASES.items() if cmd == name), None):
        return f"(alias: '{alias}')"
    return ""


def _format_lines(lines):
    linesep = "\n" * (_config.linesep + 1)
    if _config.flags.textwrap:
        lines = map(
            lambda x: linesep.join(x),
            map(lambda x: _tw.wrap(x, width=120, fix_sentence_endings=True), lines),
        )
    return linesep.join(lines)


def _ref_parse_bible(ctx, refs, term="Reference"):
    refs = [bible.ref_parse(refs) for bible in ctx.bible]
    return _format_lines(
        "\n".join(verses) for verses in _zip(*refs, fillvalue=f"{term} not found")
    )


def _ref_parse(ctx, bible_fn, target, term):
    if refs := max([bible_fn(bible)(target) for bible in ctx.bible], key=len):
        ctx.last_ref, result = refs[-1], _ref_parse_bible(ctx, refs, term)
        return result
    return f"{term} '{''.join(target)}' not found"


def _doc(hdoc, name):
    if hdoc and name:
        return hdoc.replace("@alias", _format_alias(name))


def _last_refs(ctx, range_fn):
    last_ref = getattr(ctx, "last_ref", None)
    if last_ref is not None:
        if refs := range_fn(last_ref):
            ctx.last_ref = min(max(-1, refs[-1]), len(ctx.bible[0].content))
            if result := _ref_parse_bible(ctx, refs):
                return result


def help(ctx, *args):
    """Prints this help. @alias"""
    if args:
        match args:
            case ["help", *sub_command]:
                print(_config.help)
            case [name]:
                assert name not in sys.builtin_module_names and hasattr(
                    sys.modules[__name__], name
                ), f"command '{name}' not found"
                if target := getattr(sys.modules[__name__], name).__doc__:
                    print(_doc(target, name))
            case [name, sub_command]:
                module = _command.eval_module(name)
                if target := getattr(module, sub_command).__doc__:
                    print(_doc(target, name))
            case _:
                print(
                    "Error: You must use help for command and one sub-command only.\n\nhelp <command> [<sub-command>]"
                )
    else:
        methods = sorted(
            f"{method.__name__:<20} {_doc(method.__doc__.splitlines()[0], method.__name__)}"
            for method in [getattr(ctx.module, name) for name in ctx.methods]
        )

        print(f"\n{_config.application} v{_config.version}", end="\n\n")
        print("\n".join(methods), end="\n\n")


def set(ctx, *args):
    """Configure a sub-command with a new value. @alias

    set <config> <value>

    Examples:
        set bible kjv"""
    return _command.eval(ctx, *args, module="set")


def ref(ctx, *args):
    """Search a reference(s) by chapters and verses. @alias

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
    """Search one or more words. @alias

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
    """Count how much words. @alias

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
    return _format_lines("\n".join(bible.chapters()) for bible in ctx.bible)


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
    """List all notes. @alias"""
    assert not args, "you should use only notes"
    return _format_lines(ctx.notes) if ctx.notes else None


def note(ctx, *args):
    """Adds a new note. @alias

    notes <string>"""
    target = " ".join(args)

    assert target, "you should use note <string>"
    ctx.add_note(target)
    return None


def plus(ctx, *args):
    """Get next verses. @alias

    plus <int>"""
    match args:
        case [n] if n.isdigit():
            n = int(n)
            return _last_refs(
                ctx, lambda last_ref: list(range(last_ref + 1, last_ref + n + 1))
            )
    raise AssertionError("you should use plus <int>")


def minus(ctx, *args):
    """Get previous verses. @alias

    minus <int>"""
    match args:
        case [n] if n.isdigit():
            n = int(n)
            return _last_refs(ctx, lambda last_ref: list(range(last_ref - n, last_ref)))
    raise AssertionError("you should use minus <int>")
