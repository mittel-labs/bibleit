from __future__ import annotations

import unittest
from unittest.mock import patch

from bibleit import cli, translation


class FakeView:
    def __init__(self, value: str):
        self.value = value

    def decode(self):
        return self.value


class FakeCursor:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class FakeTranslation:
    slug = "TEST"

    def __init__(self):
        self.header = translation.TranslationHeader(
            name="Test Translation",
            slug=self.slug,
            chapters={
                "Genesis": translation.TranslationChapter(1, 1, "Genesis", 1, 50),
                "Daniel": translation.TranslationChapter(27, 27, "Daniel", 27, 12),
            },
        )
        self.read_refs = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def resolve_bookid(self, book_name: str):
        return self.header.resolve_bookid(book_name)

    def read(self, ref):
        self.read_refs.append(ref)
        return FakeCursor(
            [
                FakeView("Daniel 9:2 No primeiro ano"),
                FakeView("Daniel 9:3 Por isso me voltei"),
            ]
        )


class CliTests(unittest.TestCase):
    def test_parse_cli_ref_supports_book_chapter_verse_range(self):
        ref = cli.parse_cli_ref("dani 9:2-15", FakeTranslation())

        self.assertEqual(ref, translation.TranslationRef(27, 9, 2, 15))

    def test_parse_cli_ref_supports_dot_reference(self):
        ref = cli.parse_cli_ref("dani 9.2", FakeTranslation())

        self.assertEqual(ref, translation.TranslationRef(27, 9, 2))

    def test_parse_cli_ref_reads_entire_chapter_without_verse(self):
        ref = cli.parse_cli_ref("dani 9", FakeTranslation())

        self.assertEqual(ref, translation.TranslationRef(27, 9))

    def test_clean_row_removes_markup(self):
        self.assertEqual(
            cli._clean_row("John 3:16 <b>For</b><S>25</S><br>God &amp; love"),
            "John 3:16 For God & love",
        )

    def test_clean_row_keeps_strongs_when_enabled(self):
        self.assertEqual(
            cli._clean_row("John 3:16 <b>For</b><S>25</S><br>God &amp; love", keep_strongs=True),
            "John 3:16 For25 God & love",
        )

    def test_main_prints_reference_without_opening_tui(self):
        fake = FakeTranslation()
        header = fake.header

        with (
            patch.object(cli.translation, "get_installed", return_value={"TEST": header}),
            patch.object(cli.translation, "get_translation_available", return_value=header),
            patch.object(cli.translation, "is_installed", return_value=True),
            patch.object(cli.translation, "open", return_value=fake),
            patch("sys.stdout") as stdout,
        ):
            rc = cli.main(["-t", "TEST", "dani", "9.2"])

        self.assertEqual(rc, 0)
        self.assertEqual(fake.read_refs, [translation.TranslationRef(27, 9, 2)])
        stdout.write.assert_any_call("Daniel 9:2 No primeiro ano\nDaniel 9:3 Por isso me voltei\n")

    def test_live_accepts_host_and_port(self):
        with patch("bibleit.live.main") as live_main:
            rc = cli.main(["--live", "127.0.0.1", "9001"])

        self.assertEqual(rc, 0)
        live_main.assert_called_once_with(host="127.0.0.1", port="9001")

    def test_live_short_alias_accepts_host_and_port(self):
        with patch("bibleit.live.main") as live_main:
            rc = cli.main(["-l", "0.0.0.0", "8000"])

        self.assertEqual(rc, 0)
        live_main.assert_called_once_with(host="0.0.0.0", port="8000")


if __name__ == "__main__":
    unittest.main()
