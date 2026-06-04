from __future__ import annotations

import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

from aiohttp.test_utils import make_mocked_request

from bibleit.config import save_config
from bibleit.live import (
    HUB_KEY,
    TITLE_KEY,
    TOKEN_KEY,
    clean_verse_text,
    create_app,
    parse_verse_line,
    request_is_authorized,
    viewer_html,
)


class LiveVerseTest(unittest.TestCase):
    def test_parse_verse_line(self):
        verse = parse_verse_line("KJV", "Genesis 1:1 In the beginning God created the heaven and the earth.")

        self.assertEqual(verse.translation, "KJV")
        self.assertEqual(verse.reference, "Genesis 1:1")
        self.assertEqual(verse.text, "In the beginning God created the heaven and the earth.")

    def test_parse_multi_word_book(self):
        verse = parse_verse_line("KJV", "Song of Solomon 2:1 I am the rose of Sharon.")

        self.assertEqual(verse.book, "Song of Solomon")
        self.assertEqual(verse.chapter, 2)
        self.assertEqual(verse.verse, 1)

    def test_clean_verse_text_removes_markup_and_strongs(self):
        text = clean_verse_text("Let <b>there</b> be light <S>216</S><br>and there was light.")

        self.assertEqual(text, "Let there be light and there was light.")

    def test_create_app_has_live_hub(self):
        app = create_app("test live")

        self.assertEqual(app[TITLE_KEY], "test live")
        self.assertIsNone(app[HUB_KEY].current)

    def test_viewer_html_renders_template_with_escaped_title(self):
        rendered = viewer_html("bibleit <live>")

        self.assertIn("<title>bibleit &lt;live&gt;</title>", rendered)
        self.assertIn('id="live"', rendered)
        self.assertIn('id="textual"', rendered)
        self.assertIn('id="translation-filter"', rendered)
        self.assertIn("bibleit-selected-translations", rendered)
        self.assertNotIn("__all__", rendered)

    def test_control_requests_are_open_without_token(self):
        with patch.dict("os.environ", {}, clear=True):
            app = create_app("test live")

        request = make_mocked_request("POST", "/api/publish", app=app)

        self.assertTrue(request_is_authorized(request))

    def test_control_requests_require_matching_bearer_token(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": "secret"}, clear=True):
            app = create_app("test live")

        request = make_mocked_request(
            "POST",
            "/api/publish",
            headers={"Authorization": "Bearer secret"},
            app=app,
        )

        self.assertEqual(app[TOKEN_KEY], "secret")
        self.assertTrue(request_is_authorized(request))

    def test_control_requests_use_config_token(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"LIVE_TOKEN": "secret"})
                app = create_app("test live")

        request = make_mocked_request(
            "POST",
            "/api/publish",
            headers={"Authorization": "Bearer secret"},
            app=app,
        )

        self.assertEqual(app[TOKEN_KEY], "secret")
        self.assertTrue(request_is_authorized(request))

    def test_control_requests_reject_missing_token(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": "secret"}, clear=True):
            app = create_app("test live")

        request = make_mocked_request("POST", "/api/publish", app=app)

        self.assertFalse(request_is_authorized(request))

    def test_live_hub_ignores_stale_sequence_for_same_publisher(self):
        async def run():
            hub = create_app("test live")[HUB_KEY]

            await hub.publish(
                {
                    "publisher_id": "presenter",
                    "sequence": 2,
                    "reference": "Genesis 1:2",
                }
            )
            await hub.publish(
                {
                    "publisher_id": "presenter",
                    "sequence": 1,
                    "reference": "Genesis 1:1",
                }
            )

            self.assertEqual(hub.current["reference"], "Genesis 1:2")

        import asyncio

        asyncio.run(run())

    def test_live_hub_accepts_new_publisher_sequence(self):
        async def run():
            hub = create_app("test live")[HUB_KEY]

            await hub.publish(
                {
                    "publisher_id": "first",
                    "sequence": 10,
                    "reference": "Genesis 1:10",
                }
            )
            await hub.publish(
                {
                    "publisher_id": "second",
                    "sequence": 1,
                    "reference": "Genesis 1:1",
                }
            )

            self.assertEqual(hub.current["reference"], "Genesis 1:1")

        import asyncio

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
