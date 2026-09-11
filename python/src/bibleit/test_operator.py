from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from bibleit import operator, reader, translation
from bibleit.operator import OperatorError, OperatorSession

LINES = [
    "Genesis 1:1 In the beginning God created the heaven and the earth.",
    "Genesis 1:2 And the earth was without form, and void.",
    "Genesis 1:3 And God said, Let there be light.",
    "Genesis 2:1 Thus the heavens and the earth were finished.",
    "Matthew 1:1 The book of the generation of Jesus Christ.",
]

PT_LINES = [
    "Gênesis 1:1 No princípio criou Deus os céus e a terra.",
    "Gênesis 1:2 E a terra era sem forma e vazia.",
]


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
    def __init__(self, slug: str = "KJV", name: str = "King James", lines=None, books=None):
        self.slug = slug
        self.closed = False
        self.header = translation.TranslationHeader(
            name=name,
            slug=slug,
            chapters=books
            or {
                "Genesis": translation.TranslationChapter(1, 1, "Genesis", 1, 2),
                "Matthew": translation.TranslationChapter(40, 40, "Matthew", 40, 28),
            },
        )
        self.lines = LINES if lines is None else lines

    def resolve_bookid(self, book_name: str):
        return self.header.resolve_bookid(book_name)

    def _position(self, ref: translation.TranslationRef) -> int:
        target = reader.target_row_ref(ref)

        for index, line in enumerate(self.lines):
            row = reader.row_ref(self, line)

            if row is None:
                continue

            if (row.bookid, row.chapter, row.verse) >= (target.bookid, target.chapter, target.verse):
                return index

        return len(self.lines)

    def cursor_from(self, ref: translation.TranslationRef):
        return FakeCursor(self.lines, self._position(ref))

    def cursor_chapter(self, ref: translation.TranslationRef):
        target = reader.target_row_ref(ref)
        lines = []

        for line in self.lines:
            row = reader.row_ref(self, line)

            if row and row.bookid == target.bookid and row.chapter == target.chapter:
                lines.append(line)

        return FakeCursor(lines)

    def close(self):
        self.closed = True


class FakeTarget:
    name = "fake"

    def __init__(self):
        self.payloads: list[dict] = []
        self.live: list[bool] = []

    async def publish(self, payload: dict) -> None:
        self.payloads.append(payload)

    async def set_live(self, live: bool) -> None:
        self.live.append(live)


class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self.target = FakeTarget()
        self.session = OperatorSession(targets=[self.target])
        self.translations = {"KJV": FakeTranslation()}

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def open(self, slug: str = "KJV"):
        with patch.object(translation, "open", side_effect=lambda value: self.translations[value]):
            self.run_async(self.session.open_translation(slug))

    def open_and(self, coroutine_factory, slug: str = "KJV"):
        async def run():
            with patch.object(translation, "open", side_effect=lambda value: self.translations[value]):
                await self.session.open_translation(slug)

            await coroutine_factory()

        return self.run_async(run())


class OpenTranslationTest(SessionTestCase):
    def test_opening_activates_the_translation(self):
        self.open()

        self.assertEqual(self.session.active().slug, "KJV")
        self.assertEqual(self.session.snapshot()["translations"], [{"slug": "KJV", "name": "King James"}])

    def test_opening_another_translation_keeps_the_active_one(self):
        self.translations["NVIPT"] = FakeTranslation("NVIPT", "Nova Versão", PT_LINES)

        async def run():
            await self.session.open_translation("NVIPT")

        self.open_and(run)

        self.assertEqual(self.session.active().slug, "KJV")
        self.assertEqual(self.session.reference_payload()["book"], "Genesis")

    def test_opening_twice_is_a_no_op(self):
        self.open()
        self.open()

        self.assertEqual(len(self.session.translations), 1)

    def test_reports_a_translation_that_cannot_be_opened(self):
        async def run():
            with patch.object(translation, "open", side_effect=ValueError("translation not found: NOPE")):
                with self.assertRaises(OperatorError):
                    await self.session.open_translation("NOPE")

        self.run_async(run())

    def test_closing_releases_the_translation(self):
        self.open()
        opened = self.session.translations[0]

        self.run_async(self.session.close_translation("KJV"))

        self.assertTrue(opened.closed)
        self.assertEqual(self.session.translations, [])
        self.assertIsNone(self.session.active())

    def test_aligns_the_reference_to_the_first_book_when_missing(self):
        self.session.state.bookid = 66
        self.session.state.chapter = 9
        self.session.state.verse = 9
        self.open()

        self.assertEqual(self.session.state.bookid, 1)
        self.assertEqual(self.session.state.chapter, 1)
        self.assertEqual(self.session.state.verse, 1)


