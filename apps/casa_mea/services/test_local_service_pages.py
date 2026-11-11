"""Public-contract tests for canonical locality and service landing pages."""

from django.test import TestCase
from django.urls import reverse
from django.utils.translation import activate


class LocalServicePageTests(TestCase):
    """Keep SEO entry points collision-safe and bound to ordinary catalogue gates."""

    def tearDown(self):
        """Avoid leaking the English locale into another test module."""

        activate("ro")
        super().tearDown()

    def test_home_categories_link_to_canonical_local_service_pages(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "/servicii/electricieni/iasi/iasi-95079/",
        )
        self.assertNotContains(
            response,
            "?county=Ia%C8%99i&amp;locality=95079&amp;category=electricieni#rezultate",
        )

    def test_local_page_resolves_siruta_scope_and_is_noindex_in_demo_mode(self):
        url = reverse(
            "services:local_service",
            kwargs={
                "category": "instalatii",
                "county_slug": "iasi",
                "locality_slug": "iasi",
                "siruta_code": "95079",
            },
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Instalații")
        self.assertContains(response, "Firme pentru Instalații în Iași")
        self.assertContains(response, "Instal Pro Iași", html=False)
        self.assertEqual(response.context["category_slug"], "instalatii")
        self.assertEqual(
            response.context["art_photo"],
            "services/category-photos/instalatii.webp",
        )
        self.assertContains(response, "category-photos/instalatii.webp")
        self.assertContains(response, "Imagine ilustrativă")
        self.assertContains(response, '<meta name="robots" content="noindex, follow">')
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, follow")
        self.assertContains(
            response,
            f'<link rel="canonical" href="http://testserver{url}">',
        )

    def test_noncanonical_place_slugs_redirect_permanently(self):
        response = self.client.get(
            "/servicii/electricieni/neamt/piatra-rea-120735/",
            {"page": "2", "ignored": "value"},
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers["Location"],
            "/servicii/electricieni/neamt/piatra-neamt-120735/?page=2",
        )

    def test_unknown_category_or_cross_county_siruta_fails_closed(self):
        unknown_category = self.client.get(
            "/servicii/necunoscut/iasi/iasi-95079/"
        )
        cross_county_code = self.client.get(
            "/servicii/electricieni/neamt/piatra-neamt-95079/"
        )

        self.assertEqual(unknown_category.status_code, 404)
        self.assertEqual(cross_county_code.status_code, 404)

    def test_english_page_keeps_path_scope_and_translates_customer_copy(self):
        response = self.client.get(
            "/en/servicii/electricieni/neamt/piatra-neamt-120735/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, "Electrical work in Piatra-Neamț")
        self.assertContains(response, "Other services in Piatra-Neamț")
        self.assertContains(
            response,
            'hreflang="ro" href="http://testserver/servicii/electricieni/neamt/piatra-neamt-120735/"',
        )
