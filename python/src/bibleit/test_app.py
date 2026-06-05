from __future__ import annotations

import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
import asyncio

from textual.widgets import Button, Label, ListItem, ListView, Switch

try:
    from bibleit import translation
    from bibleit.config import config_value, load_config, save_config, theme_is_dark, theme_value
    from bibleit.app import (
        BibleView,
        Bibleit,
        ConfigScreen,
        HistoryEntry,
        HistoryScreen,
        LivePublisher,
        NavigationState,
        RowRef,
        SessionHistory,
        ShortcutsScreen,
        StatusBar,
        View,
        WelcomeScreen,
        running_in_browser,
    )
    from bibleit.navigation import (
        complete_navigation_value,
        navigation_completion_candidates,
        navigation_suggestion_value,
        next_chapter_ref,
        parse_navigation_ref,
        previous_chapter_ref,
        select_navigation_completion,
    )
    from bibleit.text_find import (
        TextFindIndex,
        cached_find_index,
        clean_verse_text,
        clear_find_index_cache,
        find_translation_text,
    )
except ModuleNotFoundError:
    raise


class FakeCursor:
    def __init__(self, values):
        self.values = values
        self.index = 0

    def next(self):
        if self.index >= len(self.values):
            return None

        value = self.values[self.index]
        self.index += 1
        return value


class FakeTranslation:
    slug = "TEST"

    def __init__(self):
        self.header = translation.TranslationHeader(
            name="Test",
            slug=self.slug,
            chapters={
                "Genesis": translation.TranslationChapter(1, 1, "Genesis", 1, 50),
                "Daniel": translation.TranslationChapter(27, 27, "Daniel", 27, 12),
                "Deuteronomy": translation.TranslationChapter(5, 5, "Deuteronomy", 5, 34),
                "First Letter of Paul to the Corinthians": translation.TranslationChapter(
                    46,
                    46,
                    "First Letter of Paul to the Corinthians",
                    46,
                    16,
                ),
                "Primeira Carta de João": translation.TranslationChapter(
                    62,
                    62,
                    "Primeira Carta de João",
                    62,
                    5,
                ),
                "Matthew": translation.TranslationChapter(40, 40, "Matthew", 40, 28),
            },
        )
        self.strongs = {
            "H7225": translation.StrongEntry(
                code="H7225",
                lemma="reshith",
                definition="beginning",
            )
        }
        self.rows_by_book = {
            1: [
                "Genesis 1:1 In the beginning God created the heavens and the earth.",
                "Genesis 1:2 The earth was formless and empty.",
            ],
            46: [
                "First Letter of Paul to the Corinthians 13:4 Love is patient, love is kind.",
                "First Letter of Paul to the Corinthians 13:5 It does not dishonor others.",
            ],
        }
        self.read_calls = 0

    def resolve_bookid(self, book_name: str):
        return self.header.resolve_bookid(book_name)

    def read(self, ref: translation.TranslationRef):
        self.read_calls += 1
        return FakeCursor(self.rows_by_book.get(ref.bookid, []))


class AmbiguousFakeTranslation(FakeTranslation):
    def __init__(self):
        super().__init__()
        self.header = translation.TranslationHeader(
            name="Test",
            slug=self.slug,
            chapters={
                "Daniel": translation.TranslationChapter(27, 27, "Daniel", 27, 12),
                "Darius": translation.TranslationChapter(80, 80, "Darius", 80, 1),
            },
        )

    def resolve_bookid(self, book_name: str):
        normalized = book_name.lower()
        matches = {
            chapter.name.lower(): chapter.bookid
            for chapter in self.header.chapters.values()
            if chapter.name.lower().startswith(normalized)
        }
        return next(iter(matches.values())) if len(matches) == 1 else None


class FakeLive:
    def __init__(self):
        self.values = []

    def set_live_blocking(self, live: bool):
        self.values.append(live)


class FakeView:
    def __init__(self):
        self.live = FakeLive()


class FakeClickEvent:
    def __init__(self, item):
        self.item = item
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeInputEvent:
    def __init__(self, input_id: str, value: str):
        self.input = type("FakeInput", (), {"id": input_id})()
        self.value = value
        self.stopped = False

    def stop(self):
        self.stopped = True


