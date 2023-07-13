import unittest
from unittest.mock import patch

from bibleit import config
from bibleit.bible import Bible, BibleNotFound


class TestBible(unittest.TestCase):
    def setUp(self):
        config.label = True
        self.bible = Bible("kjv")

    def test_init(self):
        self.assertEqual(self.bible.version, "kjv")

    def test_init_invalid_version(self):
        with self.assertRaises(BibleNotFound):
            Bible("invalid")

    def test_labeled(self):
        config.set_flag("label", False)
        self.assertEqual("test", self.bible.labeled("test"))

        config.set_flag("label", True)
        self.assertEqual(
            f"✝ {self.bible.version}{config.context_ps1}\ttest",
            self.bible.labeled("test"),
        )

    def test_book(self):
        # Genesis has 1533 lines/verses in kjv
        self.assertEqual(len(self.bible.book("genesis")), 1533)

    def test_chapters(self):
        self.assertEqual(
            set(self.bible.chapters()),
            {
                "1 Chronicles",
                "1 Corinthians",
                "1 John",
                "1 Kings",
                "1 Peter",
                "1 Samuel",
                "1 Thessalonians",
                "1 Timothy",
                "2 Chronicles",
                "2 Corinthians",
                "2 John",
                "2 Kings",
                "2 Peter",
                "2 Samuel",
                "2 Thessalonians",
                "2 Timothy",
                "3 John",
                "Acts",
                "Amos",
                "Colossians",
                "Daniel",
                "Deuteronomy",
                "Ecclesiastes",
                "Ephesians",
                "Esther",
                "Exodus",
                "Ezekiel",
                "Ezra",
                "Galatians",
                "Genesis",
                "Habakkuk",
                "Haggai",
                "Hebrews",
                "Hosea",
                "Isaiah",
                "James",
                "Jeremiah",
                "Job",
                "Joel",
                "John",
                "Jonah",
                "Joshua",
                "Jude",
                "Judges",
                "Lamentations",
                "Leviticus",
                "Luke",
                "Malachi",
                "Mark",
                "Matthew",
                "Micah",
                "Nahum",
                "Nehemiah",
                "Numbers",
                "Obadiah",
                "Philemon",
                "Philippians",
                "Proverbs",
                "Psalms",
                "Revelation",
                "Romans",
                "Ruth",
                "Song of Solomon",
                "Titus",
                "Zechariah",
                "Zephaniah",
            },
        )

    def test_ref_invalid(self):
        self.assertEqual(self.bible.ref("genesis", "invalid"), [])

    def test_search(self):
        self.assertEqual(
            self.bible.search("God+created+heaven+earth"), [0, 34, 5036, 18488, 18582]
        )

    def test_count(self):
        self.assertEqual(self.bible.count("God"), 4833)

    def test_refs_range(self):
        self.assertEqual(self.bible.refs(["genesis", "1:1-3"]), [0, 1, 2])

    def test_refs_invalid(self):
        self.assertEqual(self.bible.refs(["invalid"]), [])

    @patch("bibleit.bible._TRANSLATIONS_DIR")
    def test_init_file_not_found(self, mock_dir):
        mock_dir.__truediv__.return_value.is_file.return_value = False
        with self.assertRaises(BibleNotFound):
            Bible("kjv")

    def test_ref_parse(self):
        config.set_flag("label", False)
        self.assertEqual(
            ["Genesis 1:1 In the beginning God created the heaven and the earth."],
            self.bible.ref_parse([0]),
        )
