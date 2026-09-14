from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from bibleit.operator import OperatorService, OperatorSession
from bibleit.standalone import create_operator_app
from bibleit.test_operator_core import FakeCatalog

try:
    from playwright.async_api import async_playwright, expect
except ModuleNotFoundError:
    async_playwright = None
    expect = None


@unittest.skipIf(async_playwright is None, "playwright is not installed")
class StandaloneBrowserTests(AioHTTPTestCase):
    async def get_application(self):
        self.environment = patch.dict(
            os.environ,
            {"BIBLEIT_DEFAULT_TRANSLATION": "", "BIBLEIT_LIVE_URL": ""},
            clear=False,
        )
        self.environment.start()
        self.catalog = FakeCatalog()
        self.service = OperatorService(session=OperatorSession(), catalog=self.catalog)
        self.playwright = None
        self.browser = None
        return create_operator_app(title="Test Bibleit", service=self.service)

    async def asyncTearDown(self):
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()
        await super().asyncTearDown()
        self.environment.stop()

    async def page(self):
        if self.browser is None:
            self.playwright = await async_playwright().start()
            try:
                self.browser = await self.playwright.chromium.launch()
            except Exception as error:
                raise unittest.SkipTest(f"Chromium is unavailable: {error}") from error
        page = await self.browser.new_page()
        await page.goto(f"http://127.0.0.1:{self.server.port}/operator")
        return page

    async def test_first_run_explains_how_to_begin(self):
        page = await self.page()
        await expect(page.get_by_text("Open your first translation")).to_be_visible()

    async def test_verse_navigation_runs_through_the_shared_api(self):
        await self.service.open_translation("KJV")
        page = await self.page()
        await expect(page.locator(".row")).to_have_count(5)
        await page.get_by_label("Next verse").click()
        await expect(page.locator("#now")).to_have_text("Genesis 1:2")

    async def test_share_panel_renders_a_dynamic_qr(self):
        page = await self.page()
        await page.get_by_role("button", name="Share").click()
        await expect(page.locator(".qr")).to_be_visible()
        self.assertTrue(await page.locator(".qr").evaluate("image => image.naturalWidth > 0"))


if __name__ == "__main__":
    unittest.main()