class BibleViewRowTests(unittest.TestCase):
    def make_view(self):
        return View(NavigationState(), FakeTranslation())

    def test_row_ref_parses_rendered_verse(self):
        view = self.make_view()
        row = view._make_row("Genesis 1:3 Let there be light")

        self.assertEqual(view._row_ref(row), RowRef(bookid=1, chapter=1, verse=3))

    def test_strongs_are_hidden_when_disabled(self):
        view = self.make_view()

        self.assertEqual(
            view._style_row("Genesis 1:1 Beginning<S>7225</S>"),
            "[bold]Genesis 1:1 [/] Beginning",
        )

    def test_strongs_are_clickable_when_enabled(self):
        view = self.make_view()
        view.show_strongs = True

        styled = view._style_row("Genesis 1:1 Beginning<S>7225</S>")

        self.assertIn("@click=app.open_strong('H7225')", styled)
        self.assertIn("ᴴ7225", styled)

    def test_valid_index_clamps_stale_index(self):
        view = View(NavigationState(), FakeTranslation())
        view._nodes._append(ListItem())
        view._nodes._append(ListItem())
        view.index = 24

        self.assertEqual(view._valid_index(), 1)
        self.assertEqual(view.index, 1)

    def test_stale_row_click_is_ignored(self):
        view = View(NavigationState(), FakeTranslation(), ListItem())
        event = FakeClickEvent(ListItem())

        with patch("bibleit.app.running_in_browser", return_value=True):
            view._on_list_item__child_clicked(event)

        self.assertTrue(event.stopped)
        self.assertIsNone(view.index)


class SessionHistoryTests(unittest.TestCase):
    def test_record_moves_existing_entry_to_front(self):
        history = SessionHistory()
        history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))
        history.record(HistoryEntry(40, 5, 3, "Matthew 5:3"))
        history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))

        self.assertEqual(
            [entry.label for entry in history.entries()],
            ["Genesis 1:1", "Matthew 5:3"],
        )

    def test_entries_filters_with_fuzzy_query(self):
        history = SessionHistory()
        history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))
        history.record(HistoryEntry(19, 23, 1, "Psalms 23:1"))
        history.record(HistoryEntry(43, 3, 16, "John 3:16"))

        filtered = history.entries("john 3:16")

        self.assertEqual([entry.label for entry in filtered], ["John 3:16"])

    def test_entries_filters_from_first_letter(self):
        history = SessionHistory()
        history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))
        history.record(HistoryEntry(19, 23, 1, "Psalms 23:1"))
        history.record(HistoryEntry(43, 3, 16, "John 3:16"))

        filtered = history.entries("j")

        self.assertEqual([entry.label for entry in filtered], ["John 3:16"])

    def test_entries_filters_from_second_letter(self):
        history = SessionHistory()
        history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))
        history.record(HistoryEntry(19, 23, 1, "Psalms 23:1"))
        history.record(HistoryEntry(43, 3, 16, "John 3:16"))

        filtered = history.entries("jo")

        self.assertEqual([entry.label for entry in filtered], ["John 3:16"])


class TextFindTests(unittest.TestCase):
    def setUp(self):
        clear_find_index_cache()
        self.translation = FakeTranslation()

    def test_clean_verse_text_removes_rendered_markup(self):
        self.assertEqual(
            clean_verse_text("Genesis 1:1 <b>Love</b><S>25</S><br>is patient"),
            "Genesis 1:1 Love is patient",
        )

    def test_find_translation_finds_phrase_in_verse_text(self):
        results = find_translation_text(self.translation, "love is patient")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].label, "First Letter of Paul to the Corinthians 13:4")
        self.assertEqual(results[0].ref, translation.TranslationRef(46, 13, 4))

    def test_find_translation_checks_rendered_text_not_only_labels(self):
        results = find_translation_text(self.translation, "formless")

        self.assertEqual([result.label for result in results], ["Genesis 1:2"])

    def test_find_index_builds_once_and_reuses_results(self):
        index = TextFindIndex.build(self.translation)
        read_calls = self.translation.read_calls

        self.assertEqual(
            [result.label for result in index.find("love")],
            ["First Letter of Paul to the Corinthians 13:4"],
        )
        self.assertEqual([result.label for result in index.find("formless")], ["Genesis 1:2"])
        self.assertEqual(self.translation.read_calls, read_calls)

    def test_find_index_cache_reuses_translation_index(self):
        cached_find_index(self.translation)
        read_calls = self.translation.read_calls

        cached_find_index(self.translation)

        self.assertEqual(self.translation.read_calls, read_calls)

    def test_find_index_cache_evicts_oldest_index(self):
        class OtherTranslation(FakeTranslation):
            slug = "OTHER"

        with patch.dict("os.environ", {"BIBLEIT_FIND_INDEX_CACHE_SIZE": "1"}):
            cached_find_index(self.translation)
            other = OtherTranslation()
            cached_find_index(other)
            read_calls = self.translation.read_calls

            cached_find_index(self.translation)

        self.assertGreater(self.translation.read_calls, read_calls)


