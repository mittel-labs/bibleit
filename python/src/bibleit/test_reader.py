from __future__ import annotations

import unittest

from bibleit import reader, translation
from bibleit.reader import Book, ParsedLine, RowRef


class FakeValue:
    def __init__(self, value: str):
        self.value = value

    def memoryview(self):
        return memoryview(self.value.encode("utf-8"))


class FakeCursor:
    def __init__(self, values, index: int = 0):
        self.values = values
        self.index = index

    def next(self):
        if self.index >= len(self.values):
            return None

        value = self.values[self.index]
        self.index += 1
        return FakeValue(value)

    def previous(self):
        if self.index <= 0:
            return None

        self.index -= 1
        return FakeValue(self.values[self.index])


class FakeTranslation:
    slug = "TEST"

    def __init__(self, lines=None, cursor_index: int = 0, raise_on_cursor: bool = False):
        self.header = translation.TranslationHeader(
            name="Test",
            slug=self.slug,
            chapters={
                "Genesis": translation.TranslationChapter(1, 1, "Genesis", 1, 50),
                "Matthew": translation.TranslationChapter(40, 40, "Matthew", 40, 28),
            },
        )
        self.lines = lines or []
        self.cursor_index = cursor_index
        self.raise_on_cursor = raise_on_cursor

    def resolve_bookid(self, book_name: str):
        return self.header.resolve_bookid(book_name)

    def cursor_from(self, ref: translation.TranslationRef):
        if self.raise_on_cursor:
            raise RuntimeError("cursor failure")

        return FakeCursor(self.lines, self.cursor_index)

    def cursor_chapter(self, ref: translation.TranslationRef):
        return FakeCursor(self.lines)


GENESIS_LINES = [
    "Genesis 1:1 In the beginning God created the heaven and the earth.",
    "Genesis 1:2 And the earth was without form, and void.",
    "Genesis 1:3 And God said, Let there be light.",
    "Genesis 1:4 And God saw the light, that it was good.",
]


class ParseLineTest(unittest.TestCase):
    def test_parses_reference_and_text(self):
        parsed = reader.parse_line("Genesis 1:1 In the beginning.")

        self.assertEqual(parsed, ParsedLine("Genesis", 1, 1, "In the beginning."))
        self.assertEqual(parsed.reference, "Genesis 1:1")

    def test_parses_multi_word_book(self):
        parsed = reader.parse_line("Song of Solomon 2:1 I am the rose of Sharon.")

        self.assertEqual(parsed.book, "Song of Solomon")
        self.assertEqual(parsed.chapter, 2)
        self.assertEqual(parsed.verse, 1)

    def test_strips_surrounding_whitespace(self):
        parsed = reader.parse_line("  Genesis 1:1 In the beginning.\n")

        self.assertEqual(parsed.text, "In the beginning.")

    def test_keeps_translation_markup_in_text(self):
        parsed = reader.parse_line("Genesis 1:1 In <b>the</b> beginning <S>7225</S>")

        self.assertEqual(parsed.text, "In <b>the</b> beginning <S>7225</S>")

    def test_returns_none_without_a_reference(self):
        self.assertIsNone(reader.parse_line("In the beginning."))


class DecodeTest(unittest.TestCase):
    def test_passes_strings_through(self):
        self.assertEqual(reader.decode("Genesis 1:1 text"), "Genesis 1:1 text")

    def test_decodes_native_views(self):
        self.assertEqual(reader.decode(FakeValue("Genesis 1:1 text")), "Genesis 1:1 text")


class RowRefTest(unittest.TestCase):
    def test_resolves_the_book_name(self):
        row = reader.row_ref(FakeTranslation(), "Genesis 1:2 And the earth.")

        self.assertEqual(row, RowRef(1, 1, 2))

    def test_returns_none_for_an_unknown_book(self):
        self.assertIsNone(reader.row_ref(FakeTranslation(), "Sirach 1:1 Wisdom."))

    def test_returns_none_without_a_translation(self):
        self.assertIsNone(reader.row_ref(None, "Genesis 1:1 In the beginning."))

    def test_target_row_ref_defaults_chapter_and_verse(self):
        ref = translation.TranslationRef(bookid=1)

        self.assertEqual(reader.target_row_ref(ref), RowRef(1, 1, 1))


class VerseLineTest(unittest.TestCase):
    def test_returns_the_line_at_the_reference(self):
        translation_ = FakeTranslation(GENESIS_LINES, cursor_index=1)
        ref = translation.TranslationRef(1, 1, 2)

        self.assertEqual(reader.verse_line(translation_, ref), GENESIS_LINES[1])

    def test_returns_none_when_the_cursor_lands_elsewhere(self):
        translation_ = FakeTranslation(GENESIS_LINES)
        ref = translation.TranslationRef(1, 1, 99)

        self.assertIsNone(reader.verse_line(translation_, ref))

    def test_returns_none_when_the_cursor_is_exhausted(self):
        translation_ = FakeTranslation([])

        self.assertIsNone(reader.verse_line(translation_, translation.TranslationRef(1, 1, 1)))

    def test_returns_none_when_the_cursor_fails(self):
        translation_ = FakeTranslation(GENESIS_LINES, raise_on_cursor=True)

        self.assertIsNone(reader.verse_line(translation_, translation.TranslationRef(1, 1, 1)))


