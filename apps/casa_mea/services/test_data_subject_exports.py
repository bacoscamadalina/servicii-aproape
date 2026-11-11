"""Security and audit contracts for controlled personal-data JSON exports."""

from datetime import timedelta
from hashlib import sha256
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .data_subject_exports import (
    EXPORT_ACKNOWLEDGEMENT,
    EXPORT_FILENAME,
    generate_data_subject_export,
)
from .data_subject_requests import initial_data_request_due_at
from .provider_billing import save_provider_billing_identity
from .models import (
    BusinessIdentity,
    DataSubjectRequest,
    DataSubjectRequestEvent,
    ProviderClaimRequest,
    ProviderCRMCustomer,
    ProviderDraftCoverage,
    ProviderDraftService,
    ProviderServiceAreaDraft,
)
from .test_provider_offerings import ProviderOfferingFixtureMixin


class DataSubjectExportTests(ProviderOfferingFixtureMixin, TestCase):
    """Prove exact-email scoping, secret exclusion and download audit behavior."""

    def setUp(self):
        self.create_fixture()
        self.processor = get_user_model().objects.create_user(
            username="privacy-exporter",
            email="operator-secret@example.test",
            password="operator-password",
            is_staff=True,
        )
        self.processor.user_permissions.add(
            Permission.objects.get(codename="view_datasubjectrequest"),
            Permission.objects.get(codename="process_data_subject_request"),
        )
        self.owner.set_password("owner-password")
        self.owner.save(update_fields=("password",))
        self.profile.display_name = "Atelierul persoanei vizate"
        self.profile.description = "Descriere declarată de furnizor."
        self.profile.public_address = "Strada Atelierului 12, Iași"
        self.profile.public_email = "owner@example.test"
        self.profile.save()
        draft = ProviderServiceAreaDraft.objects.create(
            profile=self.profile,
            revision=1,
            authorization_run=self.base,
            siruta_catalogue_version="2025",
            siruta_catalogue_sha256="9" * 64,
            updated_by=self.owner,
        )
        ProviderDraftService.objects.create(draft=draft, category="constructii")
        ProviderDraftCoverage.objects.create(
            draft=draft, county="Iași", siruta_code="95079"
        )
        self.received_at = timezone.now().replace(microsecond=0)
        self.item = DataSubjectRequest.objects.create(
            request_kind=DataSubjectRequest.Kind.ACCESS,
            channel=DataSubjectRequest.Channel.EMAIL,
            requester_name="Ana Test",
            contact_email="OWNER@EXAMPLE.TEST",
            details="Solicită copia datelor asociate contului său.",
            status=DataSubjectRequest.Status.IN_REVIEW,
            received_at=self.received_at,
            due_at=initial_data_request_due_at(self.received_at),
            identity_verified_at=self.received_at,
            recorded_by=self.processor,
        )
        third_party_business = BusinessIdentity.objects.create(
            registration_number="J22/999/2026"
        )
        ProviderClaimRequest.objects.create(
            business=third_party_business,
            legal_name_at_request="COMPANIE TERȚĂ SECRETĂ",
            contact_name="Persoană Terță Secretă",
            role="administrator",
            email="third-party@example.test",
            token_digest="7" * 64,
            token_expires_at=self.received_at + timedelta(hours=1),
            privacy_notice_version="1",
            consented_at=self.received_at,
        )

    def test_export_contains_owned_data_and_excludes_secrets_and_third_parties(self):
        ProviderCRMCustomer.objects.create(
            profile=self.profile,
            name="Proprietar Contact",
            email="owner@example.test",
            phone="0712 111 222",
            notes="Contact păstrat în registrul privat.",
            created_by=self.owner,
            updated_by=self.owner,
        )
        save_provider_billing_identity(
            user=self.owner,
            expected_revision=0,
            values={
                "legal_name": "Atelierul persoanei vizate SRL",
                "fiscal_identifier": "RO12345678",
                "registration_number": "J22/123/2026",
                "registered_address": "Strada Emitentului 3, Iași",
            },
        )
        content = generate_data_subject_export(
            request_id=self.item.pk,
            actor=self.processor,
            expected_revision=0,
            acknowledgement=EXPORT_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(hours=1),
        )
        text = content.decode("utf-8")
        payload = json.loads(text)

        self.assertEqual(
            payload["request"]["verified_contact_email"], "owner@example.test"
        )
        self.assertEqual(payload["accounts"][0]["email"], "owner@example.test")
        self.assertEqual(payload["accounts"][0]["username"], "provider-owner")
        self.assertEqual(payload["schema_version"], 12)
        self.assertEqual(
            payload["provider_customer_records"][0]["phone"], "0712 111 222"
        )
        self.assertEqual(
            payload["provider_profiles"][0]["service_declaration"]["services"],
            ["constructii"],
        )
        self.assertEqual(
            payload["provider_profiles"][0]["service_declaration"]["coverage"][0][
                "locality"
            ],
            "Iași",
        )
        self.assertEqual(
            payload["provider_profiles"][0]["public_address"],
            "Strada Atelierului 12, Iași",
        )
        self.assertEqual(
            payload["provider_profiles"][0]["billing_identity"]["fiscal_identifier"],
            "RO12345678",
        )
        self.assertEqual(
            payload["provider_profiles"][0]["billing_identity"]["revisions"][0]["revision"],
            1,
        )
        for forbidden in (
            self.owner.password,
            "owner-password",
            "operator-secret@example.test",
            "Verificare administrativă separată.",
            "7" * 64,
            "COMPANIE TERȚĂ SECRETĂ",
            "third-party@example.test",
            "token_digest",
            "password",
            "review_note",
            "reviewed_by",
        ):
            self.assertNotIn(forbidden, text)

        self.item.refresh_from_db()
        event = self.item.events.get()
        self.assertEqual(self.item.revision, 1)
        self.assertEqual(event.action, DataSubjectRequestEvent.Action.EXPORT_GENERATED)
        self.assertEqual(event.previous_status, DataSubjectRequest.Status.IN_REVIEW)
        self.assertEqual(event.new_status, DataSubjectRequest.Status.IN_REVIEW)
        self.assertIn(sha256(content).hexdigest(), event.internal_note)

    def test_export_fails_closed_without_mutating_audit(self):
        cases = (
            {"expected_revision": 1},
            {"acknowledgement": "confirmare aproximativă"},
        )
        for overrides in cases:
            arguments = {
                "request_id": self.item.pk,
                "actor": self.processor,
                "expected_revision": 0,
                "acknowledgement": EXPORT_ACKNOWLEDGEMENT,
            }
            arguments.update(overrides)
            with self.assertRaises(ValueError):
                generate_data_subject_export(**arguments)
        self.item.refresh_from_db()
        self.assertEqual(self.item.revision, 0)
        self.assertFalse(self.item.events.exists())

        unprivileged = get_user_model().objects.create_user(
            username="privacy-unprivileged", is_staff=True
        )
        with self.assertRaises(PermissionError):
            generate_data_subject_export(
                request_id=self.item.pk,
                actor=unprivileged,
                expected_revision=0,
                acknowledgement=EXPORT_ACKNOWLEDGEMENT,
            )
        self.assertFalse(self.item.events.exists())

    def test_wrong_request_kind_and_unverified_state_are_rejected(self):
        DataSubjectRequest.objects.filter(pk=self.item.pk).update(
            request_kind=DataSubjectRequest.Kind.ERASURE
        )
        with self.assertRaisesMessage(ValueError, "acces sau portabilitate"):
            generate_data_subject_export(
                request_id=self.item.pk,
                actor=self.processor,
                expected_revision=0,
                acknowledgement=EXPORT_ACKNOWLEDGEMENT,
            )
        DataSubjectRequest.objects.filter(pk=self.item.pk).update(
            request_kind=DataSubjectRequest.Kind.ACCESS,
            status=DataSubjectRequest.Status.IDENTITY_PENDING,
            identity_verified_at=None,
        )
        with self.assertRaisesMessage(ValueError, "Identitatea"):
            generate_data_subject_export(
                request_id=self.item.pk,
                actor=self.processor,
                expected_revision=0,
                acknowledgement=EXPORT_ACKNOWLEDGEMENT,
            )
        self.assertFalse(self.item.events.exists())

    def test_admin_download_is_no_store_and_audited(self):
        self.client.force_login(self.processor)
        response = self.client.post(
            reverse("admin:services_datasubjectrequest_process", args=(self.item.pk,)),
            {
                "action": "generate_export",
                "internal_note": "",
                "acknowledgement": "on",
                "expected_revision": 0,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertIn(EXPORT_FILENAME, response["Content-Disposition"])
        self.assertEqual(json.loads(response.content)["schema_version"], 12)
        self.item.refresh_from_db()
        self.assertEqual(self.item.revision, 1)
        self.assertEqual(
            self.item.events.get().action,
            DataSubjectRequestEvent.Action.EXPORT_GENERATED,
        )

    def test_admin_get_is_inert_and_explains_export_boundary(self):
        self.client.force_login(self.processor)
        response = self.client.get(
            reverse("admin:services_datasubjectrequest_process", args=(self.item.pk,))
        )

        self.assertContains(response, "Generează pachetul JSON")
        self.assertContains(response, "nu păstrat ca fișier pe server")
        self.item.refresh_from_db()
        self.assertEqual(self.item.revision, 0)
        self.assertFalse(self.item.events.exists())
