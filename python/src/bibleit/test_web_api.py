from __future__ import annotations

import asyncio
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiohttp import WSMsgType, web
from aiohttp.test_utils import AioHTTPTestCase

from bibleit import translation
from bibleit.operator import OperatorSession
from bibleit.test_operator import PT_LINES, FakeTarget, FakeTranslation
from bibleit.web.api import API_PREFIX, add_operator_routes

MOCK_LANGUAGES = [
    translation.TranslationLanguage(
        name="English",
        translations=[
            translation.TranslationHeader(name="King James", slug="KJV", chapters={}),
            translation.TranslationHeader(name="American Standard", slug="ASV", chapters={}),
        ],
    )
]


class ApiTestCase(AioHTTPTestCase):
    local = True

    async def get_application(self):
        self.target = FakeTarget()
        self.session = OperatorSession(targets=[self.target])
        self.session.translations.append(FakeTranslation())
        self.session.active_slug = "KJV"

        app = web.Application()
        add_operator_routes(app, session=self.session, local=self.local)
        return app

    async def get_json(self, path, expect=200):
        response = await self.client.get(f"{API_PREFIX}{path}")
        self.assertEqual(response.status, expect)
        return await response.json()

    async def post_json(self, path, payload, expect=200):
        response = await self.client.post(f"{API_PREFIX}{path}", json=payload)
        self.assertEqual(response.status, expect)
        return await response.json()


class StateTest(ApiTestCase):
    async def test_state_describes_the_session(self):
        payload = await self.get_json("/state")

        self.assertEqual(payload["active"], "KJV")
        self.assertEqual(payload["ref"]["reference"], "Genesis 1:1")
        self.assertFalse(payload["live"])
        self.assertEqual(payload["targets"], ["fake"])

    async def test_verses_returns_a_rendered_window(self):
        payload = await self.get_json("/verses?before=0&total=2")

        rows = payload["columns"][0]["rows"]

        self.assertEqual([row["reference"] for row in rows], ["Genesis 1:1", "Genesis 1:2"])
        self.assertIn("beginning", rows[0]["html"])

    async def test_books_lists_the_translation(self):
        payload = await self.get_json("/books")

        self.assertEqual(payload["translation"], "KJV")
        self.assertEqual([book["name"] for book in payload["books"]], ["Genesis", "Matthew"])

    async def test_books_reports_a_translation_that_is_not_open(self):
        payload = await self.get_json("/books?translation=NVIPT", expect=400)

        self.assertIn("NVIPT", payload["error"])


class ResolveTest(ApiTestCase):
    async def test_resolves_a_fuzzy_reference(self):
        payload = await self.get_json("/resolve?q=gen+1.2")

        self.assertEqual(payload["ref"], {"bookid": 1, "chapter": 1, "verse": 2})
        self.assertTrue(payload["exists"])

    async def test_reports_a_reference_the_translation_lacks(self):
        payload = await self.get_json("/resolve?q=gen+9:9")

        self.assertFalse(payload["exists"])

    async def test_offers_book_completions(self):
        payload = await self.get_json("/resolve?q=gen")

        self.assertIn("Genesis", payload["candidates"])

    async def test_reports_an_unparsable_reference(self):
        payload = await self.get_json("/resolve?q=nowhere+at+all")

        self.assertIsNone(payload["ref"])
        self.assertIn("error", payload)


