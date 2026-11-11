"""Behavior tests for the first discovery milestone."""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import activate


class HomeTests(TestCase):
    def tearDown(self):
        """Keep the localized promotion-film request isolated from later tests."""

        activate("ro")
        super().tearDown()

    def test_home_explains_the_location_first_job(self):
        response = self.client.get(reverse("services:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aproape de casă. Aproape de oamenii potriviți.")
        self.assertContains(response, "Alege județul, apoi restrânge opțional")
        self.assertNotContains(response, 'class="journal-index home-index"')
        self.assertNotContains(response, 'class="process"')
        content = response.content.decode()
        self.assertLess(content.index('id="cautare"'), content.index('id="servicii"'))
        self.assertLess(content.index('id="servicii"'), content.index('id="cum-functioneaza"'))

    def test_home_includes_the_localized_promotion_film(self):
        romanian = self.client.get(reverse("services:home"))
        english = self.client.get("/en/")

        self.assertContains(romanian, "servicii-aproape-home-ro.mp4")
        self.assertContains(romanian, "servicii-aproape-home-ro.vtt")
        self.assertContains(romanian, "Redă cu sunet")
        self.assertNotContains(romanian, "<video autoplay")
        self.assertContains(romanian, "Vezi cum ajungi de la proiect la firma potrivită")
        self.assertContains(english, "servicii-aproape-home-en.mp4")
        self.assertContains(english, "servicii-aproape-home-en.vtt")
        self.assertContains(english, "Play with sound")
        self.assertContains(english, "See how to go from project to the right company")

    def test_search_filters_by_location_and_category(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Cluj", "locality": "54984", "category": "gradinarit"},
        )

        self.assertContains(response, "Verde Urban")
        self.assertNotContains(response, "Nord Construct")
        content = response.content.decode()
        self.assertLess(content.index('id="cautare"'), content.index('id="rezultate"'))
        self.assertLess(content.index('id="rezultate"'), content.index('id="servicii"'))

    def test_legacy_locality_name_links_still_resolve(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Cluj", "locality": "Cluj-Napoca", "category": "constructii"},
        )

        self.assertContains(response, "Nord Construct")
        self.assertContains(response, 'value="54984" selected')

    def test_search_shows_a_useful_empty_state(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Cluj", "locality": "55268", "category": ""},
        )

        self.assertContains(response, "Nu avem încă exemple demonstrative")

    def test_county_only_search_includes_every_demo_provider_in_the_county(self):
        response = self.client.get(reverse("services:home"), {"county": "Cluj"})

        self.assertContains(response, "Nord Construct")
        self.assertContains(response, "Atelier Lemn Bun")
        self.assertContains(response, "Verde Urban")
        self.assertContains(response, "Toate localitățile din județ")
        self.assertNotContains(response, "Alege localitatea.")

    def test_locality_must_belong_to_the_selected_county(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Cluj", "locality": "40205", "category": ""},
        )

        self.assertContains(response, "Alege o localitate din județul selectat")

    def test_localities_endpoint_returns_all_cluj_localities(self):
        response = self.client.get(reverse("services:localities"), {"county": "Cluj"})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["localities"]), 434)
        self.assertIn(
            {"value": "54984", "label": "Cluj-Napoca"},
            payload["localities"],
        )
        self.assertIn(
            {"value": "55927", "label": "Băișoara"},
            payload["localities"],
        )

    def test_localities_endpoint_rejects_unknown_county_with_empty_list(self):
        response = self.client.get(reverse("services:localities"), {"county": "Necunoscut"})

        self.assertEqual(response.json(), {"localities": []})

    def test_home_links_to_the_live_professional_workflow(self):
        response = self.client.get(reverse("services:home"))

        self.assertContains(response, reverse("services:professionals"))
        self.assertContains(response, reverse("services:company_registration"))
        self.assertContains(response, reverse("services:subscription_plan"))
        self.assertContains(response, reverse("services:provider_login"))
        self.assertContains(response, 'class="professional-route', count=2)
        self.assertContains(response, "Resurse pentru profesioniști")
        self.assertNotContains(response, "mailto:salut@serviciiaproape.example")
        self.assertNotContains(response, "intră în următoarea etapă")

    def test_home_footer_links_to_legal_information(self):
        response = self.client.get(reverse("services:home"))

        self.assertContains(response, reverse("services:privacy"))
        self.assertContains(response, reverse("services:terms"))
        self.assertContains(response, settings.LEGAL_OPERATOR_NAME)
        self.assertNotContains(response, "cookie-consent")


class ProfessionalsEntryTests(TestCase):
    def test_professionals_entry_explains_the_controlled_claim_path(self):
        response = self.client.get(reverse("services:professionals"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alege cum vrei să începi")
        self.assertContains(response, "Caută firma în catalog")
        self.assertContains(response, "Nu este necesar un link de confirmare")
        self.assertContains(response, "intri direct cu e-mailul și parola alese")
        self.assertContains(response, "verificarea administrativă")
        self.assertContains(response, "nu publică automat profilul")
        self.assertContains(response, 'class="professionals-choice', count=2)
        self.assertContains(response, "Resurse pentru profesioniști")
        self.assertContains(
            response,
            f'class="professionals-choice professionals-primary" href="{reverse("services:home")}#cautare"',
        )
        self.assertContains(
            response,
            f'class="professionals-choice professionals-secondary" href="{reverse("services:company_registration")}"',
        )
        self.assertContains(response, reverse("services:subscription_plan"))
        self.assertContains(response, reverse("services:provider_login"))

    def test_login_links_people_without_access_to_claim_instructions(self):
        response = self.client.get(reverse("services:provider_login"))

        self.assertContains(response, reverse("services:professionals"))
        self.assertContains(response, "Vezi cum revendici firma")


class SubscriptionPlanTests(TestCase):
    """Keep the public price explicit without presenting an inactive checkout."""

    def test_plan_explains_price_benefits_and_publication_boundaries(self):
        response = self.client.get(reverse("services:subscription_plan"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["monthly_price_ron"], 49)
        self.assertEqual(response.context["managed_site_monthly_price_ron"], 299)
        self.assertContains(response, "49")
        self.assertContains(response, "lei")
        self.assertContains(response, "Opțiunile disponibile")
        self.assertContains(response, "Gratuit")
        self.assertContains(response, "Esențial")
        self.assertContains(response, "Partener")
        self.assertContains(response, "Site de prezentare personalizat, cu până la 5 pagini")
        self.assertContains(response, "Două solicitări de actualizare")
        self.assertContains(response, "se cotează separat")
        self.assertContains(response, reverse("services:managed_site_inquiry"))
        self.assertNotContains(response, "mailto:")
        self.assertContains(response, "Fără descriere, date de contact, portofoliu sau solicitări")
        self.assertContains(response, "Solicitări structurate de la clienți")
        self.assertContains(response, "până la 8 fotografii")
        self.assertNotContains(response, "Plata online nu este încă activă")
        self.assertNotContains(response, "Ce nu cumpără abonamentul")
        self.assertContains(response, reverse("services:professionals"))
        self.assertContains(response, reverse("services:home") + "#cautare")
        self.assertNotContains(response, "checkout")
        self.assertNotContains(response, "method=\"post\"")
