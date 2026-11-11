"""End-to-end contracts for companies absent from the imported catalogue."""

from datetime import timedelta
import re
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from .models import BusinessIdentity, ProviderClaimRequest, ProviderRegistrationRequest
from .provider_registrations import (
    REVIEW_ACKNOWLEDGEMENT,
    convert_provider_registration_to_claim,
)
from .test_representation_evidence import representation_evidence_upload


@override_settings(
    DEBUG=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="ServiciiAproape <test@example.com>",
)
class ProviderRegistrationFlowTests(TestCase):
    """Prove intake, confirmation and reconciliation remain fail-closed."""

    def setUp(self):
        self.url = reverse("services:company_registration")
        self.payload = {
            "legal_name": "Firmă Nouă SRL",
            "cui": "RO 12345678",
            "registration_number": "j22/1234/2026",
            "requested_category": "electricieni",
            "registered_county": "Iași",
            "registered_office_siruta": "95079",
            "first_name": "Ana",
            "last_name": "Reprezentant",
            "username": "ana.reprezentant",
            "role": "administrator",
            "email": "ANA@EXAMPLE.COM",
            "password1": "Provider-pass-2026!",
            "password2": "Provider-pass-2026!",
            "evidence_type": "onrc_document",
            "representation_declaration": "on",
            "privacy_consent": "on",
            "website": "",
        }

    def tearDown(self):
        """Do not leak the language selected by the bilingual route test."""

        activate("ro")
        super().tearDown()

    def submit(self, **overrides):
        return self.client.post(
            self.url,
            {
                **self.payload,
                "evidence_document": representation_evidence_upload(),
                **overrides,
            },
        )

    def test_unlisted_company_enters_review_without_email_link(self):
        response = self.submit()

        self.assertContains(response, "Cererea a intrat în verificare")
        self.assertEqual(BusinessIdentity.objects.count(), 0)
        registration = ProviderRegistrationRequest.objects.get()
        self.assertEqual(registration.cui, "RO12345678")
        self.assertEqual(registration.registration_number, "J22/1234/2026")
        self.assertEqual(registration.requested_category, "electricieni")
        self.assertEqual(registration.email, "ana@example.com")
        self.assertEqual(registration.status, registration.Status.REVIEW_PENDING)
        self.assertIsNone(registration.email_verified_at)
        self.assertEqual(registration.account_username, "ana.reprezentant")
        self.assertTrue(check_password(self.payload["password1"], registration.password_hash))
        self.assertEqual(registration.representation_evidence.mime_type, "application/pdf")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(BusinessIdentity.objects.count(), 0)
        self.assertEqual(ProviderClaimRequest.objects.count(), 0)

    def test_form_rejects_invalid_identity_location_consent_and_honeypot(self):
        response = self.submit(
            cui="ABC123",
            registered_office_siruta="124215",
            privacy_consent="",
            website="robot",
        )

        self.assertContains(response, "CUI / CIF valid")
        self.assertContains(response, "localitate din județul selectat")
        self.assertEqual(ProviderRegistrationRequest.objects.count(), 0)

    def test_form_requires_a_known_service_category(self):
        response = self.submit(requested_category="")

        self.assertContains(response, "Alege serviciul principal prestat")
        self.assertEqual(ProviderRegistrationRequest.objects.count(), 0)

        response = self.submit(requested_category="categorie-inventată")

        self.assertContains(response, "nu face parte din opțiunile disponibile")
        self.assertEqual(ProviderRegistrationRequest.objects.count(), 0)

    def test_verified_admin_conversion_creates_identity_and_existing_claim_review(self):
        self.submit()
        registration = ProviderRegistrationRequest.objects.get()
        ProviderRegistrationRequest.objects.filter(pk=registration.pk).update(
            status=ProviderRegistrationRequest.Status.REVIEW_PENDING,
            email_verified_at=timezone.now(),
        )
        reviewer = get_user_model().objects.create_user(
            username="registration-reviewer",
            email="reviewer@example.test",
            is_staff=True,
        )
        reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_registration")
        )

        claim = convert_provider_registration_to_claim(
            registration_id=registration.pk,
            reviewer=reviewer,
            verified_registration_number="J22/1234/2026",
            review_note="Identitate verificată în registrul oficial.",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )

        registration.refresh_from_db()
        self.assertEqual(registration.status, registration.Status.CONVERTED)
        self.assertEqual(registration.converted_claim, claim)
        self.assertEqual(claim.status, ProviderClaimRequest.Status.REVIEW_PENDING)
        self.assertEqual(claim.email, "ana@example.com")
        self.assertEqual(BusinessIdentity.objects.count(), 1)
        self.assertFalse(hasattr(claim.business, "provider_profile"))
        self.assertEqual(claim.representation_evidence.mime_type, "application/pdf")
        self.assertFalse(
            registration.__class__.objects.filter(
                pk=registration.pk, representation_evidence__isnull=False
            ).exists()
        )

    def test_admin_review_get_is_inert_and_post_continues_to_claim_review(self):
        self.submit()
        registration = ProviderRegistrationRequest.objects.get()
        ProviderRegistrationRequest.objects.filter(pk=registration.pk).update(
            status=ProviderRegistrationRequest.Status.REVIEW_PENDING,
            email_verified_at=timezone.now(),
        )
        reviewer = get_user_model().objects.create_user(
            username="admin-registration-reviewer",
            email="admin-reviewer@example.test",
            is_staff=True,
        )
        reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_registration"),
            Permission.objects.get(codename="review_provider_claim"),
        )
        self.client.force_login(reviewer)
        review_url = reverse(
            "admin:services_providerregistrationrequest_review",
            args=(registration.pk,),
        )

        landing = self.client.get(review_url)
        self.assertContains(landing, "Verifică înscrierea")
        self.assertContains(landing, "Electricitate")
        evidence_url = reverse(
            "admin:services_providerregistrationrequest_evidence",
            args=(registration.pk,),
        )
        self.assertContains(landing, evidence_url)
        evidence_response = self.client.get(evidence_url)
        self.assertEqual(evidence_response.status_code, 200)
        self.assertTrue(
            evidence_response["Content-Disposition"].startswith("attachment;")
        )
        self.assertEqual(BusinessIdentity.objects.count(), 0)

        response = self.client.post(
            review_url,
            {
                "decision": "convert",
                "verified_registration_number": "J22/1234/2026",
                "review_note": "Identitate verificată în registrul oficial.",
                "acknowledgement": "on",
            },
        )
        claim = ProviderClaimRequest.objects.get()
        self.assertRedirects(
            response,
            reverse("admin:services_providerclaimrequest_review", args=(claim.pk,)),
            fetch_redirect_response=False,
        )

    def test_registration_retries_are_bounded_and_expired_token_fails_closed(self):
        for _index in range(3):
            self.assertContains(self.submit(), "Cererea a intrat în verificare")
        self.assertContains(self.submit(), "prea multe cereri")
        registrations = list(ProviderRegistrationRequest.objects.order_by("created_at"))
        self.assertEqual(
            [item.status for item in registrations],
            [
                ProviderRegistrationRequest.Status.REVIEW_PENDING,
                ProviderRegistrationRequest.Status.REVIEW_PENDING,
                ProviderRegistrationRequest.Status.REVIEW_PENDING,
            ],
        )
        response = self.client.get(
            reverse("services:company_registration_confirm", args=("unused-token",))
        )
        self.assertEqual(response.status_code, 410)

    def test_english_entry_page_and_locality_api_are_wired(self):
        page = self.client.get("/en/inscrie-firma/")

        self.assertContains(page, '<html lang="en">')
        self.assertContains(page, "Request company registration")
        self.assertContains(page, 'data-locations-url="/en/api/localitati/"')