class NavigationTest(SessionTestCase):
    def test_goto_resolves_a_fuzzy_reference(self):
        self.open_and(lambda: self.session.goto("gen 1.3"))

        self.assertEqual(self.session.state.chapter, 1)
        self.assertEqual(self.session.state.verse, 3)

    def test_goto_reports_a_missing_reference(self):
        async def missing():
            with self.assertRaises(OperatorError):
                await self.session.goto("gen 9:9")

        self.open_and(missing)

    def test_goto_reports_an_unparsable_reference(self):
        async def unparsable():
            with self.assertRaises(OperatorError):
                await self.session.goto("nowhere at all")

        self.open_and(unparsable)

    def test_next_and_previous_verse_step_through_the_index(self):
        async def walk():
            await self.session.next_verse()
            self.assertEqual(self.session.state.verse, 2)
            await self.session.next_verse()
            self.assertEqual(self.session.state.verse, 3)
            await self.session.previous_verse()
            self.assertEqual(self.session.state.verse, 2)

        self.open_and(walk)

    def test_next_verse_crosses_into_the_next_chapter(self):
        async def walk():
            await self.session.goto("gen 1:3")
            await self.session.next_verse()

            self.assertEqual(self.session.state.chapter, 2)
            self.assertEqual(self.session.state.verse, 1)

        self.open_and(walk)

    def test_previous_verse_at_the_start_stays_put(self):
        async def walk():
            await self.session.previous_verse()

            self.assertEqual((self.session.state.chapter, self.session.state.verse), (1, 1))

        self.open_and(walk)

    def test_chapter_end_moves_to_the_last_verse(self):
        async def walk():
            await self.session.chapter_end()

            self.assertEqual(self.session.state.verse, 3)

        self.open_and(walk)

    def test_chapter_start_moves_to_the_first_verse(self):
        async def walk():
            await self.session.goto("gen 1:3")
            await self.session.chapter_start()

            self.assertEqual(self.session.state.verse, 1)

        self.open_and(walk)

    def test_next_and_previous_chapter(self):
        async def walk():
            await self.session.next_chapter()
            self.assertEqual(self.session.state.chapter, 2)
            await self.session.previous_chapter()
            self.assertEqual(self.session.state.chapter, 1)

        self.open_and(walk)

    def test_navigation_without_a_translation_is_reported(self):
        async def run():
            with self.assertRaises(OperatorError):
                await self.session.next_verse()

        self.run_async(run())


