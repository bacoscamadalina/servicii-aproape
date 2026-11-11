"""End-to-end contracts for minimum-data provider claim initiation."""

from datetime import timedelta
import re
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth.hashers import check_password
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    ProviderClaimRequest,
    ProviderRepresentationEvidence,
    RegisteredBusinessSnapshot,
)
from .provider_claims import PRIVACY_NOTICE_VERSION
from .test_catalogue_activation import CatalogueFixtureMixin
from .test_representation_evidence import representation_evidence_upload


@override_settings(
    DEBUG=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="ServiciiAproape <test@example.com>",
)
class ProviderClaimFlowTests(CatalogueFixtureMixin, TestCase):
    def setUp(self):
        self.record = self.build_catalogue(total=1)[0]
        self.activate_preview()
        self.query = {
            "county": "Iași",
            "locality": "95079",
            "category": "constructii",
        }
        self.url = reverse(
            "services:company_claim", args=(self.record.business_id,)
        )
        self.payload = {
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

    def submit(self, **overrides):
        payload = {
            **self.payload,
            "evidence_document": representation_evidence_upload(),
            **overrides,
        }
        return self.client.post(self.url, payload, query_params=self.query)

    def test_claim_enters_review_without_email_and_retains_only_password_hash(self):
        response = self.submit()

        self.assertContains(response, "Cererea a intrat în verificare")
        self.assertEqual(len(mail.outbox), 0)
        claim = ProviderClaimRequest.objects.get()
        self.assertEqual(claim.email, "ana@example.com")
        self.assertEqual(claim.privacy_notice_version, PRIVACY_NOTICE_VERSION)
        self.assertEqual(claim.status, ProviderClaimRequest.Status.REVIEW_PENDING)
        self.assertIsNone(claim.email_verified_at)
        self.assertEqual(claim.account_first_name, "Ana")
        self.assertEqual(claim.account_last_name, "Reprezentant")
        self.assertEqual(claim.account_username, "ana.reprezentant")
        self.assertNotEqual(claim.password_hash, self.payload["password1"])
        self.assertTrue(check_password(self.payload["password1"], claim.password_hash))
        evidence = claim.representation_evidence
        self.assertEqual(
            evidence.evidence_type,
            ProviderRepresentationEvidence.EvidenceType.ONRC_DOCUMENT,
        )
        self.assertEqual(evidence.mime_type, "application/pdf")
        self.assertEqual(evidence.byte_size, len(bytes(evidence.document)))
        self.assertLessEqual(claim.token_expires_at, timezone.now())

    def test_claim_form_is_scope_bound_minimal_and_never_publishes_contact(self):
        page = self.client.get(self.url, self.query)
        self.assertContains(page, "Revendică profilul FIRMA 000 SRL")
        self.assertNotIn("FIRMA 000 SRL.</h1>", page.content.decode())
        self.assertContains(page, "Înapoi la fișa firmei", count=1)
        self.assertContains(page, "Date pentru verificare")
        self.assertContains(page, "Document justificativ")
        self.assertContains(page, 'enctype="multipart/form-data"')
        self.assertContains(page, reverse("services:privacy"))
        self.assertContains(page, "prelucrarea datelor personale")
        self.assertNotContains(page, self.record.cui)
        self.assertEqual(
            self.client.get(
                self.url,
                {**self.query, "locality": "95408"},
            ).status_code,
            404,
        )

        self.submit()
        detail = self.client.get(
            reverse("services:company_detail", args=(self.record.business_id,)),
            self.query,
        )
        self.assertNotContains(detail, "ana@example.com")
        self.assertNotContains(detail, "Ana Reprezentant")
        self.assertNotContains(detail, "dovada-reprezentare")

    def test_retries_rotate_pending_token_and_are_rate_limited(self):
        for _index in range(3):
            self.assertContains(self.submit(), "Cererea a intrat în verificare")
        claims = list(ProviderClaimRequest.objects.order_by("created_at"))
        self.assertEqual(len(claims), 3)
        self.assertEqual(
            [claim.status for claim in claims],
            [
                ProviderClaimRequest.Status.REVIEW_PENDING,
                ProviderClaimRequest.Status.REVIEW_PENDING,
                ProviderClaimRequest.Status.REVIEW_PENDING,
            ],
        )

        limited = self.submit()
        self.assertContains(limited, "prea multe cereri")
        self.assertEqual(ProviderClaimRequest.objects.count(), 3)

    def test_new_claim_does_not_expose_a_confirmation_link(self):
        self.submit()
        response = self.client.get(
            reverse("services:company_claim_confirm", args=("unused-token",))
        )
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "Linkul nu mai este activ", status_code=410)

    def test_claim_submission_never_calls_email_delivery(self):
        with patch("services.provider_claims.send_mail", side_effect=RuntimeError):
            response = self.submit()

        self.assertContains(response, "Cererea a intrat în verificare")
        claim = ProviderClaimRequest.objects.get()
        self.assertEqual(
            claim.email_delivery_state, ProviderClaimRequest.DeliveryState.PENDING
        )

    def test_invalid_form_and_honeypot_create_nothing(self):
        response = self.submit(email="invalid", privacy_consent="", website="bot")
        self.assertContains(response, "Introduceți o adresă de email validă")
        self.assertEqual(ProviderClaimRequest.objects.count(), 0)

        missing_proof = self.submit(evidence_document="")
        self.assertContains(missing_proof, "Încarcă documentul")
        self.assertEqual(ProviderClaimRequest.objects.count(), 0)

        self.run.state = self.run.State.FAILED
        self.run.save(update_fields=("state",))
        self.assertEqual(self.client.get(self.url, self.query).status_code, 404)
