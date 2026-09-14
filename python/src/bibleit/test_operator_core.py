from __future__ import annotations

import asyncio
import subprocess
import sys
import unittest
from pathlib import Path

from bibleit import reader, translation
from bibleit.operator import (
    CapabilityError,
    CommandValidationError,
    OperatorError,
    OperatorCapabilities,
    OperatorService,
    OperatorSession,
    PublishError,
    RelayTarget,
)
from bibleit.operator.models import GotoReference, InstallEvent, StateEvent, parse_command

LINES = [
    "Genesis 1:1 In the beginning <S>7225</S>.",
    "Genesis 1:2 And the earth was without form.",
    "Genesis 1:3 And God said, Let there be light.",
    "Genesis 2:1 Thus the heavens and the earth were finished.",
    "Matthew 1:1 The book of the generation of Jesus Christ <S>2424</S>.",
]


class FakeValue:
    def __init__(self, value):
        self.value = value

    def memoryview(self):
        return memoryview(self.value.encode())


class FakeCursor:
    def __init__(self, values, index=0):
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
    def __init__(self, slug="KJV", name="King James", lines=None):
        self.slug = slug
        self.closed = False
        self.lines = list(lines or LINES)
        self.header = translation.TranslationHeader(
            name,
            slug,
            {
                "Genesis": translation.TranslationChapter(1, 1, "Genesis", 1, 2),
                "Matthew": translation.TranslationChapter(40, 40, "Matthew", 40, 1),
            },
        )
        self._strongs = {
            "H7225": translation.StrongEntry("H7225", definition="beginning"),
            "G2424": translation.StrongEntry("G2424", definition="Jesus"),
        }

    @property
    def strongs(self):
        return self._strongs

    def resolve_bookid(self, name):
        return self.header.resolve_bookid(name)

    def _position(self, ref):
        target = reader.target_row_ref(ref)
        for index, line in enumerate(self.lines):
            row = reader.row_ref(self, line)
            if row and (row.bookid, row.chapter, row.verse) >= (target.bookid, target.chapter, target.verse):
                return index
        return len(self.lines)

    def cursor_from(self, ref):
        return FakeCursor(self.lines, self._position(ref))

    def cursor_chapter(self, ref):
        target = reader.target_row_ref(ref)
        lines = [
            line
            for line in self.lines
            if (row := reader.row_ref(self, line)) and row.bookid == target.bookid and row.chapter == target.chapter
        ]
        return FakeCursor(lines)

    def read(self, ref):
        target = reader.target_row_ref(ref)
        return FakeCursor(
            [line for line in self.lines if (row := reader.row_ref(self, line)) and row.bookid == target.bookid]
        )

    def close(self):
        self.closed = True


class FakeCatalog:
    def __init__(self):
        self.available = {"KJV": FakeTranslation()}
        self.installed = []
        self.removed = []

    async def list(self):
        from bibleit.operator.models import TranslationCatalogState

        return TranslationCatalogState(tuple(self.available))

    async def open(self, slug):
        if slug not in self.available:
            raise ValueError(f"translation not found: {slug}")
        return self.available[slug]

    async def install(self, slug):
        self.installed.append(slug)

    async def remove(self, slug):
        self.removed.append(slug)


class FakeTarget:
    def __init__(self, name="relay"):
        self.name = name
        self.payloads = []
        self.live_values = []
        self.fail_publish = False
        self.block_next_publish = False
        self.fail_blocked_publish = False
        self.publish_started = asyncio.Event()
        self.release_publish = asyncio.Event()

    async def publish(self, payload):
        if self.block_next_publish:
            self.block_next_publish = False
            self.publish_started.set()
            await self.release_publish.wait()
            if self.fail_blocked_publish:
                raise OSError("offline")
        if self.fail_publish:
            raise OSError("offline")
        self.payloads.append(payload)

    async def set_live(self, live):
        self.live_values.append(live)


class RejectedRelayPublisher:
    async def set_live(self, _live):
        return False


class OperatorCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.catalog = FakeCatalog()
        self.target = FakeTarget()
        self.session = OperatorSession(targets=[self.target])
        self.service = OperatorService(session=self.session, catalog=self.catalog)

    async def asyncTearDown(self):
        await self.service.close()

    async def test_fake_host_can_open_read_resolve_search_and_look_up_strongs(self):
        await self.service.open_translation("KJV")

        self.assertEqual(self.service.state().active, "KJV")
        self.assertEqual(self.service.books()[0].name, "Genesis")
        self.assertTrue(self.service.resolve("gen 1:2").exists)
        self.assertEqual((await self.service.search("earth"))[0].reference, "Genesis 1:2")
        self.assertEqual((await self.service.strongs("H7225")).definition, "beginning")

    async def test_typed_commands_drive_the_session(self):
        await self.service.open_translation("KJV")
        await self.service.execute(GotoReference(1, 1, 3))

        self.assertEqual(self.service.state().ref.verse, 3)

    async def test_transport_command_parser_is_strict(self):
        with self.assertRaises(CommandValidationError):
            parse_command("set_live", {"live": "yes"})
        with self.assertRaises(CommandValidationError):
            parse_command("next_verse", {"surprise": True})
        with self.assertRaises(CommandValidationError):
            parse_command("goto_ref", {"bookid": True})

    async def test_publish_failure_rolls_back_reference_and_sequence(self):
        await self.service.open_translation("KJV")
        await self.service.command("set_live", {"live": True})
        old_state = self.service.state()
        self.target.fail_publish = True

        with self.assertRaises(PublishError):
            await self.service.command("goto_ref", {"bookid": 1, "chapter": 1, "verse": 2})

        self.assertEqual(self.service.state().ref, old_state.ref)
        self.assertEqual(self.service.state().sequence, old_state.sequence)

    async def test_partial_multi_target_publish_is_compensated_without_reusing_sequence(self):
        first = FakeTarget("first")
        second = FakeTarget("second")
        session = OperatorSession(targets=[first, second])
        service = OperatorService(session=session, catalog=self.catalog)
        await service.open_translation("KJV")
        await session.set_live(True)
        committed = first.payloads[-1]
        second.fail_publish = True

        with self.assertRaises(PublishError):
            await session.goto_ref(translation.TranslationRef(1, 1, 2))

        self.assertEqual(service.state().ref.verse, 1)
        self.assertEqual(session.sequence, 3)
        self.assertEqual([payload["sequence"] for payload in first.payloads], [1, 2, 3])
        self.assertEqual(first.payloads[-1]["translations"], committed["translations"])
        await service.close()

    async def test_goto_ref_rejects_references_not_present_in_an_open_translation(self):
        await self.service.open_translation("KJV")
        old_state = self.service.state()

        with self.assertRaisesRegex(OperatorError, "Reference not found"):
            await self.session.goto_ref(translation.TranslationRef(999, 1, 1))

        self.assertEqual(self.service.state().ref, old_state.ref)
        self.assertEqual(self.service.state().sequence, old_state.sequence)

    async def test_failed_publish_cannot_rollback_a_later_concurrent_transition(self):
        await self.service.open_translation("KJV")
        await self.session.set_live(True)
        original_sequence = self.session.sequence
        self.target.block_next_publish = True
        self.target.fail_blocked_publish = True

        failing = asyncio.create_task(self.session.goto_ref(translation.TranslationRef(1, 1, 2)))
        await self.target.publish_started.wait()
        succeeding = asyncio.create_task(self.session.goto_ref(translation.TranslationRef(1, 1, 3)))
        self.target.release_publish.set()

        with self.assertRaises(PublishError):
            await failing
        await succeeding

        self.assertEqual(self.service.state().ref.verse, 3)
        self.assertEqual(self.service.state().sequence, original_sequence + 1)

    async def test_close_disables_live_targets_before_releasing_translations(self):
        await self.service.open_translation("KJV")
        await self.session.set_live(True)

        await self.service.close()

        self.assertFalse(self.session.state.live)
        self.assertEqual(self.target.live_values[-1], False)

    async def test_relay_target_rejects_unacknowledged_live_state_changes(self):
        with self.assertRaisesRegex(PublishError, "live-state"):
            await RelayTarget(RejectedRelayPublisher()).set_live(True)

    async def test_closing_session_unblocks_waiting_subscription_consumers(self):
        subscription = self.service.subscribe(include_initial=False)
        waiting = asyncio.create_task(subscription.get())
        await asyncio.sleep(0)

        await self.session.close()

        with self.assertRaises(StopAsyncIteration):
            await waiting

    async def test_subscribers_receive_typed_events_and_can_unsubscribe(self):
        subscription = self.service.subscribe()
        self.assertIsInstance(await subscription.get(), StateEvent)
        await self.service.open_translation("KJV")
        event = await subscription.get()
        self.assertIsInstance(event, StateEvent)
        self.assertEqual(event.state.active, "KJV")
        subscription.close()
        await self.service.command("set_strongs", {"strongs": True})
        self.assertTrue(subscription.empty())

    async def test_slow_subscriber_keeps_the_newest_event(self):
        subscription = self.service.subscribe(include_initial=False, max_events=1)
        await self.service.open_translation("KJV")
        await self.service.command("set_strongs", {"strongs": True})

        event = subscription.get_nowait()
        self.assertTrue(event.state.strongs)

    async def test_translation_mutations_are_denied_unless_host_grants_them(self):
        with self.assertRaises(CapabilityError):
            self.service.install_translation("KJV")
        with self.assertRaises(CapabilityError):
            await self.service.remove_translation("KJV")
        with self.assertRaises(CapabilityError):
            await self.service.write_config({"DEFAULT_TRANSLATION": "KJV"})

    async def test_granted_install_reports_progress(self):
        service = OperatorService(
            session=OperatorSession(),
            catalog=self.catalog,
            capabilities=OperatorCapabilities(install_translations=True),
        )
        subscription = service.subscribe(include_initial=False)
        task = service.install_translation("KJV")
        await task

        events = [subscription.get_nowait(), subscription.get_nowait()]
        self.assertEqual([event.state for event in events], ["installing", "installed"])
        self.assertTrue(all(isinstance(event, InstallEvent) for event in events))
        await service.close()

    async def test_viewers_are_counted_per_target(self):
        self.session.set_viewers("local", 3)
        self.session.set_viewers("relay", 4)

        self.assertEqual(self.service.state().viewers, 7)
        self.assertEqual(self.service.state().viewer_counts, {"local": 3, "relay": 4})

    async def test_strongs_prefix_uses_the_row_testament(self):
        await self.service.open_translation("KJV")
        old_row = self.service.verse_window(before=0, total=1).columns[0].rows[0]
        await self.service.command("goto", {"value": "Matthew 1:1"})
        new_row = self.service.verse_window(before=0, total=1).columns[0].rows[0]

        self.assertIn('data-code="H7225"', old_row.html)
        self.assertIn('data-code="G2424"', new_row.html)


class FrameworkIsolationTests(unittest.TestCase):
    def test_operator_package_imports_without_web_frameworks(self):
        script = """
import builtins
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'aiohttp', 'fastapi', 'textual'}:
        raise AssertionError(f'web framework imported: {name}')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import bibleit.operator
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