class WindowAroundTest(unittest.TestCase):
    def test_reads_forward_from_the_reference(self):
        translation_ = FakeTranslation(GENESIS_LINES)
        window = reader.window_around(translation_, translation.TranslationRef(1, 1, 1), total=2)

        self.assertEqual(window.lines, GENESIS_LINES[:2])
        self.assertEqual(window.index, 0)

    def test_prepends_preceding_verses(self):
        translation_ = FakeTranslation(GENESIS_LINES, cursor_index=2)
        window = reader.window_around(
            translation_,
            translation.TranslationRef(1, 1, 3),
            before=2,
            total=4,
        )

        self.assertEqual(window.lines, GENESIS_LINES)
        self.assertEqual(window.index, 2)

    def test_always_reads_at_least_one_verse_forward(self):
        translation_ = FakeTranslation(GENESIS_LINES, cursor_index=3)
        window = reader.window_around(
            translation_,
            translation.TranslationRef(1, 1, 4),
            before=3,
            total=1,
        )

        self.assertEqual(window.lines, GENESIS_LINES)
        self.assertEqual(window.index, 3)

    def test_reports_no_index_when_the_reference_is_missing(self):
        translation_ = FakeTranslation(GENESIS_LINES)
        window = reader.window_around(translation_, translation.TranslationRef(1, 9, 9))

        self.assertIsNone(window.index)

    def test_exposes_the_forward_cursor_for_further_reads(self):
        translation_ = FakeTranslation(GENESIS_LINES)
        window = reader.window_around(translation_, translation.TranslationRef(1, 1, 1), total=2)

        self.assertEqual(reader.decode(window.cursor.next()), GENESIS_LINES[2])


class ChapterTest(unittest.TestCase):
    def test_chapter_last_ref_returns_the_final_verse(self):
        translation_ = FakeTranslation(GENESIS_LINES)

        self.assertEqual(
            reader.chapter_last_ref(translation_, 1, 1),
            translation.TranslationRef(1, 1, 4),
        )

    def test_chapter_last_ref_returns_none_for_an_empty_chapter(self):
        self.assertIsNone(reader.chapter_last_ref(FakeTranslation([]), 1, 1))


class BooksTest(unittest.TestCase):
    def test_lists_books_once_ordered_by_id(self):
        self.assertEqual(
            reader.books(FakeTranslation()),
            [Book(1, "Genesis", 50), Book(40, "Matthew", 28)],
        )


class StrongPrefixTest(unittest.TestCase):
    def test_old_testament_books_use_hebrew(self):
        self.assertEqual(reader.strong_prefix(39), "H")

    def test_new_testament_books_use_greek(self):
        self.assertEqual(reader.strong_prefix(40), "G")


class RenderTextualMarkupTest(unittest.TestCase):
    STRONGS = {"H7225": translation.StrongEntry(code="H7225", lemma="reshith")}

    def render(self, value: str, **kwargs) -> str:
        options = {"strongs": self.STRONGS, "show_strongs": False} | kwargs
        return reader.render_textual_markup(value, **options)

    def test_emphasises_the_reference(self):
        self.assertEqual(
            self.render("Genesis 1:1 In the beginning."),
            "[bold]Genesis 1:1 [/] In the beginning.",
        )

    def test_translates_inline_emphasis(self):
        rendered = self.render("Genesis 1:1 In <b>the</b> <i>beginning</i>.")

        self.assertIn("[bold]the[/]", rendered)
        self.assertIn("[italic]beginning[/]", rendered)

    def test_turns_breaks_into_newlines(self):
        self.assertIn("\n", self.render("Genesis 1:1 First<br>Second"))

    def test_dims_superscript(self):
        self.assertIn("[dim italic]2[/]", self.render("Genesis 1:1 Light<sup>2</sup>"))

    def test_hides_strongs_codes_by_default(self):
        rendered = self.render("Genesis 1:1 beginning <S>7225</S>")

        self.assertNotIn("7225", rendered)

    def test_shows_known_strongs_codes_when_enabled(self):
        rendered = self.render("Genesis 1:1 beginning <S>7225</S>", show_strongs=True)

        self.assertIn("app.open_strong('H7225')", rendered)
        self.assertIn("ᴴ7225", rendered)

    def test_drops_unknown_strongs_codes(self):
        rendered = self.render("Genesis 1:1 beginning <S>9999</S>", show_strongs=True)

        self.assertNotIn("9999", rendered)

    def test_uses_the_greek_prefix_when_requested(self):
        strongs = {"G26": translation.StrongEntry(code="G26", lemma="agape")}
        rendered = self.render(
            "Matthew 1:1 love <S>26</S>",
            strongs=strongs,
            show_strongs=True,
            prefix="G",
        )

        self.assertIn("app.open_strong('G26')", rendered)

    def test_keeps_codes_raw_without_a_strongs_mapping(self):
        rendered = self.render("Genesis 1:1 beginning <S>7225</S>", strongs=None)

        self.assertIn("7225", rendered)


if __name__ == "__main__":
    unittest.main()
