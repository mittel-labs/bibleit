from __future__ import annotations

from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Label, Tree

from bibleit import translation


class Translations(Screen):
    AVAILABLE_NODE_LABEL = "Available"
    INSTALLED_NODE_LABEL = "Installed"
    LOADING_LABEL = "Loading translations..."
    BINDINGS = [
        ("escape", "close", "Close"),
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
        with Container(id="translations-panel"):
            yield Label("Translations", id="translations-title")
            yield Label("Open installed translations or install new ones.", id="translations-caption")
            yield Tree(self.LOADING_LABEL, id="translations-tree")

    def on_mount(self):
        self.call_after_refresh(self._build_tree)

    def _tree(self) -> Tree:
        return self.query_exactly_one("#translations-tree", Tree)

    def _build_tree(self, active_slug: str = None):
        tree = self._tree()
        tree.root.label = "Translations"
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

        for lang in translation.get_languages_available():
            language = available.add(lang.name)
            for t in lang.translations:
                if not translation.is_installed(t.slug):
                    language.add_leaf(str(t), t)
            if not language.children:
                language.remove()

        def select_active():
            tree.cursor_line = active_node.line if active_node else 0

        self.call_after_refresh(select_active)

    def _install_node(self, node) -> None:
        if node is None:
            return

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

    def action_install(self):
        self._install_node(self._tree().cursor_node)

    def action_uninstall(self):
        node = self._tree().cursor_node
        if node is None:
            return

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

    def _open_node(self, node) -> None:
        from bibleit.ui.bible_view import BibleView

        if node is None:
            return

        data = node.data

        if not data:
            return

        if not translation.is_installed(data.slug):
            self.notify(
                "Translation not installed",
                title=str(data),
                severity="warning",
                timeout=3,
            )
            return

        self.app.query_exactly_one(BibleView).post_message(Translations.Open(translation.open(data.slug)))

        self.app.pop_screen()

    def action_open(self):
        self._open_node(self._tree().cursor_node)

    def _activate_node(self, node) -> None:
        if node is None:
            return

        if node.children:
            if node.is_expanded:
                node.collapse()
            else:
                node.expand()
        elif node.data and node.parent:
            if node.parent.label.plain == self.INSTALLED_NODE_LABEL:
                self._open_node(node)
            else:
                self._install_node(node)

    def action_activate(self):
        node = self._tree().cursor_node

        if node:
            self._activate_node(node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        self._activate_node(event.node)

    def action_close(self):
        from bibleit.ui.bible_view import BibleView

        self.app.pop_screen()
        self.app.query_exactly_one(BibleView).focus()
