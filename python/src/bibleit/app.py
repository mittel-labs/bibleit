from __future__ import annotations
from dataclasses import dataclass

from textual.app import App
from textual.containers import Container, Horizontal
from textual.binding import Binding
from textual.widgets import ListView, ListItem, Input, Tree, Footer, Label, Static
from textual.screen import Screen
from textual.content import Content
from textual.message import Message
from textual.reactive import reactive
from textual import events
from textual_autocomplete import AutoComplete, DropdownItem
from typing import Iterable, Sequence
from html import unescape

from bibleit import translation
from unidecode import unidecode


import re


@dataclass(frozen=True)
class RowRef:
    bookid: int
    chapter: int
    verse: int


@dataclass
class NavigationState:
    bookid: int = 1
    chapter: int = 1
    verse: int = 1


class StatusBar(Horizontal):
    can_focus = False
    translations = reactive(list)
    strongs = reactive(False)

    def compose(self):
        yield Static(id="status-left")
        yield Static(id="status-right")

    def watch_translations(self):
        self._refresh()

    def watch_strongs(self):
        self._refresh()

    def on_mount(self):
        self._refresh()

    def _refresh(self):
        translation_text = (
            " [#b8b0a6]·[/] ".join(f"[#d97706]{t}[/]" for t in self.translations)
            if self.translations
            else "No translation selected"
        )

        left = " [#b8b0a6]·[/] ".join(
            filter(
                None,
                [
                    "[bold]bibleit[/]",
                    translation_text,
                    "[#d97706]STRONGS[/]" if self.strongs else None,
                ],
            )
        )

        right = "[#7a756e]" "^S Search   " "^T Translations   " "^G Strongs" "[/]"

        self.query_one("#status-left", Static).update(left)
        self.query_one("#status-right", Static).update(right)


class Search(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
    ]

    def __init__(
        self,
        view: View,
    ):
        super().__init__()

        self.view = view
        self.input = Input()
        self.translations = [view.translation]
        self.suggestions = self._build_suggestions()

    def on_mount(self):
        self.input.focus()

    class Request(Message):
        BIBLE_REF_RE = re.compile(
            r"^\s*"
            r"(?:(?:\"(?P<book_dq>[^\"]+)\"|'(?P<book_sq>[^']+)')|(?P<book>.+?))"
            r"\.?\s*"
            r"(?:(?P<chapter>\d+)"
            r"(?:\s*[:.]\s*(?P<verse_start>\d+)"
            r"(?:\s*[-–]\s*(?P<verse_end>\d+))?"
            r")?"
            r")?\s*$",
            re.IGNORECASE | re.UNICODE,
        )

        def __init__(self, value: str):
            super().__init__()
            self.value = value

            if m := self.BIBLE_REF_RE.match(value):
                gd = m.groupdict()
                self.book_name: str = (
                    gd.get("book_dq") or gd.get("book_sq") or gd["book"]
                ).strip()
                self.chapter = int(gd["chapter"]) if gd["chapter"] else None
                self.verse_start = int(gd["verse_start"]) if gd["verse_start"] else None
                self.verse_end = int(gd["verse_end"]) if gd["verse_end"] else None

        def __repr__(self):
            return (
                f"{self.book_name} {self.chapter} {self.verse_start} {self.verse_end}"
            )

    class Response(Message):
        def __init__(
            self,
            request: Search.Request,
            values: list[(str, Iterable[str])],
        ):
            self.request = request
            self.values = values
            super().__init__()

    class AC(AutoComplete):
        def __init__(self, target: Input, candidates: Sequence[DropdownItem | str]):
            self.input = target
            super().__init__(target, candidates)

        def match(self, query, candidate):
            return self._fuzzy_search.match(query, unidecode(candidate))

        def post_completion(self):
            super().post_completion()
            self.input.insert_text_at_cursor(" ")

        @property
        def option_list(self):
            try:
                return super().option_list
            except Exception:
                return None

        def _align_to_target(self):
            try:
                if self.option_list is None:
                    return

                super()._align_to_target()

            except Exception:
                pass

    def on_unmount(self):
        for ac in self.query(self.AC):
            ac.display = False

    def compose(self):
        yield self.input
        yield self.AC(self.input, candidates=self.suggestions)

    def _build_suggestions(self):
        return (
            [
                DropdownItem(
                    c.name,
                    Content.from_markup(f"[bold #f3f0ea on #6b655d] {t.slug} [/] "),
                )
                for t in self.translations
                for c in t.header.chapters.values()
            ]
            if self.translations
            else []
        )

    def on_input_submitted(self, event: Input.Submitted):
        value = event.value.strip()

        if value:
            self.view.search_reference(value)
            self.app.pop_screen()


