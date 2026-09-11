from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

import bibleit
from bibleit.config import save_config
from bibleit import live
from bibleit.web import assets
from bibleit.live import (
    HUB_KEY,
    add_live_routes,
    TITLE_KEY,
    TOKEN_KEY,
    clean_verse_text,
    create_app,
    current,
    handle_publisher_message,
    icon,
    parse_verse_line,
    request_is_authorized,
    viewer_html,
)


class RelayDependencyTest(unittest.TestCase):
    """The relay runs in a container with aiohttp and no native library.

    `python -m bibleit.live` must therefore stay clear of the translation
    layer, which loads `libbibleit` at import time and pulls in `requests`.
    """

    FORBIDDEN = ("bibleit.translation", "bibleit._ffi", "bibleit.reader", "requests", "textual")

    def test_the_relay_imports_without_the_reading_layer(self):
        program = "import sys, bibleit.live; print(' '.join(sorted(set(sys.modules) & set(FORBIDDEN)))) "
        program = f"FORBIDDEN = {self.FORBIDDEN!r}\n{program}"
        root = Path(bibleit.__file__).resolve().parent.parent

        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            env=os.environ | {"PYTHONPATH": str(root)},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class ShutdownTest(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_closes_open_sockets(self):
        """aiohttp waits for handlers to return, and a socket handler only
        returns when its socket closes. Without help, Ctrl+C hangs for as long
        as a viewer is connected."""
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": ""}):
            app = create_app("test live")

        server = TestServer(app)
        await server.start_server()

        async with TestClient(server) as client:
            viewer = await client.ws_connect("/ws")
            monitor = await client.ws_connect("/ws?role=monitor")
            publisher = await client.ws_connect("/ws?role=publisher")

            self.assertEqual(len(app[HUB_KEY].sockets()), 3)

            await asyncio.wait_for(server.close(), timeout=5)

            for ws in (viewer, monitor, publisher):
                await ws.close()


class ViewerAssetTest(unittest.IsolatedAsyncioTestCase):
    async def test_serves_the_stylesheet_and_the_script(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": ""}):
            app = create_app("test live")

        async with TestClient(TestServer(app)) as client:
            for path, content_type in (("/viewer.css", "text/css"), ("/viewer.js", "application/javascript")):
                response = await client.get(path)

                self.assertEqual(response.status, 200)
                self.assertEqual(response.content_type, content_type)
                self.assertGreater(len(await response.text()), 0)

    async def test_refuses_an_unknown_asset(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": ""}):
            app = create_app("test live")

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/viewer.map")

            self.assertEqual(response.status, 404)


class LiveVerseTest(unittest.TestCase):
    def test_parse_verse_line(self):
        verse = parse_verse_line("KJV", "Genesis 1:1 In the beginning God created the heaven and the earth.")

        self.assertEqual(verse.translation, "KJV")
        self.assertEqual(verse.reference, "Genesis 1:1")
        self.assertEqual(verse.text, "In the beginning God created the heaven and the earth.")

    def test_parse_multi_word_book(self):
        verse = parse_verse_line("KJV", "Song of Solomon 2:1 I am the rose of Sharon.")

        self.assertEqual(verse.book, "Song of Solomon")
        self.assertEqual(verse.chapter, 2)
        self.assertEqual(verse.verse, 1)

    def test_clean_verse_text_removes_markup_and_strongs(self):
        text = clean_verse_text("Let <b>there</b> be light <S>216</S><br>and there was light.")

        self.assertEqual(text, "Let there be light and there was light.")

    def test_create_app_has_live_hub(self):
        app = create_app("test live")

        self.assertEqual(app[TITLE_KEY], "test live")
        self.assertIsNone(app[HUB_KEY].current)
        self.assertEqual(app[HUB_KEY].client_count(), 0)

    def test_live_routes_mount_onto_an_existing_application(self):
        async def operator(request):
            return web.Response(text="operator")

        app = web.Application()
        app.router.add_get("/operator", operator)

        add_live_routes(app, title="composed")

        paths = {resource.canonical for resource in app.router.resources()}

        self.assertEqual(app[TITLE_KEY], "composed")
        self.assertIn("/operator", paths)
        self.assertIn("/ws", paths)
        self.assertIn("/api/publish", paths)

    def test_viewer_page_escapes_the_title_and_links_its_assets(self):
        rendered = viewer_html("bibleit <live>")

        self.assertIn("<title>bibleit &lt;live&gt;</title>", rendered)
        self.assertIn('href="/viewer.css"', rendered)
        self.assertIn('src="/viewer.js"', rendered)
        self.assertIn('href="/bibleit-icon.png"', rendered)

    def test_viewer_page_keeps_its_markup_out_of_the_assets(self):
        """The page carries structure only; styling and behaviour are served
        separately, so neither can drift back inline."""
        rendered = viewer_html("bibleit live")

        self.assertIn('id="splash"', rendered)
        self.assertIn('id="verses"', rendered)
        self.assertNotIn("<style", rendered)
        self.assertNotIn("addEventListener", rendered)

    def test_viewer_page_is_not_the_textual_web_page(self):
        rendered = viewer_html("bibleit live")

        self.assertNotIn('id="textual"', rendered)
        self.assertNotIn("/textual/", rendered)
        self.assertNotIn("textualEnabled", rendered)

    def test_viewer_behaviour_lives_in_the_script(self):
        script = assets.static_text("viewer.js")

        self.assertIn("bibleit-selected-translations", script)
        self.assertIn('navigator.wakeLock.request("screen")', script)
        self.assertIn("visibilitychange", script)

    def test_icon_response(self):
        response = asyncio.run(icon(make_mocked_request("GET", "/bibleit-icon.png")))

        self.assertEqual(response.content_type, "image/png")
        self.assertGreater(len(response.body), 0)

    def test_control_requests_are_open_without_token(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                app = create_app("test live")

        request = make_mocked_request("POST", "/api/publish", app=app)

        self.assertTrue(request_is_authorized(request))

    def test_current_response_includes_client_count(self):
        app = create_app("test live")
        request = make_mocked_request("GET", "/api/current", app=app)

        import asyncio

        response = asyncio.run(current(request))

        self.assertIn('"clients": 0', response.text)

    def test_main_arguments_take_precedence_over_environment(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "BIBLEIT_LIVE_HOST": "127.0.0.2",
                    "BIBLEIT_LIVE_PORT": "9002",
                },
                clear=True,
            ),
            patch.object(live.web, "run_app") as run_app,
        ):
            live.main(host="127.0.0.1", port="9001")

        self.assertEqual(run_app.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(run_app.call_args.kwargs["port"], 9001)

    def test_control_requests_require_matching_bearer_token(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": "secret"}, clear=True):
            app = create_app("test live")

        request = make_mocked_request(
            "POST",
            "/api/publish",
            headers={"Authorization": "Bearer secret"},
            app=app,
        )

        self.assertEqual(app[TOKEN_KEY], "secret")
        self.assertTrue(request_is_authorized(request))

    def test_control_requests_use_config_token(self):
        with TemporaryDirectory() as temp:
            path = f"{temp}/config"
            with patch.dict("os.environ", {"BIBLEIT_CONFIG_FILE": path}, clear=True):
                save_config({"LIVE_TOKEN": "secret"})
                app = create_app("test live")

        request = make_mocked_request(
            "POST",
            "/api/publish",
            headers={"Authorization": "Bearer secret"},
            app=app,
        )

        self.assertEqual(app[TOKEN_KEY], "secret")
        self.assertTrue(request_is_authorized(request))

    def test_control_requests_reject_missing_token(self):
        with patch.dict("os.environ", {"BIBLEIT_LIVE_TOKEN": "secret"}, clear=True):
            app = create_app("test live")

        request = make_mocked_request("POST", "/api/publish", app=app)

        self.assertFalse(request_is_authorized(request))

    def test_live_hub_ignores_stale_sequence_for_same_publisher(self):
        async def run():
            hub = create_app("test live")[HUB_KEY]

            await hub.publish(
                {
                    "publisher_id": "presenter",
                    "sequence": 2,
                    "reference": "Genesis 1:2",
                }
            )
            await hub.publish(
                {
                    "publisher_id": "presenter",
                    "sequence": 1,
                    "reference": "Genesis 1:1",
                }
            )

            self.assertEqual(hub.current["reference"], "Genesis 1:2")

        import asyncio

        asyncio.run(run())

    def test_live_hub_accepts_new_publisher_sequence(self):
        async def run():
            hub = create_app("test live")[HUB_KEY]

            await hub.publish(
                {
                    "publisher_id": "first",
                    "sequence": 10,
                    "reference": "Genesis 1:10",
                }
            )
            await hub.publish(
                {
                    "publisher_id": "second",
                    "sequence": 1,
                    "reference": "Genesis 1:1",
                }
            )

            self.assertEqual(hub.current["reference"], "Genesis 1:1")

        import asyncio

        asyncio.run(run())

    def test_publisher_websocket_message_updates_current_verse(self):
        async def run():
            hub = create_app("test live")[HUB_KEY]
            message = SimpleNamespace(
                type=web.WSMsgType.TEXT,
                data=json.dumps(
                    {
                        "type": "publish",
                        "payload": {
                            "publisher_id": "presenter",
                            "sequence": 1,
                            "reference": "Genesis 1:3",
                        },
                    }
                ),
            )

            await handle_publisher_message(hub, message)

            self.assertEqual(hub.current["reference"], "Genesis 1:3")

        import asyncio

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
