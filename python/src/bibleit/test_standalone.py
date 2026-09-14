from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from bibleit import cli
from bibleit.integrations.aiohttp import API_PREFIX
from bibleit.operator import OperatorService, OperatorSession
from bibleit.standalone import addresses, create_operator_app
from bibleit.test_operator_core import FakeCatalog


class StandaloneTests(AioHTTPTestCase):
    async def get_application(self):
        self.environment = patch.dict(
            os.environ,
            {"BIBLEIT_DEFAULT_TRANSLATION": "", "BIBLEIT_LIVE_URL": ""},
            clear=False,
        )
        self.environment.start()
        self.catalog = FakeCatalog()
        self.service = OperatorService(session=OperatorSession(), catalog=self.catalog)
        return create_operator_app(title="Test Bibleit", host="0.0.0.0", service=self.service)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.environment.stop()

    async def test_serves_cache_safe_operator_assets_and_clear_first_run(self):
        page = await self.client.get("/operator")
        css = await self.client.get("/operator/static/operator.css")
        script = await self.client.get("/operator/static/operator.js")

        self.assertIn("Open your first translation", await page.text())
        self.assertEqual(page.headers["Cache-Control"], "no-cache")
        self.assertEqual(css.headers["Cache-Control"], "no-cache")
        self.assertIn("/api/v1/bibleit", await script.text())

    async def test_dynamic_qr_uses_the_reachable_audience_address(self):
        with patch("bibleit.standalone.lan_address", return_value="192.168.1.50"):
            found = addresses("0.0.0.0", self.server.port)
            qr = await self.client.get(f"{API_PREFIX}/qr.svg")

        self.assertEqual(found["audience"][-1], f"http://192.168.1.50:{self.server.port}/")
        self.assertEqual(qr.status, 200)
        self.assertEqual(qr.content_type, "image/svg+xml")
        self.assertIn(b"<svg", await qr.read())

    async def test_operator_and_audience_share_one_publish_session(self):
        await self.client.post(f"{API_PREFIX}/translations/KJV")
        live = await self.client.post(
            f"{API_PREFIX}/commands",
            json={"command": "set_live", "params": {"live": True}},
        )
        current = await self.client.get("/api/current")

        self.assertTrue((await live.json())["live"])
        self.assertEqual((await current.json())["verse"]["reference"], "Genesis 1:1")

    async def test_loopback_policy_protects_operator_but_not_audience(self):
        with patch("bibleit.standalone.is_loopback", return_value=False):
            operator = await self.client.get("/operator")
            api = await self.client.get(f"{API_PREFIX}/state")
            audience = await self.client.get("/")

        self.assertEqual(operator.status, 403)
        self.assertEqual(api.status, 403)
        self.assertEqual(audience.status, 200)


class StandaloneCliTests(unittest.TestCase):
    def test_web_accepts_host_and_port(self):
        with patch("bibleit.standalone.main") as standalone_main:
            result = cli.main(["--web", "127.0.0.1", "9010"])

        self.assertEqual(result, 0)
        standalone_main.assert_called_once_with(host="127.0.0.1", port="9010")


if __name__ == "__main__":
    unittest.main()