class Translations(Screen):
    AVAILABLE_NODE_LABEL = "Available"
    INSTALLED_NODE_LABEL = "Installed"
    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
        ("ctrl+i", "install", "Install"),
        ("ctrl+u", "uninstall", "Uninstall"),
        ("ctrl+o", "open", "Open"),
        Binding("enter", "activate", "Open/Install", priority=True),
    ]

    class Open(Message):
        def __init__(self, translation: translation.Translation):
            self.translation = translation
            super().__init__()

    def compose(self):
        yield Tree("Translations")
        yield Footer(show_command_palette=False)

    def on_mount(self):
        self._build_tree()

    def _build_tree(self, active_slug: str = None):
        tree = self.query_exactly_one(Tree)
        tree.root.remove_children()
        active_node = None
        installed = tree.root.add(self.INSTALLED_NODE_LABEL)
        available = tree.root.add(self.AVAILABLE_NODE_LABEL)
        tree.root.expand_all()

        for t in translation.get_installed().values():
            node = installed.add_leaf(str(t), t)
            if t.slug == active_slug:
                active_node = node
        installed.expand_all()

        for lang in translation.get_languages():
            language = available.add(lang.name)
            for t in lang.translations:
                if not translation.is_installed(t.slug):
                    language.add_leaf(str(t), t)
            if not language.children:
                language.remove()

        def select_active():
            tree.cursor_line = active_node.line if active_node else 0

        self.call_after_refresh(select_active)

    def action_install(self):
        node = self.query_exactly_one(Tree).cursor_node
        data = node.data
        if data and not translation.is_installed(data.slug):
            try:
                translation.install(data.slug)
                self.notify(data.name, title="Translation installed", timeout=7)
            except Exception as e:
                self.notify(
                    f"Failed to install translation: {e}!",
                    title=str(data),
                    severity="error",
                    timeout=7,
                )
            finally:
                self._build_tree(data.slug)
        else:
            self.notify(
                str(data),
                title="Translation already installed",
                severity="warning",
                timeout=3,
            )

    def action_uninstall(self):
        node = self.query_exactly_one(Tree).cursor_node
        data = node.data
        if data and translation.is_installed(data.slug):
            try:
                translation.uninstall(data.slug)
                self.notify(data.name, title="Translation uninstalled", timeout=3)
            except Exception as e:
                self.notify(
                    f"Failed to uninstall translation: {e}!",
                    title=str(data),
                    severity="error",
                    timeout=7,
                )
            finally:
                self._build_tree()
        else:
            self.notify(
                str(data),
                title="Translation not installed",
                severity="warning",
                timeout=3,
            )

    def action_open(self):
        data = self.query_exactly_one(Tree).cursor_node.data

        if not translation.is_installed(data.slug):
            self.notify(
                "Translation not installed",
                title=str(data),
                severity="warning",
                timeout=3,
            )
            return

        self.app.query_exactly_one(BibleView).post_message(
            Translations.Open(translation.open(data.slug))
        )

        self.app.pop_screen()

    def action_activate(self):
        node = self.query_exactly_one(Tree).cursor_node

        if node:
            if node.children:
                if node.is_expanded:
                    node.collapse()
                else:
                    node.expand()
            elif node.data and node.parent:
                if node.parent.label.plain == self.INSTALLED_NODE_LABEL:
                    self.action_open()
                else:
                    self.action_install()


