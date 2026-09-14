from __future__ import annotations

import unittest

from bibleit import live_payload

GENESIS = "Genesis 1:1 In the beginning God created the heaven and the earth."
GENESIS_PT = "Gênesis 1:1 No princípio criou Deus os céus e a terra."


class ParseVerseLineTest(unittest.TestCase):
    def test_builds_a_verse_with_its_reference(self):
        verse = live_payload.parse_verse_line("KJV", GENESIS)

        self.assertEqual(verse.translation, "KJV")
        self.assertEqual(verse.reference, "Genesis 1:1")
        self.assertEqual(verse.text, "In the beginning God created the heaven and the earth.")

    def test_cleans_translation_markup(self):
        verse = live_payload.parse_verse_line("KJV", "Genesis 1:3 Let <b>light</b> <S>216</S><br>be.")

        self.assertEqual(verse.text, "Let light be.")

    def test_returns_none_without_a_reference(self):
        self.assertIsNone(live_payload.parse_verse_line("KJV", "not a verse"))


class BundlePayloadTest(unittest.TestCase):
    def test_carries_every_translation_and_leads_with_the_first(self):
        payload = live_payload.bundle_payload(
            [("KJV", GENESIS), ("NVIPT", GENESIS_PT)],
            publisher_id="presenter",
            sequence=4,
        )

        self.assertEqual(payload["translation"], "KJV")
        self.assertEqual(payload["reference"], "Genesis 1:1")
        self.assertEqual([verse["translation"] for verse in payload["translations"]], ["KJV", "NVIPT"])
        self.assertEqual(payload["publisher_id"], "presenter")
        self.assertEqual(payload["sequence"], 4)

    def test_skips_translations_missing_the_verse(self):
        payload = live_payload.bundle_payload(
            [("KJV", GENESIS), ("NVIPT", "")],
            publisher_id="presenter",
            sequence=1,
        )

        self.assertEqual(len(payload["translations"]), 1)

    def test_returns_none_when_no_translation_has_the_verse(self):
        self.assertIsNone(
            live_payload.bundle_payload(
                [("KJV", ""), ("NVIPT", "nope")],
                publisher_id="presenter",
                sequence=1,
            )
        )


if __name__ == "__main__":
    unittest.main()
