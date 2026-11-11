"""Owner-only preparation of issuer details, without invoice issuance."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from .models import ProviderBillingIdentity, ProviderBillingIdentityEvent, ProviderInvoiceDraft, ProviderMembership
from .provider_billing import save_provider_billing_identity
from .test_provider_offerings import ProviderOfferingFixtureMixin


class ProviderBillingIdentityTests(ProviderOfferingFixtureMixin, TestCase):
    """Provider declarations cannot leak into public facts or fiscal state."""

    def setUp(self):
        self.create_fixture()
        self.url = reverse("services:provider_billing_identity")
        self.values = {
            "legal_name": "Atelier Test S.R.L.",
            "fiscal_identifier": "RO12345678",
            "registration_number": "J22/1/2020",
            "registered_address": "Strada Exemplului 10, Iași, România",
        }

    def test_owner_creates_updates_and_sees_only_unverified_declaration(self):
        """Each real change gets one revision, but no invoice or public edit."""

        self.client.force_login(self.owner)
        empty = self.client.get(self.url)
        self.assertContains(empty, "Nu există încă date declarate")
        self.assertNotContains(empty, "RO12345678")
        created = self.client.post(
            self.url, {"action": "save_billing_identity", "expected_revision": 0, **self.values},
        )
        self.assertRedirects(created, self.url)
        identity = ProviderBillingIdentity.objects.get(profile=self.profile)
        self.assertEqual(identity.revision, 1)
        self.assertEqual(identity.events.count(), 1)
        self.assertEqual(identity.updated_by, self.owner)
        self.assertContains(self.client.get(self.url), "RO12345678")
        self.assertEqual(ProviderInvoiceDraft.objects.count(), 0)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.public_content_revision, 0)

        same = self.client.post(
            self.url, {"action": "save_billing_identity", "expected_revision": 1, **self.values},
        )
        self.assertRedirects(same, self.url)
        identity.refresh_from_db()
        self.assertEqual(identity.revision, 1)
        self.assertEqual(identity.events.count(), 1)

        changed = self.client.post(
            self.url, {
                "action": "save_billing_identity", "expected_revision": 1,
                **{**self.values, "registered_address": "Strada Nouă 20, Iași, România"},
            },
        )
        self.assertRedirects(changed, self.url)
        identity.refresh_from_db()
        self.assertEqual(identity.revision, 2)
        self.assertEqual(identity.events.count(), 2)
        self.assertEqual(identity.events.get(revision=1).registered_address, self.values["registered_address"])

    def test_stale_invalid_and_foreign_changes_fail_closed(self):
        """Missing authority, stale revisions, or malformed fields never write."""

        self.client.force_login(self.owner)
        invalid = self.client.post(
            self.url, {"action": "save_billing_identity", "expected_revision": 0,
                       **{**self.values, "registered_address": "scurt"}},
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "registered_address")
        self.assertFalse(ProviderBillingIdentity.objects.exists())

        identity, changed = save_provider_billing_identity(
            user=self.owner, expected_revision=0, values=self.values,
        )
        self.assertTrue(changed)
        stale = self.client.post(
            self.url, {"action": "save_billing_identity", "expected_revision": 0, **self.values},
        )
        self.assertContains(stale, "Datele de facturare s-au modificat")
        self.assertEqual(ProviderBillingIdentityEvent.objects.count(), 1)

        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"action": "save_billing_identity", "expected_revision": 1, **self.values}).status_code, 403)
        with self.assertRaises(PermissionError):
            save_provider_billing_identity(user=self.reviewer, expected_revision=1, values=self.values)
        self.client.force_login(self.owner)
        self.membership.state = ProviderMembership.State.REVOKED
        self.membership.revoked_at = timezone.now()
        self.membership.save(update_fields=("state", "revoked_at"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        with self.assertRaises(PermissionError):
            save_provider_billing_identity(user=self.owner, expected_revision=1, values=self.values)
        identity.refresh_from_db()
        self.assertEqual(identity.revision, 1)

    def test_english_page_preserves_non_fiscal_boundary(self):
        """The English route is translated without implying invoice issuance."""

        self.client.force_login(self.owner)
        with translation.override("en"):
            response = self.client.get(reverse("services:provider_billing_identity"))
        self.assertContains(response, "Issuer details")
        self.assertContains(response, "Fiscal issuance, RO e-Factura and payment recording are not active.")