class NavigationCommandTests(unittest.TestCase):
    def setUp(self):
        self.translation = FakeTranslation()
        self.state = NavigationState(bookid=1, chapter=3, verse=4)

    def test_bare_number_is_verse_in_current_chapter(self):
        self.assertEqual(
            parse_navigation_ref(":10", self.translation, self.state),
            translation.TranslationRef(1, 3, 10),
        )

    def test_chapter_and_verse_use_current_book(self):
        self.assertEqual(
            parse_navigation_ref(":9.2", self.translation, self.state),
            translation.TranslationRef(1, 9, 2),
        )

    def test_book_prefix_chapter_and_verse(self):
        self.assertEqual(
            parse_navigation_ref(":Mat 5:3", self.translation, self.state),
            translation.TranslationRef(40, 5, 3),
        )

    def test_fuzzy_book_chapter_and_verse(self):
        self.assertEqual(
            parse_navigation_ref("cor 13:4", self.translation, self.state),
            translation.TranslationRef(46, 13, 4),
        )

    def test_explicit_chapter_and_verse_forms(self):
        self.assertEqual(
            parse_navigation_ref(":c9", self.translation, self.state),
            translation.TranslationRef(1, 9, 1),
        )
        self.assertEqual(
            parse_navigation_ref(":v10", self.translation, self.state),
            translation.TranslationRef(1, 3, 10),
        )

    def test_next_chapter_uses_current_book(self):
        self.assertEqual(
            next_chapter_ref(self.translation, self.state),
            translation.TranslationRef(1, 4, 1),
        )

    def test_next_chapter_crosses_to_next_book(self):
        state = NavigationState(bookid=1, chapter=50, verse=1)

        self.assertEqual(
            next_chapter_ref(self.translation, state),
            translation.TranslationRef(5, 1, 1),
        )

    def test_previous_chapter_uses_current_book(self):
        self.assertEqual(
            previous_chapter_ref(self.translation, self.state),
            translation.TranslationRef(1, 2, 1),
        )

    def test_previous_chapter_crosses_to_previous_book(self):
        state = NavigationState(bookid=27, chapter=1, verse=1)

        self.assertEqual(
            previous_chapter_ref(self.translation, state),
            translation.TranslationRef(5, 34, 1),
        )

    def test_book_completion_fills_single_match(self):
        completed, matches, changed = complete_navigation_value("Da", self.translation)

        self.assertTrue(changed)
        self.assertEqual(completed, "Daniel ")
        self.assertEqual(matches, ["Daniel"])

    def test_book_completion_preserves_chapter_and_verse_tail(self):
        completed, matches, changed = complete_navigation_value("Da 9:2", self.translation)

        self.assertTrue(changed)
        self.assertEqual(completed, "Daniel 9:2")
        self.assertEqual(matches, ["Daniel"])

    def test_book_completion_shows_multiple_matches_without_guessing(self):
        ambiguous = AmbiguousFakeTranslation()

        completed, matches, changed = complete_navigation_value("Da", ambiguous)

        self.assertFalse(changed)
        self.assertEqual(completed, "Da")
        self.assertEqual(matches, ["Daniel", "Darius"])

    def test_book_completion_selection_preserves_tail(self):
        self.assertEqual(
            select_navigation_completion("Da 9:2", "Daniel"),
            "Daniel 9:2",
        )

    def test_book_completion_selection_adds_separator_without_tail(self):
        self.assertEqual(
            select_navigation_completion("Da", "Daniel"),
            "Daniel ",
        )

    def test_book_completion_ignores_numeric_commands(self):
        self.assertEqual(
            navigation_completion_candidates(":9.2", self.translation),
            [],
        )

    def test_book_completion_finds_contains_match(self):
        completed, matches, changed = complete_navigation_value("cor", self.translation)

        self.assertTrue(changed)
        self.assertEqual(completed, "First Letter of Paul to the Corinthians ")
        self.assertEqual(matches, ["First Letter of Paul to the Corinthians"])

    def test_book_suggestion_uses_first_match(self):
        self.assertEqual(
            navigation_suggestion_value("da", self.translation),
            "daniel ",
        )

    def test_book_suggestion_does_not_shift_unfinished_tail(self):
        self.assertIsNone(
            navigation_suggestion_value("dani 2:3", self.translation),
        )

    def test_book_suggestion_skips_contains_match_with_unfinished_tail(self):
        self.assertIsNone(
            navigation_suggestion_value("cor 13:4", self.translation),
        )

    def test_book_suggestion_is_accent_insensitive(self):
        self.assertEqual(
            navigation_suggestion_value("joao", self.translation),
            "Primeira Carta de João ",
        )