class StrongScreen(Screen):
    HTML_TAG_RE = re.compile(r"<[^>]+>")
    STRONG_LINK_RE = re.compile(
        r"<a\s+href=['\"]S:([^'\"]+)['\"]>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    REPLACEMENTS = [
        (r"<br\s*/?>", "\n"),
        (r"</p>", "\n\n"),
        (r"<hr\s*/?>", "\n────────────────────\n"),
        (r"<b>(.*?)</b>", r"[bold]\1[/]"),
        (r"<big>(.*?)</big>", r"[bold]\1[/]"),
        (r"<i>(.*?)</i>", r"[italic]\1[/]"),
        (r"<grk>(.*?)</grk>", r"[italic #d8c090]\1[/]"),
        (r"<heb>(.*?)</heb>", r"[italic #d8c090]\1[/]"),
        (
            r"<font color='3'>(.*?)</font>",
            r"[#d8c090]\1[/]",
        ),
        (
            r"<font color='4'>(.*?)</font>",
            r"[italic #909090]\1[/]",
        ),
        (
            r"<font color='5'>(.*?)</font>",
            r"[bold #ffb347]\1[/]",
        ),
    ]

    BINDINGS = [
        ("escape", "app.pop_screen", "Close"),
    ]

    def __init__(
        self,
        translation: translation.Translation,
        code: str,
        entry,
    ):
        super().__init__()
        self.translation = translation
        self.code = code
        self.entry = entry

    def render_strongs_html(self, html: str) -> str:
        if not html:
            return ""

        html = unescape(html)

        # Strong cross references
        def replace_link(match):
            raw_code = match.group(1).upper().strip()
            inner = match.group(2)
            inner = re.sub(r"<[^>]+>", "", inner).strip()

            if raw_code.startswith(("H", "G")):
                code = raw_code
            else:
                if self.code.startswith("H"):
                    code = f"H{raw_code}"
                else:
                    code = f"G{raw_code}"

            if code not in self.translation.strongs:
                alt = f"G{raw_code}" if code.startswith("H") else f"H{raw_code}"

                if alt in self.translation.strongs:
                    code = alt

            exists = code in self.translation.strongs

            if exists:
                return (
                    f"[bold underline #ffb347]"
                    f"[@click=app.open_strong('{code}')]"
                    f"{inner}"
                    f"[/][/]"
                )

            return f"[dim]{inner}[/]"

        html = self.STRONG_LINK_RE.sub(replace_link, html)

        for pattern, repl in self.REPLACEMENTS:
            html = re.sub(
                pattern,
                repl,
                html,
                flags=re.IGNORECASE | re.DOTALL,
            )

        html = self.HTML_TAG_RE.sub("", html)
        html = re.sub(r"\n{3,}", "\n\n", html)
        return html.strip()

    def compose(self):
        with Container():
            yield Label(
                f"""
        [bold #ffb347]{self.code}[/]

        [bold]Lemma:[/] {self.entry.lemma}

        [bold]Transliteration:[/] {self.entry.transliteration}

        [bold]Definition:[/]
        {self.entry.definition}

        [bold]Description:[/]
        {self.render_strongs_html(self.entry.description)}
        """,
                markup=True,
            )


