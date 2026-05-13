from __future__ import annotations

import unittest

try:
    from bibleit import translation
    from bibleit.app import NavigationState, RowRef, View
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


if __name__ == "__main__":
    unittest.main()
