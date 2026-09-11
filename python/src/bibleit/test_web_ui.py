from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from bibleit import translation
from bibleit.test_operator import PT_LINES, FakeTranslation
from bibleit.text_find import clear_find_index_cache
from bibleit.web.api import SESSION_KEY
from bibleit.web.server import create_operator_app

try:
    from playwright.async_api import async_playwright, expect
except ModuleNotFoundError:
    async_playwright = None
    expect = None

UI_LINES = [
    "Genesis 1:1 In the beginning <S>7225</S> God created the heaven and the earth.",
    "Genesis 1:2 And the earth was without form, and void.",
    "Genesis 1:3 And God said, Let there be light: and there was light.",
    "Genesis 2:1 Thus the heavens and the earth were finished.",
    "Matthew 1:1 The book of the generation of Jesus Christ.",
]

STRONGS = {
    "H7225": translation.StrongEntry(
        code="H7225",
        lemma="reshith",
        transliteration="re'shiyth",
        definition="the first, in place, time, order or rank",
    )
}

# The operator would otherwise pick up the developer's own configuration: open a
# real translation, publish to a real relay, or let the settings panel write to
# the real ~/.bibleit/config.
ISOLATED_ENVIRONMENT = {
    "BIBLEIT_DEFAULT_TRANSLATION": "",
    "BIBLEIT_LIVE_URL": "",
    "BIBLEIT_LIVE_TOKEN": "",
}


@unittest.skipIf(async_playwright is None, "playwright is not installed")
class OperatorUiTestCase(AioHTTPTestCase):
    async def get_application(self):
        self.config = TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            ISOLATED_ENVIRONMENT | {"BIBLEIT_CONFIG_FILE": f"{self.config.name}/config"},
        )
        self.environment.start()
        self.page_errors: list[str] = []
        self._playwright = None
        self._browser = None

        # The text search cache is keyed by slug, so a fake from another test
        # would otherwise answer for this one.
        clear_find_index_cache()

        app = create_operator_app(title="bibleit live")
        session = app[SESSION_KEY]
        opened = FakeTranslation(lines=UI_LINES)
        opened.strongs = STRONGS
        session.translations.append(opened)
        session.active_slug = "KJV"
        self.session = session
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.environment.stop()
        self.config.cleanup()
        self.assertEqual(self.page_errors, [])

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server.port}{path}"

    async def browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self.addAsyncCleanup(self._playwright.stop)

            try:
                self._browser = await self._playwright.chromium.launch()
            except Exception as error:
                raise unittest.SkipTest(f"chromium is not installed: run `make test-ui` ({error})")

            self.addAsyncCleanup(self._browser.close)

        return self._browser

    async def open_page(self, **options):
        browser = await self.browser()
        page = await browser.new_page(**options)
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        await page.goto(self.url("/operator"))
        await page.wait_for_selector(".row")
        return page