class BrowserModeTests(unittest.TestCase):
    def test_running_in_browser_detects_textual_serve_driver(self):
        with patch.dict(
            "os.environ",
            {"TEXTUAL_DRIVER": "textual.drivers.web_driver:WebDriver"},
        ):
            self.assertTrue(running_in_browser())

    def test_running_in_browser_is_false_without_web_driver(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(running_in_browser())


class ConfigTests(unittest.TestCase):
    def test_save_config_creates_toml_file(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config(
                    {
                        "LIVE_URL": "https://live.example",
                        "LIVE_TOKEN": "secret",
                    }
                )

                self.assertEqual(
                    load_config(),
                    {
                        "LIVE_URL": "https://live.example",
                        "LIVE_TOKEN": "secret",
                    },
                )

    def test_save_config_skips_empty_values(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config(
                    {
                        "LIVE_URL": "https://live.example",
                        "LIVE_TOKEN": "",
                    }
                )

                self.assertEqual(load_config(), {"LIVE_URL": "https://live.example"})

                with open(path, encoding="utf-8") as file:
                    self.assertNotIn("LIVE_TOKEN", file.read())

    def test_save_config_removes_existing_value_when_empty(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"LIVE_TOKEN": "secret", "LIVE_URL": "https://live.example"})
                save_config({"LIVE_TOKEN": ""})

                self.assertEqual(load_config(), {"LIVE_URL": "https://live.example"})

    def test_environment_value_takes_precedence_over_config(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"LIVE_URL": "https://config.example"})

            with patch.dict(
                "os.environ",
                {
                    "BIBLEIT_CONFIG_FILE": path,
                    "BIBLEIT_LIVE_URL": "https://env.example",
                },
                clear=True,
            ):
                self.assertEqual(config_value("LIVE_URL"), "https://env.example")

    def test_theme_is_loaded_from_config(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"THEME": "dark"})

                self.assertEqual(theme_value(), "dark")
                self.assertTrue(theme_is_dark())

    def test_theme_env_takes_precedence_over_config(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"THEME": "light"})

            with patch.dict(
                "os.environ",
                {
                    "BIBLEIT_CONFIG_FILE": path,
                    "BIBLEIT_THEME": "dark",
                },
                clear=True,
            ):
                self.assertTrue(theme_is_dark())

    def test_invalid_theme_falls_back_to_light(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"THEME": "sepia"})

                self.assertEqual(theme_value(), "light")

    def test_config_save_then_escape_keeps_saved_theme(self):
        async def run():
            with TemporaryDirectory() as temp:
                path = f"{temp}/config"
                with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                    save_config({"THEME": "light"})
                    app = Bibleit()

                    async with app.run_test() as pilot:
                        app.push_screen(ConfigScreen())
                        await pilot.pause()
                        app.screen.query_one("#config-theme-dark", Switch).value = True
                        await pilot.press("ctrl+s")
                        await pilot.pause()
                        await pilot.press("escape")
                        await pilot.pause()

                        self.assertTrue(app.dark_theme)
                        self.assertTrue(app.has_class("dark"))
                        self.assertEqual(app.theme, "textual-dark")

        asyncio.run(run())

    def test_shortcuts_screen_mounts_with_open_translation(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                bible_view = app.query_exactly_one(BibleView)
                view = View(NavigationState(), FakeTranslation())
                view.show_strongs = True
                bible_view.views.append(view)

                app.push_screen(ShortcutsScreen())
                await pilot.pause()

                self.assertIsInstance(app.screen, ShortcutsScreen)

        asyncio.run(run())

    def test_welcome_forwards_shortcut(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                await pilot.pause()

                self.assertIsInstance(app.screen, WelcomeScreen)

                await pilot.press("?")
                await pilot.pause()

                self.assertIsInstance(app.screen, ShortcutsScreen)

        asyncio.run(run())

    def test_uppercase_g_opens_go_to_command(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                bible_view = app.query_exactly_one(BibleView)
                bible_view.views.append(View(NavigationState(), FakeTranslation()))
                bible_view.focus()
                await pilot.pause()

                await pilot.press("G")
                await pilot.pause()

                self.assertTrue(app.query_exactly_one(StatusBar).command_mode)

        asyncio.run(run())

    def test_at_opens_go_to_command(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                bible_view = app.query_exactly_one(BibleView)
                bible_view.views.append(View(NavigationState(), FakeTranslation()))
                bible_view.focus()
                await pilot.pause()

                await pilot.press("@")
                await pilot.pause()

                self.assertTrue(app.query_exactly_one(StatusBar).command_mode)

        asyncio.run(run())

    def test_ctrl_h_toggles_history_screen(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                bible_view = app.query_exactly_one(BibleView)
                bible_view.focus()
                await pilot.pause()

                self.assertNotIsInstance(app.screen, HistoryScreen)

                await pilot.press("ctrl+h")
                await pilot.pause()

                self.assertIsInstance(app.screen, HistoryScreen)

                await pilot.press("ctrl+h")
                await pilot.pause()

                self.assertNotIsInstance(app.screen, HistoryScreen)

        asyncio.run(run())

    def test_history_status_button_opens_history_screen(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                await pilot.pause()

                self.assertNotIsInstance(app.screen, HistoryScreen)

                status = app.query_exactly_one(StatusBar)
                button = status.query_one("#action-history", Button)
                await status.on_button_pressed(Button.Pressed(button))
                await pilot.pause()

                self.assertIsInstance(app.screen, HistoryScreen)
                self.assertIsNotNone(app.screen.query_one("#history-title", Label))

        asyncio.run(run())

    def test_history_entries_are_wrapped(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                app.history.record(
                    HistoryEntry(
                        46,
                        1,
                        1,
                        "Carta de Paulo aos Coríntios 1:1",
                    )
                )
                app.push_screen(HistoryScreen())
                await pilot.pause()

                history = app.screen
                row = history.query_one("#history-list", ListView).children[0]
                label = row.query_one(Label)

                self.assertEqual(str(row.styles.height), "auto")
                self.assertEqual(str(row.styles.margin.bottom), "0")
                self.assertEqual(str(label.styles.height), "auto")
                self.assertEqual(label.styles.text_overflow, "fold")

        asyncio.run(run())

    def test_history_down_from_filter_focuses_first_entry(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                app.history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))
                app.push_screen(HistoryScreen())
                await pilot.pause()

                history = app.screen
                history.action_focus_filter()
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()

                list_view = history.query_one("#history-list", ListView)
                self.assertIs(app.focused, list_view)
                self.assertEqual(list_view.index, 0)

        asyncio.run(run())

    def test_history_up_from_first_entry_focuses_filter(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                app.history.record(HistoryEntry(1, 1, 1, "Genesis 1:1"))
                app.push_screen(HistoryScreen())
                await pilot.pause()

                history = app.screen
                await pilot.press("up")
                await pilot.pause()

                self.assertIs(app.focused, history.query_one("#history-filter"))

        asyncio.run(run())

    def test_go_to_completion_arrows_cycle_matches(self):
        async def run():
            app = Bibleit()

            async with app.run_test() as pilot:
                app.pop_screen()
                bible_view = app.query_exactly_one(BibleView)
                bible_view.views.append(View(NavigationState(), AmbiguousFakeTranslation()))
                status = app.query_exactly_one(StatusBar)
                status.open_command()
                status._set_command_value("Da")
                await pilot.pause()

                status._show_completions(["Daniel", "Darius"])

                self.assertEqual(status._completion_matches, ["Daniel", "Darius"])
                self.assertEqual(status._completion_index, 0)

                await pilot.press("right")
                await pilot.pause()
                self.assertEqual(status._completion_index, 1)

                await pilot.press("left")
                await pilot.pause()
                self.assertEqual(status._completion_index, 0)

        asyncio.run(run())

    def test_go_to_submit_uses_active_completion(self):
        async def run():
            app = Bibleit()
            submitted = []

            async with app.run_test():
                app.pop_screen()
                bible_view = app.query_exactly_one(BibleView)
                bible_view.views.append(View(NavigationState(), AmbiguousFakeTranslation()))
                bible_view.go_to_command = submitted.append
                status = app.query_exactly_one(StatusBar)
                status.open_command()
                status._set_command_value("Da")
                status._show_completions(["Daniel", "Darius"], 1)

                status.on_input_submitted(FakeInputEvent("status-command", "Da"))

                self.assertEqual(submitted, ["Darius "])

        asyncio.run(run())

    def test_go_to_typing_shows_completion_matches(self):
        async def run():
            app = Bibleit()

            async with app.run_test():
                app.pop_screen()
                bible_view = app.query_exactly_one(BibleView)
                bible_view.views.append(View(NavigationState(), FakeTranslation()))
                status = app.query_exactly_one(StatusBar)
                status.open_command()
                status._set_command_value("joao")

                status.on_input_changed(FakeInputEvent("status-command", "joao"))

                self.assertEqual(status._completion_matches, ["Primeira Carta de João"])
                self.assertEqual(status._completion_index, 0)

        asyncio.run(run())

    def test_browser_theme_toggle_does_not_save_config(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict(
                "os.environ",
                {
                    "BIBLEIT_CONFIG_FILE": path,
                    "TEXTUAL_DRIVER": "textual.drivers.web_driver:WebDriver",
                },
                clear=True,
            ):
                save_config({"THEME": "light"})
                app = Bibleit()

                app.action_toggle_theme()

                self.assertTrue(app.dark_theme)
                self.assertEqual(load_config(), {"THEME": "light"})


class LivePublisherTests(unittest.TestCase):
    def test_uses_serve_public_url_for_local_terminal_control(self):
        with patch.dict(
            "os.environ",
            {"BIBLEIT_SERVE_PUBLIC_URL": "https://bibleit.mittel.site/"},
            clear=True,
        ):
            self.assertEqual(LivePublisher().url, "https://bibleit.mittel.site")

    def test_live_url_takes_precedence_over_serve_public_url(self):
        with patch.dict(
            "os.environ",
            {
                "BIBLEIT_LIVE_URL": "https://live.example",
                "BIBLEIT_SERVE_PUBLIC_URL": "https://bibleit.mittel.site",
            },
            clear=True,
        ):
            self.assertEqual(LivePublisher().url, "https://live.example")

    def test_live_url_uses_config_before_serve_public_url(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"LIVE_URL": "https://config-live.example"})

            with patch.dict(
                "os.environ",
                {
                    "BIBLEIT_CONFIG_FILE": path,
                    "BIBLEIT_SERVE_PUBLIC_URL": "https://bibleit.mittel.site",
                },
                clear=True,
            ):
                self.assertEqual(LivePublisher().url, "https://config-live.example")

    def test_live_token_is_sent_as_bearer_header(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": "secret"}, clear=True):
            publisher = LivePublisher()

            self.assertEqual(
                publisher._headers()["Authorization"],
                "Bearer secret",
            )

    def test_live_token_uses_config(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"LIVE_TOKEN": "secret"})
                publisher = LivePublisher()

            self.assertEqual(
                publisher._headers()["Authorization"],
                "Bearer secret",
            )

    def test_verse_payload_adds_increasing_sequence(self):
        publisher = LivePublisher()

        first = publisher.verse_payload("Genesis 1:1 First", "KJV")
        second = publisher.verse_payload("Genesis 1:2 Second", "KJV")

        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(first["publisher_id"], second["publisher_id"])
        self.assertEqual(first["translations"][0]["translation"], "KJV")

    def test_bundle_payload_includes_multiple_translations(self):
        publisher = LivePublisher()

        payload = publisher.bundle_payload(
            [
                ("KJV", "Psalms 119:25 My soul cleaveth unto the dust."),
                ("NVIPT", "Salmos 119:25 Agora estou prostrado no pó."),
            ]
        )

        self.assertEqual(payload["reference"], "Psalms 119:25")
        self.assertEqual([v["translation"] for v in payload["translations"]], ["KJV", "NVIPT"])
        self.assertEqual(payload["sequence"], 1)

    def test_verse_payload_returns_none_for_invalid_row(self):
        publisher = LivePublisher()

        self.assertIsNone(publisher.verse_payload("not a verse", "KJV"))

    def test_disable_live_now_turns_off_remote_live_mode(self):
        bible_view = BibleView()
        view = FakeView()
        bible_view.state.live = True
        bible_view.views.append(view)

        bible_view.disable_live_now()

        self.assertFalse(bible_view.state.live)
        self.assertEqual(view.live.values, [False])


if __name__ == "__main__":
    unittest.main()
