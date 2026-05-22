from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from bibleit import translation
    from bibleit.app import BibleView, LivePublisher, NavigationState, RowRef, View, running_in_browser
except ModuleNotFoundError as exc:
    if exc.name == "textual_autocomplete":
        raise unittest.SkipTest("textual_autocomplete is not installed") from exc
    raise


class FakeTranslation:
    slug = "TEST"

    def __init__(self):
        self.strongs = {
            "H7225": translation.StrongEntry(
                code="H7225",
                lemma="reshith",
                definition="beginning",
            )
        }

    def resolve_bookid(self, book_name: str):
        return {"Genesis": 1, "Matthew": 40}.get(book_name)


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
