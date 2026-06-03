from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from bibleit import translation
    from bibleit.app import (
        BibleView,
        HistoryEntry,
        LivePublisher,
        NavigationState,
        RowRef,
        SessionHistory,
        View,
        clean_verse_text,
        next_chapter_ref,
        complete_navigation_value,
        navigation_completion_candidates,
        navigation_suggestion_value,
        parse_navigation_ref,
        previous_chapter_ref,
        running_in_browser,
        search_translation_text,
        select_navigation_completion,
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

    def resolve_bookid(self, book_name: str):
        return self.header.resolve_bookid(book_name)

    def read(self, ref: translation.TranslationRef):
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


class TextSearchTests(unittest.TestCase):
    def setUp(self):
        self.translation = FakeTranslation()

    def test_clean_verse_text_removes_rendered_markup(self):
        self.assertEqual(
            clean_verse_text("Genesis 1:1 <b>Love</b><S>25</S><br>is patient"),
            "Genesis 1:1 Love is patient",
        )

    def test_search_translation_finds_phrase_in_verse_text(self):
        results = search_translation_text(self.translation, "love is patient")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].label, "First Letter of Paul to the Corinthians 13:4")
        self.assertEqual(results[0].ref, translation.TranslationRef(46, 13, 4))

    def test_search_translation_searches_rendered_text_not_only_labels(self):
        results = search_translation_text(self.translation, "formless")

        self.assertEqual([result.label for result in results], ["Genesis 1:2"])


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

    def test_book_suggestion_skips_contains_match(self):
        self.assertIsNone(
            navigation_suggestion_value("cor 13:4", self.translation),
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

    def test_live_token_is_sent_as_bearer_header(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": "secret"}, clear=True):
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