class PublishTest(SessionTestCase):
    def test_nothing_is_published_until_live(self):
        self.open_and(lambda: self.session.goto("gen 1:2"))

        self.assertEqual(self.target.payloads, [])

    def test_going_live_publishes_the_current_verse(self):
        self.open_and(lambda: self.session.set_live(True))

        self.assertEqual(self.target.live, [True])
        self.assertEqual(self.target.payloads[-1]["reference"], "Genesis 1:1")

    def test_every_open_translation_travels_in_one_payload(self):
        self.translations["NVIPT"] = FakeTranslation("NVIPT", "Nova Versão", PT_LINES)

        async def run():
            await self.session.open_translation("NVIPT")
            await self.session.set_live(True)

        self.open_and(run)

        payload = self.target.payloads[-1]

        self.assertEqual([verse["translation"] for verse in payload["translations"]], ["KJV", "NVIPT"])

    def test_the_sequence_advances_with_every_publish(self):
        async def run():
            await self.session.set_live(True)
            await self.session.goto("gen 1:2")
            await self.session.goto("gen 1:3")

        self.open_and(run)

        sequences = [payload["sequence"] for payload in self.target.payloads]

        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(set(sequences)), len(sequences))

    def test_going_to_a_reference_marks_history(self):
        async def run():
            await self.session.set_live(True)
            await self.session.goto("gen 1:2")

        self.open_and(run)

        self.assertTrue(self.target.payloads[-1]["history"])

    def test_stepping_a_verse_does_not_mark_history(self):
        async def run():
            await self.session.set_live(True)
            await self.session.next_verse()

        self.open_and(run)

        self.assertNotIn("history", self.target.payloads[-1])

    def test_leaving_live_tells_the_target(self):
        async def run():
            await self.session.set_live(True)
            await self.session.set_live(False)

        self.open_and(run)

        self.assertEqual(self.target.live, [True, False])

    def test_viewer_count_comes_from_a_counting_target(self):
        class Hub:
            def client_count(self):
                return 7

            async def publish(self, payload):
                pass

            async def set_live(self, live):
                pass

        session = OperatorSession(targets=[operator.HubTarget(Hub())])
        session.refresh_viewers()

        self.assertEqual(session.viewers, 7)
        self.assertTrue(session.connected)


class VersesTest(SessionTestCase):
    def test_returns_a_window_per_open_translation(self):
        self.translations["NVIPT"] = FakeTranslation("NVIPT", "Nova Versão", PT_LINES)

        async def run():
            await self.session.open_translation("NVIPT")

        self.open_and(run)

        payload = self.session.verses(before=0, total=2)

        self.assertEqual([column["translation"] for column in payload["columns"]], ["KJV", "NVIPT"])
        self.assertEqual(payload["columns"][0]["rows"][0]["reference"], "Genesis 1:1")
        self.assertEqual(payload["columns"][0]["index"], 0)
        self.assertEqual(payload["ref"]["reference"], "Genesis 1:1")

    def test_rows_carry_rendered_html_and_plain_text(self):
        self.translations["KJV"] = FakeTranslation(lines=["Genesis 1:1 Let <b>light</b> <S>216</S> be."])
        self.open()

        row = self.session.verses(before=0, total=1)["columns"][0]["rows"][0]

        self.assertIn("<b>light</b>", row["html"])
        self.assertIn('data-code="216"', row["html"])
        self.assertEqual(row["text"], "Let light be.")
        self.assertEqual(row["bookid"], 1)

    def test_caps_the_window_size(self):
        self.open()

        self.assertLessEqual(
            len(self.session.verses(total=operator.MAX_TOTAL * 10)["columns"][0]["rows"]),
            operator.MAX_TOTAL,
        )


class CommandTest(SessionTestCase):
    def test_dispatches_navigation_commands(self):
        async def run():
            await self.session.command("next_verse")

        self.open_and(run)

        self.assertEqual(self.session.state.verse, 2)

    def test_dispatches_a_reference_command(self):
        async def run():
            await self.session.command("goto_ref", {"bookid": 1, "chapter": 1, "verse": 3})

        self.open_and(run)

        self.assertEqual(self.session.state.verse, 3)

    def test_dispatches_the_strongs_toggle(self):
        async def run():
            await self.session.command("set_strongs", {"strongs": True})

        self.open_and(run)

        self.assertTrue(self.session.snapshot()["strongs"])

    def test_rejects_an_unknown_command(self):
        async def run():
            with self.assertRaises(OperatorError):
                await self.session.command("launch_rocket")

        self.run_async(run())

    def test_set_active_requires_an_open_translation(self):
        async def run():
            with self.assertRaises(OperatorError):
                await self.session.set_active("NVIPT")

        self.open_and(run)


class ListenerTest(SessionTestCase):
    def test_state_changes_reach_listeners(self):
        async def run():
            queue = self.session.listen()
            await self.session.goto("gen 1:2")
            event = queue.get_nowait()

            self.assertEqual(event["type"], "state")
            self.assertEqual(event["state"]["ref"]["verse"], 2)

            self.session.forget(queue)
            await self.session.goto("gen 1:3")

            self.assertTrue(queue.empty())

        self.open_and(run)


if __name__ == "__main__":
    unittest.main()
