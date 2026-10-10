from __future__ import annotations

import re
from html import unescape

from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Label

from bibleit import translation


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
                return f"[bold underline #ffb347]" f"[@click=app.open_strong('{code}')]" f"{inner}" f"[/][/]"

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
