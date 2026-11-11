"""Contracts for the explicitly isolated development provider journey."""

from io import StringIO

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    ProviderDevelopmentDemoGrant,
    ProviderRegistrationRequest,
    ProviderServiceAreaDraft,
    ProviderSubscription,
)
from .provider_offerings import replace_provider_services_and_coverage_for_owner
from .test_provider_offerings import ProviderOfferingFixtureMixin


class ProviderDevelopmentDemoTests(ProviderOfferingFixtureMixin, TestCase):
    """Keep demo authorization explicit, auditable and environment-bound."""

    def setUp(self):
        self.create_fixture()
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="manage_provider_development_demo"),
            Permission.objects.get(codename="manage_provider_subscription"),
        )
        now = timezone.now()
        ProviderRegistrationRequest.objects.create(
            legal_name="Atelier demonstrativ SRL",
            cui="12345678",
            registration_number=self.business.registration_number,
            registered_county="Iași",
            registered_office_siruta="95079",
            contact_name="Ana Test",
            role="administrator",
            email=self.owner.email,
            status=ProviderRegistrationRequest.Status.CONVERTED,
            token_digest="4" * 64,
            token_expires_at=now,
            email_verified_at=now,
            privacy_notice_version="1",
            consented_at=now,
            linked_business=self.business,
            converted_claim=self.profile.approved_claim,
            reviewed_at=now,
            reviewed_by=self.reviewer,
            review_note="Identitatea a fost verificată pentru demonstrație.",
            review_policy_version="1",
        )

    def command(self):
        output = StringIO()
        call_command(
            "enable_provider_development_demo",
            email=self.owner.email,
            actor=self.reviewer.username,
            categories=["constructii"],
            acknowledgement="SERVICIIAPROAPE_DEVELOPMENT_DEMO_ONLY",
            stdout=output,
        )
        return output.getvalue()

    @override_settings(PROVIDER_DEVELOPMENT_DEMO_ENABLED=True)
    def test_command_creates_grant_subscription_and_repins_existing_draft(self):
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        self.business.snapshot_records.filter(import_run=self.base).delete()

        output = self.command()

        grant = ProviderDevelopmentDemoGrant.objects.get(profile=self.profile)
        draft = ProviderServiceAreaDraft.objects.get(profile=self.profile)
        subscription = ProviderSubscription.objects.get(profile=self.profile)
        self.assertEqual(grant.authorization_run.snapshot.provider, "SERVICIIAPROAPE_DEMO")
        self.assertEqual(grant.catalogue_run, self.current)
        self.assertEqual(draft.authorization_run, grant.authorization_run)
        self.assertEqual(draft.revision, 2)
        self.assertEqual(subscription.status, ProviderSubscription.Status.ACTIVE)
        self.assertIn(f"profile_id={self.profile.pk}", output)

        original_end = subscription.period_ends_at
        self.command()
        subscription.refresh_from_db()
        self.assertEqual(subscription.period_ends_at, original_end)

    @override_settings(PROVIDER_DEVELOPMENT_DEMO_ENABLED=False)
    def test_command_refuses_non_development_environment(self):
        with self.assertRaisesMessage(CommandError, "dezactivat"):
            self.command()