class View(ListView):
    INITIAL_ROWS = 25
    STRONG_RE = re.compile(r"<S>(.*?)</S>")

    class Render(Message):
        def __init__(self, slug: str, value: Iterable[str]):
            self.slug = slug
            self.value = value
            super().__init__()

    class Navigate(Message):
        def __init__(self, ref: translation.TranslationRef):
            self.ref = ref
            super().__init__()

    def __init__(
        self,
        state: NavigationState,
        translation_: translation.Translation,
        *children,
    ):
        super().__init__(*children)

        self.state = state
        self.translation = translation_
        self.cursor = None
        self.show_strongs = False
        self.syncing = False

    def _select_first(self):
        if self.children:
            self.focus()
            self.index = 0

    def _style_row(self, text: str) -> str:
        text = re.sub(r"(.* \d+:\d+)", r"[bold]\1 [/]", text)
        text = re.sub(r"<b>(.*?)</b>", r"[bold]\1[/]", text)
        text = re.sub(r"<i>(.*?)</i>", r"[italic]\1[/]", text)

        def replace_strong(match):
            raw = match.group(1).strip()

            if not self.translation:
                return raw

            prefix = "H"

            if self.children:
                ref = self._row_ref(self.children[0])

                if ref:
                    prefix = self._strong_prefix(ref.bookid)

            code = f"{prefix}{raw}"

            entry = self.translation.strongs.get(code)

            if not entry:
                return ""

            if not self.show_strongs:
                return ""

            label = raw

            return f"[#c96f00]" f"[@click=app.open_strong('{code}')]" f"ᴴ{label}" f"[/]"

        text = text.replace("<br>", "\n").replace("<br/>", "\n")
        text = self.STRONG_RE.sub(replace_strong, text)
        text = re.sub(
            r"<sup>(.*?)</sup>",
            r"[dim italic]\1[/]",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return text

    def _make_row(self, value: str) -> ListItem:
        label = Label(self._style_row(value), markup=True)
        row = ListItem(label)
        row.data = value
        return row

    def _decode_row(self, value) -> str:
        return value.memoryview().tobytes().decode("utf-8", "replace")

    def _append_cursor_row(self) -> bool:
        if self.cursor is None:
            return False
        value = self.cursor.next()
        if value is None:
            return False
        self.append(self._make_row(self._decode_row(value)))
        return True

    def _load_cursor_rows(self, cursor, count: int = INITIAL_ROWS) -> None:
        self.cursor = cursor
        for _ in range(count):
            if not self._append_cursor_row():
                break

    def _row_ref(self, row: ListItem) -> RowRef | None:
        if not self.translation:
            return None

        text = getattr(row, "data", "")
        match = re.match(r"^(?P<book>.+)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+", text)
        if not match:
            return None

        if bookid := self.translation.resolve_bookid(match.group("book")):
            return RowRef(
                bookid=bookid,
                chapter=int(match.group("chapter")),
                verse=int(match.group("verse")),
            )

    def _cursor_from_row(self, row: ListItem):
        ref = self._row_ref(row)
        if ref is None or self.translation is None:
            return None
        return self.translation.cursor_from(
            translation.TranslationRef(ref.bookid, ref.chapter, ref.verse)
        )

    def _previous_row(self) -> ListItem | None:
        if not self.children:
            return None

        cursor = self._cursor_from_row(self.children[0])
        if cursor is None:
            return None

        value = cursor.previous()
        if value is None:
            return None

        return self._make_row(self._decode_row(value))

    def _next_row(self) -> ListItem | None:
        if not self.children:
            return None

        cursor = self._cursor_from_row(self.children[-1])
        if cursor is None:
            return None

        cursor.next()
        value = cursor.next()
        if value is None:
            return None

        return self._make_row(self._decode_row(value))

    def _force_highlight(self, index: int) -> None:
        for child in self.children:
            if isinstance(child, ListItem):
                child.highlighted = False

        self.index = None
        self.index = index

        if 0 <= index < len(self.children):
            row = self.children[index]

            if isinstance(row, ListItem):
                row.highlighted = True

                self.scroll_to_widget(
                    row,
                    animate=False,
                    immediate=True,
                    force=True,
                )

                ref = self._row_ref(row)

                if ref:
                    self.state.bookid = ref.bookid
                    self.state.chapter = ref.chapter
                    self.state.verse = ref.verse

                    if not self.syncing:
                        self.post_message(
                            self.Navigate(
                                translation.TranslationRef(
                                    ref.bookid,
                                    ref.chapter,
                                    ref.verse,
                                )
                            )
                        )

    def _force_highlight_row(self, row: ListItem) -> None:
        try:
            index = self.children.index(row)
        except ValueError:
            return
        self._force_highlight(index)

    def _force_highlight_row_after_refresh(self, row: ListItem) -> None:
        self.call_after_refresh(self._force_highlight_row, row)

    def _strong_prefix(self, bookid: int) -> str:
        return "H" if bookid <= 39 else "G"

    def on_translations_open(self, event: Translations.Open):
        self.clear()
        self.translation = event.translation

        self._load_cursor_rows(
            self.translation.read(translation.TranslationRef(bookid=1))
        )

        self.call_after_refresh(self._select_first)

    def on_search_request(self, event: Search.Request):
        if event.book_name:
            if bookid := self.translation.resolve_bookid(event.book_name):
                target = [self.translation]
                ref = translation.TranslationRef(
                    bookid, event.chapter, event.verse_start, event.verse_end
                )
                try:
                    results = ((t.slug, t.read(ref)) for t in target)
                    self.post_message(Search.Response(event, results))
                except Exception as e:
                    self.notify(
                        "Invalid referench search",
                        severity="error",
                        timeout=3,
                    )
                    self.log.error("error on read parsing", e)
        else:
            self.notify(
                "Search reference not found",
                severity="error",
                timeout=3,
            )

    def on_search_response(self, event: Search.Response):
        for slug, value in event.values:
            self.post_message(View.Render(slug, value))
        self.app.pop_screen()

    def on_view_render(self, event: Render):
        self.clear()
        self._load_cursor_rows(event.value)
        self.call_after_refresh(self._select_first)

    async def on_key(self, event: events.Key):
        if event.key == "down" and self.index == len(self.children) - 1:
            row = self._next_row()
            if row is None:
                return
            event.stop()
            await self.append(row)
            self._force_highlight_row_after_refresh(row)

        elif event.key == "up" and self.index == 0:
            row = self._previous_row()
            if row is None:
                return
            event.stop()
            await self.insert(0, [row])
            self._force_highlight_row_after_refresh(row)

    def sync_to_state(self):
        ref = translation.TranslationRef(
            self.state.bookid,
            self.state.chapter,
            self.state.verse,
        )

        try:
            cursor = self.translation.cursor_from(ref)
            self.syncing = True
            self.clear()
            self._load_cursor_rows(cursor)

            def restore():
                self._select_first()
                self.syncing = False

            self.call_after_refresh(restore)
        except RuntimeError as e:
            self.log.error("error on cursor_from", e)
            self.notify(
                "Search reference not found",
                severity="error",
                timeout=3,
            )

    def action_toggle_strongs(self):
        self.show_strongs = not self.show_strongs

        rows = [child.data for child in self.children]

        current_index = self.index or 0

        self.clear()

        for row in rows:
            self.append(self._make_row(row))

        status = self.app.query_exactly_one(StatusBar)
        status.strongs = self.show_strongs

        def restore():
            if self.children:
                self.index = min(current_index, len(self.children) - 1)
                self.focus()

        self.call_after_refresh(restore)

    def search_reference(self, value: str):
        request = Search.Request(value)

        if not request.book_name:
            self.notify(
                "Search reference not found",
                severity="error",
                timeout=3,
            )
            return

        bookid = self.translation.resolve_bookid(request.book_name)

        if not bookid:
            self.notify(
                "Book not found",
                severity="error",
                timeout=3,
            )
            return

        ref = translation.TranslationRef(
            bookid,
            request.chapter or 1,
            request.verse_start or 1,
            request.verse_end,
        )

        try:
            cursor = self.translation.cursor_from(ref)
            self.syncing = True
            self.clear()

            self._load_cursor_rows(cursor)

            def restore():
                self._select_first()
                self.syncing = False

            self.call_after_refresh(restore)
        except RuntimeError as e:
            self.log.error("error on cursor_from", e)
            self.notify(
                "Search reference not found",
                severity="error",
                timeout=3,
            )


class BibleView(Horizontal):
    can_focus = True

    BINDINGS = [
        ("ctrl+t", "open_translations", "Translations"),
        ("ctrl+s", "open_search", "Search"),
        ("ctrl+g", "toggle_strongs", "Strongs"),
        ("ctrl+w", "close_pane", "Close Pane"),
        ("ctrl+shift+h", "split_horizontal", "Split Horizontal"),
        ("ctrl+shift+v", "split_vertical", "Split Vertical"),
    ]

    def __init__(self):
        super().__init__()
        self.state = NavigationState()
        self.views: list[View] = []

    def add_translation(
        self,
        translation: translation.Translation,
    ):
        view = View(self.state, translation)
        self.views.append(view)
        self.mount(view)
        view.sync_to_state()
        self.refresh_status()

    def on_translations_open(
        self,
        event: Translations.Open,
    ):
        for view in self.views:
            if view.translation.slug == event.translation.slug:
                return
        self.add_translation(event.translation)

    def on_view_navigate(self, event: View.Navigate):
        for view in self.views:
            if view is event.control:
                continue

            view.sync_to_state()

    def on_mount(self):
        self.app.install_screen(Translations(), name="translations")
        self.focus()

    def action_open_translations(self):
        if isinstance(self.screen, Translations):
            self.app.pop_screen()
        else:
            self.app.push_screen("translations")

    def action_open_search(self):
        if not self.views:
            self.notify(
                "Please open a translation first",
                severity="warning",
            )
            return

        view = self.focused_view()

        if not view:
            view = self.views[0]

        self.app.push_screen(Search(view))

    def action_toggle_strongs(self):
        view = self.focused_view()

        if not view:
            if self.views:
                view = self.views[0]
            else:
                return

        view.action_toggle_strongs()

    def refresh_status(self):
        status = self.app.query_exactly_one(StatusBar)
        status.translations = [view.translation.slug for view in self.views]

    def action_close_pane(self):
        view = self.focused_view()
        if not view:
            return

        if len(self.views) <= 1:
            return
        self.views.remove(view)
        view.remove()
        self.refresh_status()
        self.views[0].focus()

    def focused_view(self) -> View | None:
        focused = self.app.focused

        while focused and not isinstance(focused, View):
            focused = focused.parent

        return focused


class Bibleit(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "app.tcss"

    def action_open_strong(self, code: str):
        focused = self.focused
        view = focused

        while view and not isinstance(view, View):
            view = view.parent

        if not view:
            return

        if not view.translation:
            return

        entry = view.translation.strongs.get(code)

        if not entry:
            self.notify(
                f"Strong entry not found: {code}",
                severity="warning",
            )
            return

        self.push_screen(
            StrongScreen(
                view.translation,
                code,
                entry,
            )
        )

    def compose(self):
        yield BibleView()
        yield StatusBar()
