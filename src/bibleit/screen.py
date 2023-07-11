import curses
import types

ESC_KEY = 27
EXIT_KEYS = [ord("q"), ord("Q"), ESC_KEY]


def init(ctx, result):
    ctx.screen = types.SimpleNamespace()
    ctx.screen.result = result
    ctx.screen.stdscr = curses.initscr()
    ctx.screen.stdscr.clear()
    curses.noecho()
    curses.cbreak()
    ctx.screen.stdscr.keypad(True)
    ctx.screen.stdscr.scrollok(True)
    curses.curs_set(0)
    ctx.screen.selected_idx = 0
    ctx.screen.max_y, ctx.screen.max_x = ctx.screen.stdscr.getmaxyx()
    ctx.screen.scroll_start = 0
    ctx.screen.visible_lines = (ctx.screen.max_y - 2) // max(curses.curs_set(0), 1)


def display(ctx):
    if not ctx.screen.result:
        close(ctx)
        return

    output = list(filter(None, ctx.screen.result.splitlines()))
    ctx.screen.total_lines = len(output)

    display_lines = [
        line for line in output[ctx.screen.scroll_start :] if line.strip()
    ][: ctx.screen.visible_lines]

    if ctx.screen.selected_idx < ctx.screen.scroll_start:
        ctx.screen.selected_idx = ctx.screen.scroll_start
    elif ctx.screen.selected_idx >= ctx.screen.scroll_start + ctx.screen.visible_lines:
        ctx.screen.selected_idx = ctx.screen.scroll_start + ctx.screen.visible_lines - 1

    ctx.screen.stdscr.clear()
    for i, line in enumerate(display_lines):
        if i == ctx.screen.selected_idx - ctx.screen.scroll_start:
            ctx.screen.stdscr.addstr(i, 0, line, curses.A_REVERSE)
        else:
            ctx.screen.stdscr.addstr(line)
        ctx.screen.stdscr.addstr("\n")

    key = ctx.screen.stdscr.getch()

    key_handlers = {
        curses.KEY_UP: handle_up,
        curses.KEY_DOWN: handle_down,
        curses.KEY_PPAGE: handle_page_up,
        curses.KEY_NPAGE: handle_page_down,
    }

    handler = key_handlers.get(key, None)
    if handler:
        handler(ctx, display_lines)
    elif key in EXIT_KEYS:
        close(ctx)


def handle_up(ctx, display_lines):
    if ctx.screen.selected_idx > 0:
        ctx.screen.selected_idx -= 1
        if ctx.screen.selected_idx < ctx.screen.scroll_start:
            ctx.screen.scroll_start = ctx.screen.selected_idx


def handle_down(ctx, display_lines):
    if ctx.screen.selected_idx < ctx.screen.total_lines - 1:
        if (
            ctx.screen.selected_idx - ctx.screen.scroll_start
            >= ctx.screen.visible_lines - 1
            or ctx.screen.selected_idx == len(display_lines) - 1
        ):
            ctx.screen.scroll_start += 1
        ctx.screen.selected_idx = min(
            ctx.screen.selected_idx + 1, ctx.screen.total_lines - 1
        )


def handle_page_up(ctx, display_lines):
    ctx.screen.selected_idx = max(0, ctx.screen.selected_idx - ctx.screen.visible_lines)
    ctx.screen.scroll_start = max(0, ctx.screen.scroll_start - ctx.screen.visible_lines)


def handle_page_down(ctx, display_lines):
    ctx.screen.selected_idx = min(
        ctx.screen.total_lines - 1,
        ctx.screen.selected_idx + ctx.screen.visible_lines,
    )
    ctx.screen.scroll_start = min(
        ctx.screen.scroll_start + ctx.screen.visible_lines,
        ctx.screen.total_lines - ctx.screen.visible_lines,
    )


def close(ctx):
    if ctx.screen:
        ctx.screen = None
    curses.echo()
    curses.nocbreak()
    curses.endwin()
