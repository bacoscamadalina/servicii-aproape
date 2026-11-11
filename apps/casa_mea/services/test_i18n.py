"""Integration tests for the Romanian and English public URL spaces."""

from django.test import TestCase
from django.urls import reverse
from django.utils.translation import activate, override


class PublicLanguageTests(TestCase):
    """Keep one continuous language across every non-admin workflow."""

    def tearDown(self):
        """Do not leak LocaleMiddleware's last activated language to other tests."""
        activate("ro")
        super().tearDown()

    def test_home_has_stable_romanian_and_shareable_english_urls(self):
        romanian = self.client.get("/")
        english = self.client.get("/en/")

        self.assertEqual(romanian.status_code, 200)
        self.assertContains(romanian, '<html lang="ro">')
        self.assertContains(romanian, "Aproape de casă. Aproape de oamenii potriviți.")
        self.assertEqual(english.status_code, 200)
        self.assertContains(english, '<html lang="en">')
        self.assertContains(english, "Close to home. Close to the right people.")
        self.assertContains(english, "Start a local search")
        self.assertNotContains(english, "Începe căutarea locală")

    def test_language_links_preserve_search_state_and_publish_hreflang(self):
        response = self.client.get(
            "/en/",
            {
                "county": "Iași",
                "locality": "95079",
                "category": "constructii",
                "page": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        romanian_url = (
            "/?county=Ia%C8%99i&amp;locality=95079&amp;category=constructii&amp;page=2"
        )
        english_url = (
            "/en/?county=Ia%C8%99i&amp;locality=95079&amp;category=constructii&amp;page=2"
        )
        self.assertContains(response, f'href="{romanian_url}" lang="ro"')
        self.assertContains(
            response,
            f'href="{english_url}" lang="en" hreflang="en" aria-current="page"',
        )
        self.assertContains(response, 'rel="alternate" hreflang="ro"')
        self.assertContains(response, 'rel="alternate" hreflang="en"')
        self.assertContains(response, 'rel="alternate" hreflang="x-default"')

    def test_optional_locality_and_javascript_copy_follow_url_language(self):
        response = self.client.get("/en/", {"county": "Iași"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All localities in the county")
        self.assertContains(response, "County Iași")
        self.assertContains(response, 'data-locality-loading="Loading localities…"')
        self.assertContains(
            response, 'data-locality-all="All localities in the county"'
        )

    def test_provider_entry_and_account_pages_do_not_fall_back_to_romanian(self):
        professionals = self.client.get("/en/pentru-profesionisti/")
        subscription = self.client.get("/en/abonament/")
        login = self.client.get("/en/cont/autentificare/")

        self.assertEqual(professionals.status_code, 200)
        self.assertContains(professionals, '<html lang="en">')
        self.assertContains(professionals, "For professionals")
        self.assertEqual(subscription.status_code, 200)
        self.assertContains(subscription, "Professional subscription")
        self.assertContains(subscription, "Available plans")
        self.assertContains(subscription, "Essential plan")
        self.assertNotContains(subscription, "Preț de lansare")
        self.assertEqual(login.status_code, 200)
        self.assertContains(login, '<html lang="en">')
        self.assertContains(login, "Provider sign-in")
        self.assertContains(login, '<meta name="robots" content="noindex">')
        self.assertNotContains(login, "Autentificare furnizor")

    def test_reverse_keeps_every_simple_service_route_in_active_language(self):
        route_names = (
            "home",
            "professionals",
            "subscription_plan",
            "privacy",
            "terms",
            "provider_login",
            "provider_password_reset",
            "provider_password_reset_done",
            "provider_password_reset_complete",
            "provider_password_change",
            "customer_password_change",
            "provider_dashboard",
            "provider_logout",
            "localities",
        )

        with override("ro"):
            self.assertTrue(
                all(not reverse(f"services:{name}").startswith("/ro/") for name in route_names)
            )
        with override("en"):
            self.assertTrue(
                all(reverse(f"services:{name}").startswith("/en/") for name in route_names)
            )

    def test_locality_api_exists_in_both_language_spaces(self):
        romanian = self.client.get("/api/localitati/", {"county": "Iași"})
        english = self.client.get("/en/api/localitati/", {"county": "Iași"})

        self.assertEqual(romanian.status_code, 200)
        self.assertEqual(english.status_code, 200)
        self.assertEqual(romanian.json(), english.json())
        self.assertTrue(english.json()["localities"])

    def test_legal_pages_are_complete_in_both_language_spaces(self):
        romanian = self.client.get("/confidentialitate/")
        english = self.client.get("/en/confidentialitate/")
        terms = self.client.get("/en/termeni/")

        self.assertEqual(romanian.status_code, 200)
        self.assertContains(romanian, "Confidențialitate și date personale")
        self.assertContains(romanian, "Nu stocăm adresa IP")
        self.assertContains(romanian, "cookie-uri de publicitate")
        self.assertContains(romanian, "documentele lor justificative sunt șterse")
        self.assertContains(romanian, "după 30 de zile")
        self.assertContains(romanian, "anonimizate după 1095 de zile")
        self.assertContains(romanian, "tuturor firmelor eligibile")
        self.assertContains(romanian, "fereastra de 90 de zile")
        self.assertNotContains(romanian, "maximum trei firme")
        self.assertEqual(english.status_code, 200)
        self.assertContains(english, "Privacy and personal data")
        self.assertContains(english, "Strictly necessary cookies")
        self.assertContains(english, "We do not store the IP address")
        self.assertContains(english, "cross-site tracking cookies")
        self.assertContains(english, "supporting documents deleted")
        self.assertContains(english, "after 30 days")
        self.assertContains(english, "anonymised 1095 days after")
        self.assertContains(english, "every eligible provider")
        self.assertContains(english, "90-day window")
        self.assertNotContains(english, "up to three providers")
        self.assertNotContains(english, "Cine operează platforma")
        self.assertEqual(terms.status_code, 200)
        self.assertContains(terms, "An informational directory, not an endorsement")
        self.assertContains(terms, "every eligible provider")

    def test_admin_remains_unprefixed_and_romanian(self):
        admin = self.client.get("/admin/login/", HTTP_ACCEPT_LANGUAGE="en")

        self.assertEqual(admin.status_code, 200)
        self.assertContains(admin, '<html lang="ro"')
        self.assertEqual(self.client.get("/en/admin/").status_code, 404)
