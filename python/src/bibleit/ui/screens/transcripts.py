from __future__ import annotations

from pathlib import Path

from textual import events
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Label, ListItem, ListView

from bibleit.transcripts import TranscriptFile, list_transcripts, read_transcript


class TranscriptsScreen(Screen):
    BINDINGS = [
        ("escape", "close_screen", "Close"),
        ("ctrl+shift+r", "close_screen", "Transcripts"),
        Binding("enter", "open_selected", "Open", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_path: Path | None = None
        self._files: list[TranscriptFile] = []

    def compose(self):
        with Container(id="transcripts-panel"):
            yield Label("Transcripts", id="transcripts-title")
            with Horizontal(id="transcripts-body"):
                yield ListView(id="transcripts-files")
                yield ListView(id="transcripts-lines")

    def on_mount(self) -> None:
        active_path = getattr(getattr(self.app, "transcript_recorder", None), "path", None)
        self._refresh_files(preferred=active_path)
        self._refresh_lines()
        self.set_interval(1, self._refresh_live_tail)
        self.call_after_refresh(self._focus_files)

    def _files_list(self) -> ListView:
        return self.query_one("#transcripts-files", ListView)

    def _lines_list(self) -> ListView:
        return self.query_one("#transcripts-lines", ListView)

    def _focus_files(self) -> None:
        self._files_list().focus()

    def _refresh_files(self, *, preferred: Path | None = None) -> None:
        files = list_transcripts()
        list_view = self._files_list()
        previous_path = preferred or self._selected_path

        list_view.clear()
        self._files = files
        for file in files:
            item = ListItem(Label(file.label, classes="transcript-file"))
            item.path = file.path
            list_view.append(item)

        if not files:
            self._selected_path = None
            return

        index = 0
        if previous_path is not None:
            for candidate_index, file in enumerate(files):
                if file.path == previous_path:
                    index = candidate_index
                    break

        list_view.index = index
        self._selected_path = files[index].path

    def _refresh_lines(self) -> None:
        list_view = self._lines_list()
        list_view.clear()

        if self._selected_path is None:
            list_view.append(ListItem(Label("No transcripts yet", classes="transcript-line")))
            return

        for line in read_transcript(self._selected_path):
            list_view.append(ListItem(Label(line, classes="transcript-line")))

        if list_view.children:
            list_view.index = len(list_view.children) - 1

    def _refresh_live_tail(self) -> None:
        active_path = getattr(getattr(self.app, "transcript_recorder", None), "path", None)
        if active_path is not None and active_path != self._selected_path:
            self._refresh_files(preferred=active_path)

        self._refresh_lines()

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.action_close_screen()
            return

        files = self._files_list()
        if self.app.focused is files and event.key in ("up", "down"):
            event.stop()
            if not files.children:
                return
            if event.key == "down":
                files.action_cursor_down()
            else:
                files.action_cursor_up()
            self._select_current_file()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "transcripts-files":
            return
        self._select_current_file()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "transcripts-files":
            self._select_current_file()

    def _select_current_file(self) -> None:
        files = self._files_list()
        if files.index is None or not 0 <= files.index < len(files.children):
            return

        self._selected_path = getattr(files.children[files.index], "path", None)
        self._refresh_lines()

    def action_open_selected(self) -> None:
        self._select_current_file()

    def action_close_screen(self) -> None:
        from bibleit.ui.bible_view import BibleView

        self.app.pop_screen()
        self.app.query_exactly_one(BibleView).focus()
