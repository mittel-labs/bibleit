from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bibleit import translation


class TranslationNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.header = translation.TranslationHeader(
            name="Test Translation",
            slug="TEST",
            chapters={
                "Genesis": translation.TranslationChapter(1, 1, "Genesis", 1, 2),
                "Exodus": translation.TranslationChapter(2, 2, "Exodus", 2, 1),
            },
        )
        (self.root / "TEST.bt").write_text(
            "\n".join(
                [
                    "Genesis 1:1 In the beginning",
                    "Genesis 1:2 And the earth",
                    "Genesis 1:3 Let there be light",
                    "Genesis 2:1 Thus the heavens",
                    "Exodus 1:1 Now these are the names",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(translation, "TRANSLATIONS_DIR", self.root),
            patch.object(translation, "TRANSLATIONS_AVAILABLE", {"TEST": self.header}),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_read_range_stops_at_end_verse(self):
        with translation.open("TEST") as bible:
            rows = [
                verse.decode()
                for verse in bible.read(translation.TranslationRef(1, 1, 1, 2))
            ]

        self.assertEqual(
            rows,
            [
                "Genesis 1:1 In the beginning",
                "Genesis 1:2 And the earth",
            ],
        )

    def test_cursor_from_moves_backward_and_forward(self):
        with translation.open("TEST") as bible:
            cursor = bible.cursor_from(translation.TranslationRef(1, 1, 2))
            self.assertEqual(cursor.previous().decode(), "Genesis 1:1 In the beginning")

            cursor = bible.cursor_from(translation.TranslationRef(1, 1, 2))
            self.assertEqual(cursor.next().decode(), "Genesis 1:2 And the earth")
            self.assertEqual(cursor.next().decode(), "Genesis 1:3 Let there be light")

    def test_dictionary_cache_loads_strong_entries(self):
        (self.root / "SCGES.dictionary.json").write_text(
            json.dumps(
                [
                    {
                        "topic": "H7225",
                        "lexeme": "רֵאשִׁית",
                        "transliteration": "reshith",
                        "short_definition": "beginning",
                        "definition": "first, beginning",
                    }
                ]
            ),
            encoding="utf-8",
        )

        with translation.open("TEST") as bible:
            entry = bible.strongs["H7225"]

        self.assertEqual(entry.code, "H7225")
        self.assertEqual(entry.definition, "beginning")


if __name__ == "__main__":
    unittest.main()