class CommandTest(ApiTestCase):
    async def test_runs_a_navigation_command_and_returns_the_state(self):
        payload = await self.post_json("/command", {"command": "next_verse"})

        self.assertEqual(payload["ref"]["verse"], 2)

    async def test_runs_a_reference_command(self):
        payload = await self.post_json(
            "/command",
            {"command": "goto_ref", "params": {"bookid": 1, "chapter": 1, "verse": 3}},
        )

        self.assertEqual(payload["ref"]["verse"], 3)

    async def test_going_live_publishes(self):
        await self.post_json("/command", {"command": "set_live", "params": {"live": True}})

        self.assertEqual(self.target.live, [True])
        self.assertEqual(self.target.payloads[-1]["reference"], "Genesis 1:1")

    async def test_reports_an_unknown_command(self):
        payload = await self.post_json("/command", {"command": "launch_rocket"}, expect=400)

        self.assertIn("launch_rocket", payload["error"])

    async def test_reports_a_command_that_cannot_run(self):
        payload = await self.post_json("/command", {"command": "goto", "params": {"value": "gen 9:9"}}, expect=400)

        self.assertIn("not found", payload["error"])

    async def test_rejects_a_body_that_is_not_json(self):
        response = await self.client.post(f"{API_PREFIX}/command", data="nope")

        self.assertEqual(response.status, 400)


class StrongsTest(ApiTestCase):
    async def test_returns_a_known_entry(self):
        self.session.translations[0].strongs = {
            "H7225": translation.StrongEntry(code="H7225", lemma="reshith", definition="beginning")
        }

        payload = await self.get_json("/strongs/h7225")

        self.assertEqual(payload["lemma"], "reshith")

    async def test_reports_an_unknown_entry(self):
        self.session.translations[0].strongs = {}

        payload = await self.get_json("/strongs/H9999", expect=404)

        self.assertIn("H9999", payload["error"])


class TranslationCatalogueTest(ApiTestCase):
    async def test_lists_languages_and_marks_what_is_installed(self):
        with (
            patch.object(translation, "get_languages_available", return_value=MOCK_LANGUAGES),
            patch.object(translation, "get_installed", return_value={"KJV": MOCK_LANGUAGES[0].translations[0]}),
        ):
            payload = await self.get_json("/translations")

        self.assertEqual(payload["installed"], ["KJV"])
        entries = payload["languages"][0]["translations"]
        self.assertEqual(entries[0], {"slug": "KJV", "name": "King James", "installed": True})
        self.assertFalse(entries[1]["installed"])

    async def test_reports_an_unreachable_catalogue(self):
        with patch.object(translation, "get_languages_available", side_effect=LookupError("no network")):
            payload = await self.get_json("/translations", expect=502)

        self.assertIn("no network", payload["error"])

    async def test_install_reports_progress_to_listeners(self):
        queue = self.session.listen()

        with (
            patch.object(translation, "is_installed", return_value=False),
            patch.object(translation, "install") as install,
            patch.object(translation, "get_index") as get_index,
        ):
            await self.post_json("/translations/ASV", None, expect=202)
            event = await queue.get()

        install.assert_called_once_with("ASV")
        get_index.assert_called_once_with("ASV")
        self.assertEqual(event, {"type": "install", "slug": "ASV", "state": "installed"})

    async def test_install_reports_failure_to_listeners(self):
        queue = self.session.listen()

        with (
            patch.object(translation, "is_installed", return_value=False),
            patch.object(translation, "install", side_effect=LookupError("download failed")),
        ):
            await self.post_json("/translations/ASV", None, expect=202)
            event = await queue.get()

        self.assertEqual(event["state"], "failed")
        self.assertIn("download failed", event["error"])

    async def test_install_of_an_installed_translation_is_a_no_op(self):
        with patch.object(translation, "is_installed", return_value=True):
            payload = await self.post_json("/translations/KJV", None)

        self.assertEqual(payload["state"], "installed")

    async def test_uninstall_closes_the_translation_first(self):
        opened = self.session.translations[0]

        with patch.object(translation, "uninstall") as uninstall:
            await self.client.delete(f"{API_PREFIX}/translations/KJV")

        uninstall.assert_called_once_with("KJV")
        self.assertTrue(opened.closed)
        self.assertEqual(self.session.translations, [])