class ReadingTest(OperatorUiTestCase):
    async def test_opens_on_the_current_verse(self):
        page = await self.open_page()

        await expect(page.locator("#now")).to_have_text("Genesis 1:1")
        await expect(page.locator(".column-slug")).to_have_text("KJV")
        await expect(page.locator(".row")).to_have_count(len(UI_LINES))
        await expect(page.locator('.row[aria-current="true"]')).to_contain_text("Genesis 1:1")

    async def test_clicking_a_verse_makes_it_current(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Genesis 1:3").click()

        await expect(page.locator("#now")).to_have_text("Genesis 1:3")
        await expect(page.locator('.row[aria-current="true"]')).to_contain_text("Genesis 1:3")

    async def test_arrow_keys_step_through_verses(self):
        page = await self.open_page()

        await page.locator("body").press("ArrowDown")
        await expect(page.locator("#now")).to_have_text("Genesis 1:2")

        await page.locator("body").press("ArrowDown")
        await expect(page.locator("#now")).to_have_text("Genesis 1:3")

        await page.locator("body").press("ArrowUp")
        await expect(page.locator("#now")).to_have_text("Genesis 1:2")

    async def test_stepper_buttons_move_by_verse_and_chapter(self):
        page = await self.open_page()

        await page.get_by_label("Next verse").click()
        await expect(page.locator("#now")).to_have_text("Genesis 1:2")

        await page.get_by_label("Next chapter").click()
        await expect(page.locator("#now")).to_have_text("Genesis 2:1")

    async def test_verse_markup_is_rendered_not_escaped(self):
        page = await self.open_page()

        strong = page.locator('.row[aria-current="true"] .strong')

        await expect(strong).to_have_attribute("data-code", "H7225")
        await expect(strong).to_have_text("7225")


class GoToTest(OperatorUiTestCase):
    async def test_typing_a_reference_navigates(self):
        page = await self.open_page()

        await page.locator("#goto-input").fill("gen 1.3")
        await page.locator("#goto-input").press("Enter")

        await expect(page.locator("#now")).to_have_text("Genesis 1:3")

    async def test_offers_book_names_while_typing(self):
        page = await self.open_page()

        await page.locator("#goto-input").fill("gen")

        await expect(page.locator("#candidates")).to_be_visible()
        await expect(page.locator("#candidates button").first).to_have_text("Genesis")

    async def test_choosing_a_book_fills_the_box(self):
        page = await self.open_page()

        await page.locator("#goto-input").fill("mat")
        await page.locator("#candidates button").first.click()

        await expect(page.locator("#goto-input")).to_have_value("Matthew ")

    async def test_reports_a_reference_that_does_not_exist(self):
        page = await self.open_page()

        await page.locator("#goto-input").fill("gen 9:9")
        await page.locator("#goto-input").press("Enter")

        await expect(page.locator(".toast")).to_contain_text("not found")
        await expect(page.locator("#now")).to_have_text("Genesis 1:1")


class LiveTest(OperatorUiTestCase):
    async def test_going_live_reports_viewers(self):
        page = await self.open_page()

        await expect(page.locator("#viewers")).to_be_hidden()

        await page.get_by_role("button", name="Go live").click()

        await expect(page.locator("#live-toggle")).to_have_text("Live")
        await expect(page.locator("#viewers")).to_be_visible()
        await expect(page.locator("#viewers")).to_have_text("0 viewers")
        self.assertTrue(self.session.state.live)

    async def test_the_audience_view_follows_the_operator(self):
        page = await self.open_page()
        audience = await (await self.browser()).new_page()
        await audience.goto(self.url("/"))

        await page.get_by_role("button", name="Go live").click()
        await page.get_by_role("button", name="Genesis 1:3").click()

        await expect(audience.locator(".verse")).to_contain_text("Let there be light")
        await expect(audience.locator(".reference")).to_have_text("Genesis 1:3")
        await expect(page.locator("#viewers")).to_have_text("1 viewer")

    async def test_two_operators_stay_in_step(self):
        first = await self.open_page()
        second = await self.open_page()

        await first.locator("body").press("ArrowDown")

        await expect(second.locator("#now")).to_have_text("Genesis 1:2")
        await expect(second.locator('.row[aria-current="true"]')).to_contain_text("Genesis 1:2")


class PanelTest(OperatorUiTestCase):
    async def test_books_panel_navigates_by_chapter(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Books", exact=True).click()
        await page.locator("#books-grid button", has_text="Genesis").click()
        await page.locator("#chapters-grid button", has_text="2").click()

        await expect(page.locator("#now")).to_have_text("Genesis 2:1")
        await expect(page.locator("#panel")).to_be_hidden()

    async def test_find_navigates_to_a_result(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Find", exact=True).click()
        await page.locator("#find-input").fill("light")

        await expect(page.locator("#find-results button").first).to_contain_text("Genesis 1:3")

        await page.locator("#find-results button").first.click()

        await expect(page.locator("#now")).to_have_text("Genesis 1:3")

    async def test_find_reports_nothing_found(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Find", exact=True).click()
        await page.locator("#find-input").fill("zebra")

        await expect(page.locator("#find-hint")).to_contain_text("Nothing")

    async def test_share_panel_offers_an_audience_address(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Share", exact=True).click()

        await expect(page.locator("#share-url")).to_contain_text("http://")
        await expect(page.locator("#share-state")).to_contain_text("Not live yet")

    async def test_settings_panel_loads_and_saves(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Settings", exact=True).click()
        await expect(page.locator("#settings-hint")).to_contain_text("Set in the environment")
        await expect(page.locator("#config-THEME")).to_have_value("")

        await page.locator("#config-THEME").fill("dark")
        await page.get_by_role("button", name="Save settings").click()

        await expect(page.locator(".toast")).to_contain_text("Settings saved")
        self.assertIn('THEME = "dark"', Path(f"{self.config.name}/config").read_text())

    async def test_shortcuts_panel_lists_the_keys(self):
        page = await self.open_page()

        await page.locator("body").press("?")

        await expect(page.locator("#panel-title")).to_have_text("Shortcuts")
        await expect(page.locator("#shortcuts dt").first).to_have_text("↑ ↓")

    async def test_escape_closes_a_panel(self):
        page = await self.open_page()

        await page.locator("body").press("b")
        await expect(page.locator("#panel")).to_be_visible()

        await page.locator("body").press("Escape")
        await expect(page.locator("#panel")).to_be_hidden()


class LibraryTest(OperatorUiTestCase):
    async def test_lists_open_translations_and_can_close_one(self):
        page = await self.open_page()

        await page.get_by_role("button", name="Library", exact=True).click()

        await expect(page.locator("#library-open .entry")).to_have_count(1)
        await expect(page.locator("#library-open .entry b")).to_have_text("KJV")

        await page.locator("#library-open .entry button").click()

        await expect(page.locator("#welcome")).to_be_visible()
        await expect(page.locator("#now")).to_have_text("No translation open")

    async def test_closing_a_column_removes_the_translation(self):
        page = await self.open_page()
        self.session.translations.append(FakeTranslation("NVIPT", "Nova Versão", PT_LINES))
        await self.session.notify_state()

        await expect(page.locator(".column")).to_have_count(2)

        await page.get_by_label("Close NVIPT").click()

        await expect(page.locator(".column")).to_have_count(1)


class StrongsTest(OperatorUiTestCase):
    async def test_a_strongs_code_opens_its_entry(self):
        page = await self.open_page()

        await expect(page.locator(".strong").first).to_be_hidden()

        await page.locator("body").press("h")
        await expect(page.locator(".strong").first).to_be_visible()

        await page.locator(".strong").first.click()

        await expect(page.locator("#strong-card h3")).to_contain_text("H7225")
        await expect(page.locator("#strong-card")).to_contain_text("the first, in place")

    async def test_clicking_a_code_does_not_move_the_verse(self):
        page = await self.open_page()

        await page.locator("body").press("h")
        await page.locator(".strong").first.click()

        await expect(page.locator("#now")).to_have_text("Genesis 1:1")


class ChromeTest(OperatorUiTestCase):
    async def test_theme_toggle_switches_and_persists(self):
        page = await self.open_page()

        await page.get_by_label("Toggle light or dark").click()
        await expect(page.locator("html")).to_have_attribute("data-theme", "dark")

        await page.reload()
        await page.wait_for_selector(".row")

        await expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    async def test_the_layout_fits_a_phone(self):
        page = await self.open_page(viewport={"width": 390, "height": 780})

        overflow = await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")

        self.assertLessEqual(overflow, 0)
        await expect(page.get_by_label("Next verse")).to_be_visible()

        await page.get_by_label("Next verse").click()
        await expect(page.locator("#now")).to_have_text("Genesis 1:2")

    async def test_the_operator_survives_losing_the_socket(self):
        page = await self.open_page()

        await page.evaluate("window.__sockets = performance.now()")
        await page.get_by_role("button", name="Genesis 1:2").click()
        await expect(page.locator("#now")).to_have_text("Genesis 1:2")


if __name__ == "__main__":
    unittest.main()
