from __future__ import annotations

from textual.binding import Binding


BIBLE_VIEW_BINDINGS = [
    Binding("tab", "next_translation", "Next Translation", show=False, priority=True),
    Binding("shift+tab", "previous_translation", "Previous Translation", show=False, priority=True),
    Binding("ctrl+tab", "next_translation", "Next Translation", show=False, priority=True),
    ("ctrl+t", "open_translations", "Translations"),
    ("ctrl+f", "open_find", "Find"),
    ("ctrl+g", "toggle_strongs", "Strongs"),
    ("ctrl+h", "toggle_history", "History"),
    ("ctrl+p", "open_config", "Config"),
    ("ctrl+l", "toggle_live", "Live"),
    ("ctrl+w", "close_pane", "Close Pane"),
    ("ctrl+m", "toggle_maximize", "Maximize"),
    ("ctrl+1", "maximize_translation(1)", "Maximize Translation 1"),
    ("ctrl+2", "maximize_translation(2)", "Maximize Translation 2"),
    ("ctrl+3", "maximize_translation(3)", "Maximize Translation 3"),
    ("ctrl+4", "maximize_translation(4)", "Maximize Translation 4"),
    ("ctrl+5", "maximize_translation(5)", "Maximize Translation 5"),
    ("ctrl+6", "maximize_translation(6)", "Maximize Translation 6"),
    ("ctrl+7", "maximize_translation(7)", "Maximize Translation 7"),
    ("ctrl+8", "maximize_translation(8)", "Maximize Translation 8"),
    ("ctrl+9", "maximize_translation(9)", "Maximize Translation 9"),
    ("ctrl+a", "chapter_start", "Chapter Start"),
    ("ctrl+e", "chapter_end", "Chapter End"),
    ("<", "previous_chapter", "Previous Chapter"),
    (">", "next_chapter", "Next Chapter"),
    ("g", "open_reference", "Go To"),
    ("G", "open_reference", "Go To"),
    ("@", "open_reference", "Go To"),
    (":", "open_reference", "Go To"),
    ("?", "show_shortcuts", "Shortcuts"),
    ("escape", "restore_panes", "Restore Panes"),
    ("f2", "toggle_layout", "Toggle Layout"),
]


SHORTCUTS = [
    ("↑ / ↓", "Previous / next verse"),
    ("Ctrl+A", "Beginning of current chapter"),
    ("Ctrl+E", "End of current chapter"),
    ("<", "Previous chapter"),
    (">", "Next chapter"),
    ("g / G / @", "Go to"),
    ("Tab", "Next translation"),
    ("Shift+Tab", "Previous translation"),
    ("Tab in Go To", "Cycle matches"),
    ("Enter", "Select match or navigate"),
    ("Ctrl+T", "Translations"),
    ("Ctrl+F", "Find text"),
    ("Ctrl+G", "Strongs"),
    ("Ctrl+H", "History"),
    ("Ctrl+P", "Config"),
    ("Ctrl+D", "Toggle theme"),
    ("Ctrl+W", "Close pane"),
    ("Ctrl+M", "Maximize translation"),
    ("Ctrl+Tab", "Next translation"),
    ("Ctrl+1-9", "Select maximized translation"),
    ("F2", "Toggle split layout"),
    ("Ctrl+L", "Live mode"),
    ("?", "Show shortcuts"),
    ("Esc", "Close / clear"),
]


WELCOME_SHORTCUTS = [
    ("↑ / ↓", "Previous / next verse"),
    ("g / @", "Go to book, chapter, or verse"),
    ("Ctrl+F", "Find text in the current translation"),
    ("Ctrl+T", "Open translations"),
    ("Ctrl+L", "Toggle live mode"),
    ("?", "Show all shortcuts"),
]