class ConfigTest(ApiTestCase):
    async def test_reads_and_writes_settings(self):
        with TemporaryDirectory() as temp:
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": f"{temp}/config"}, clear=True):
                payload = await self.get_json("/config")
                self.assertEqual(payload["values"]["DEFAULT_TRANSLATION"], "")

                response = await self.client.put(
                    f"{API_PREFIX}/config",
                    json={"DEFAULT_TRANSLATION": "KJV", "THEME": "dark"},
                )
                written = await response.json()

        self.assertEqual(response.status, 200)
        self.assertEqual(written["values"]["DEFAULT_TRANSLATION"], "KJV")
        self.assertEqual(written["values"]["THEME"], "dark")

    async def test_reports_environment_overrides(self):
        with TemporaryDirectory() as temp:
            environment = {"BIBLEIT_CONFIG_FILE": f"{temp}/config", "BIBLEIT_LIVE_URL": "https://example.test"}

            with patch.dict("os.environ", environment, clear=True):
                payload = await self.get_json("/config")

        self.assertEqual(payload["environment"], ["LIVE_URL"])

    async def test_rejects_a_request_with_no_known_settings(self):
        response = await self.client.put(f"{API_PREFIX}/config", json={"NOPE": "1"})

        self.assertEqual(response.status, 400)


class RemoteConfigTest(ApiTestCase):
    local = False

    async def test_settings_are_refused_away_from_the_local_operator(self):
        read = await self.client.get(f"{API_PREFIX}/config")
        written = await self.client.put(f"{API_PREFIX}/config", json={"THEME": "dark"})

        self.assertEqual(read.status, 403)
        self.assertEqual(written.status, 403)


class OperatorSocketTest(ApiTestCase):
    async def test_sends_state_then_accepts_commands(self):
        async with self.client.ws_connect(f"{API_PREFIX}/operator") as ws:
            first = await ws.receive_json()

            self.assertEqual(first["type"], "state")
            self.assertEqual(first["state"]["ref"]["verse"], 1)

            await ws.send_json({"command": "next_verse"})
            update = await ws.receive_json()

            self.assertEqual(update["state"]["ref"]["verse"], 2)

    async def test_reports_a_failed_command(self):
        async with self.client.ws_connect(f"{API_PREFIX}/operator") as ws:
            await ws.receive_json()
            await ws.send_json({"command": "launch_rocket"})
            event = await ws.receive_json()

        self.assertEqual(event["type"], "error")
        self.assertIn("launch_rocket", event["message"])

    async def test_ignores_a_message_that_is_not_a_command(self):
        async with self.client.ws_connect(f"{API_PREFIX}/operator") as ws:
            await ws.receive_json()
            await ws.send_str("not json")
            await ws.send_json({"command": "next_verse"})
            update = await ws.receive_json()

        self.assertEqual(update["state"]["ref"]["verse"], 2)

    async def test_broadcasts_to_every_connected_operator(self):
        async with self.client.ws_connect(f"{API_PREFIX}/operator") as first:
            async with self.client.ws_connect(f"{API_PREFIX}/operator") as second:
                await first.receive_json()
                await second.receive_json()

                await first.send_json({"command": "next_verse"})

                self.assertEqual((await first.receive_json())["state"]["ref"]["verse"], 2)
                self.assertEqual((await second.receive_json())["state"]["ref"]["verse"], 2)


class ShutdownTest(ApiTestCase):
    async def test_shutdown_closes_the_operator_socket(self):
        ws = await self.client.ws_connect(f"{API_PREFIX}/operator")
        await ws.receive_json()

        await asyncio.wait_for(self.app.shutdown(), timeout=5)

        self.assertTrue(ws.closed or (await ws.receive()).type is WSMsgType.CLOSE)
        await ws.close()


class MultipleTranslationTest(ApiTestCase):
    async def test_verses_returns_a_column_per_translation(self):
        self.session.translations.append(FakeTranslation("NVIPT", "Nova Versão", PT_LINES))

        payload = await self.get_json("/verses?before=0&total=2")

        self.assertEqual([column["translation"] for column in payload["columns"]], ["KJV", "NVIPT"])
        self.assertEqual(payload["columns"][1]["rows"][0]["reference"], "Gênesis 1:1")


if __name__ == "__main__":
    unittest.main()
