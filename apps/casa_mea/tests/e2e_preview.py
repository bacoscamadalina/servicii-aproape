"""Browser journeys for the packaged, read-only ServiciiAproape preview."""

from pathlib import Path
import os
import re
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.environ.get("CASAMEA_E2E_BASE_URL", "http://127.0.0.1:18002").rstrip("/")
ARTIFACT_DIR = Path(os.environ.get("CASAMEA_E2E_ARTIFACT_DIR", "test-artifacts"))
VIEWPORTS = {
    "desktop": {"width": 1280, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


class PreviewBrowserJourneys(unittest.TestCase):
    """Exercise only stable visitor behavior exposed by the preview image."""

    @classmethod
    def setUpClass(cls):
        """Launch one browser while keeping every journey in an isolated context."""

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        """Release browser resources even when an individual journey fails."""

        cls.browser.close()
        cls.playwright.stop()

    def run_journey(self, name, viewport, journey):
        """Run one isolated journey and retain screenshot plus trace only on failure."""

        context = self.browser.new_context(viewport=viewport, locale="ro-RO")
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        browser_errors = []
        page.on(
            "console",
            lambda message: browser_errors.append(f"console: {message.text}")
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: browser_errors.append(f"page: {error}"))
        try:
            journey(page)
            self.assertEqual(browser_errors, [], "Browser errors were emitted")
        except Exception:
            page.screenshot(path=ARTIFACT_DIR / f"{name}.png", full_page=True)
            context.tracing.stop(path=ARTIFACT_DIR / f"{name}.zip")
            raise
        else:
            context.tracing.stop()
        finally:
            context.close()

    def assert_no_horizontal_overflow(self, page):
        """Protect the mobile and desktop layouts from page-level horizontal scroll."""

        dimensions = page.evaluate(
            "() => ({ width: document.documentElement.scrollWidth, viewport: window.innerWidth })"
        )
        self.assertLessEqual(dimensions["width"], dimensions["viewport"])

    def test_location_search_company_detail_and_language_switch(self):
        """Cover the complete locality-first discovery path at both supported sizes."""

        for viewport_name, viewport in VIEWPORTS.items():
            with self.subTest(viewport=viewport_name):

                def journey(page):
                    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
                    expect(page.locator("#hero-title")).to_contain_text(
                        "Găsește firme pentru proiectul casei tale"
                    )
                    category_y = page.locator("#id_category").bounding_box()["y"]

                    page.locator("#id_county").select_option("Iași")
                    expect(page.locator("#id_locality")).to_be_enabled()
                    expect(page.locator('#id_locality option[value=""]')).to_have_text(
                        "Toate localitățile din județ"
                    )
                    expect(page.locator('#id_locality option[value="95248"]')).to_have_count(1)
                    expect(page.locator("#location-status")).to_contain_text("localități disponibile")

                    if viewport_name == "desktop":
                        loaded_category_y = page.locator("#id_category").bounding_box()["y"]
                        self.assertAlmostEqual(category_y, loaded_category_y, delta=1)

                    page.get_by_role("button", name="Caută firme și servicii").click()
                    expect(page.locator("#rezultate h2")).to_have_text("Rezultatele căutării")
                    expect(page.locator(".registry-row").first).to_be_visible()
                    county_query = parse_qs(urlparse(page.url).query, keep_blank_values=True)
                    self.assertEqual(county_query["county"], ["Iași"])
                    self.assertEqual(county_query["locality"], [""])
                    self.assertEqual(county_query["category"], [""])
                    expect(page.locator(".registry-row .provider-location").first).to_contain_text(
                        "Sediu social"
                    )
                    self.assert_no_horizontal_overflow(page)

                    page.locator(".registry-detail-link").first.click()
                    expect(page.locator("#company-name")).to_be_visible()
                    page.locator(".detail-back").click()

                    page.locator("#id_locality").select_option("95248")
                    page.locator("#id_category").select_option("constructii")
                    page.get_by_role("button", name="Caută firme și servicii").click()

                    expect(page.locator("#rezultate h2")).to_have_text("Rezultatele căutării")
                    expect(page.locator(".registry-row").first).to_be_visible()
                    query = parse_qs(urlparse(page.url).query)
                    self.assertEqual(query["county"], ["Iași"])
                    self.assertEqual(query["locality"], ["95248"])
                    self.assertEqual(query["category"], ["constructii"])
                    self.assert_no_horizontal_overflow(page)

                    page.locator(".registry-detail-link").first.click()
                    expect(page.locator("#company-name")).to_be_visible()
                    expect(page.locator(".company-category-list")).to_contain_text("Construcții")
                    self.assert_no_horizontal_overflow(page)

                    page.locator(".detail-back").click()
                    expect(page.locator("#rezultate h2")).to_have_text("Rezultatele căutării")
                    page.locator('.language-switcher a[lang="en"]').click()
                    expect(page.locator("html")).to_have_attribute("lang", "en")
                    expect(page.locator("#rezultate h2")).to_have_text("Search results")
                    english_query = parse_qs(urlparse(page.url).query)
                    self.assertEqual(english_query, query)
                    self.assert_no_horizontal_overflow(page)

                self.run_journey(f"discovery-{viewport_name}", viewport, journey)

    def test_pagination_and_detail_return_preserve_page(self):
        """Keep page two and all search filters across company-detail navigation."""

        def journey(page):
            page.goto(
                f"{BASE_URL}/?county=Cluj&locality=54984&category=#rezultate",
                wait_until="domcontentloaded",
            )
            next_page = page.get_by_role("link", name="Pagina următoare")
            expect(next_page).to_be_visible()
            next_page.click()
            expect(page.locator(".pagination")).to_contain_text(re.compile(r"Pagina 2 din \d+"))

            page.locator(".registry-detail-link").first.click()
            expect(page.locator("#company-name")).to_be_visible()
            page.locator(".detail-back").click()

            query = parse_qs(urlparse(page.url).query, keep_blank_values=True)
            self.assertEqual(query["county"], ["Cluj"])
            self.assertEqual(query["locality"], ["54984"])
            self.assertEqual(query["category"], [""])
            self.assertEqual(query["page"], ["2"])
            expect(page.locator(".pagination")).to_contain_text(re.compile(r"Pagina 2 din \d+"))
            self.assert_no_horizontal_overflow(page)

        self.run_journey("pagination-desktop", VIEWPORTS["desktop"], journey)


if __name__ == "__main__":
    unittest.main(verbosity=2)
