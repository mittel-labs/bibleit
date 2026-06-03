from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MOCK_LANGUAGES = [
    {
        "language": "English",
        "translations": [
            {
                "short_name": "TEST",
                "full_name": "Test Translation",
            }
        ],
    }
]

MOCK_BOOKS = {
    "TEST": [
        {
            "bookid": 1,
            "name": "Genesis",
            "chronorder": 1,
            "chapters": 2,
        },
        {
            "bookid": 2,
            "name": "Exodus",
            "chronorder": 2,
            "chapters": 1,
        },
    ]
}

with (
    patch("bibleit.translation.get_languages_config", return_value=MOCK_LANGUAGES),
    patch("bibleit.translation.get_translations_books", return_value=MOCK_BOOKS),
):
    from bibleit import translation


class TranslationNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        translation.get_translations_available.cache_clear()
        translation.get_languages_available.cache_clear()

        self.patches = [
            patch.object(translation, "TRANSLATIONS_DIR", self.root),
            patch.object(
                translation,
                "get_languages_config",
                return_value=MOCK_LANGUAGES,
            ),
            patch.object(
                translation,
                "get_translations_books",
                side_effect=lambda slug=None: (MOCK_BOOKS.get(slug) if slug is not None else MOCK_BOOKS),
            ),
        ]

        for patcher in self.patches:
            patcher.start()

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

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_read_range_stops_at_end_verse(self):
        with translation.open("TEST") as bible:
            rows = [verse.decode() for verse in bible.read(translation.TranslationRef(1, 1, 1, 2))]

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

    def test_header_resolves_case_insensitive_unique_prefix(self):
        self.assertEqual(self.header.resolve_bookid("gen"), 1)
        self.assertEqual(self.header.resolve_bookid("EXO"), 2)

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
