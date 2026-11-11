"""Private intake contracts for the managed Partner plan."""

from unittest.mock import patch

from django.core import mail
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .managed_site_inquiries import (
    PROCESS_ACKNOWLEDGEMENT,
    transition_managed_site_inquiry,
)
from .models import ManagedSiteInquiry, ManagedSiteInquiryEvent, ProviderSubscription
from .test_provider_offerings import ProviderOfferingFixtureMixin


@override_settings(
    READ_ONLY_PREVIEW=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    COMMERCIAL_EMAIL="commercial@example.test",
)
class ManagedSiteInquiryTests(ProviderOfferingFixtureMixin, TestCase):
    """Keep Partner briefs owner-only, bounded and separate from payment."""

    def setUp(self):
        self.create_fixture()
        self.client.force_login(self.owner)
        self.intake_url = reverse("services:managed_site_inquiry")
        self.success_url = reverse("services:managed_site_inquiry_success")
        self.payload = {
            "goal": ManagedSiteInquiry.Goal.NEW_PRESENCE,
            "desired_launch": ManagedSiteInquiry.DesiredLaunch.SIXTY_DAYS,
            "current_website": "https://firma-exemplu.test",
            "brief": (
                "Dorim un site care prezintă renovările, zonele deservite și permite "
                "clienților să solicite o ofertă clară."
            ),
            "consent": "on",
            "website": "",
        }

    def test_intake_requires_an_authenticated_active_provider_owner(self):
        anonymous = Client().get(self.intake_url)
        self.assertRedirects(
            anonymous,
            f"{reverse('services:provider_login')}?next={self.intake_url}",
        )

        self.membership.state = self.membership.State.REVOKED
        self.membership.revoked_at = timezone.now()
        self.membership.save(update_fields=("state", "revoked_at"))
        self.assertEqual(self.client.get(self.intake_url).status_code, 403)

    def test_get_is_private_and_explicitly_collects_no_payment_data(self):
        response = self.client.get(self.intake_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, noarchive")
        self.assertContains(response, self.profile.display_name)
        self.assertContains(response, "Fără plată acum")
        self.assertNotContains(response, 'name="card_number"')
        self.assertNotContains(response, 'name="cvv"')
        self.assertFalse(ManagedSiteInquiry.objects.exists())

    def test_valid_brief_is_saved_and_notification_contains_no_private_content(self):
        response = self.client.post(self.intake_url, self.payload)

        self.assertRedirects(response, self.success_url)
        inquiry = ManagedSiteInquiry.objects.get()
        self.assertEqual(inquiry.profile, self.profile)
        self.assertEqual(inquiry.created_by, self.owner)
        self.assertEqual(
            inquiry.notification_state, ManagedSiteInquiry.NotificationState.SENT
        )
        self.assertEqual(len(mail.outbox), 1)
        notification = mail.outbox[0].body
        self.assertIn(str(inquiry.profile.public_id), notification)
        self.assertNotIn(inquiry.brief, notification)
        self.assertNotIn(inquiry.current_website, notification)
        self.assertNotIn(self.owner.email, notification)

    def test_only_three_inquiries_are_accepted_for_one_profile_per_day(self):
        for _index in range(3):
            ManagedSiteInquiry.objects.create(
                profile=self.profile,
                created_by=self.owner,
                goal=ManagedSiteInquiry.Goal.NEW_PRESENCE,
                desired_launch=ManagedSiteInquiry.DesiredLaunch.EXPLORING,
                brief="Brief existent suficient de lung pentru limita zilnică.",
                privacy_notice_version="test",
                consented_at=timezone.now(),
            )

        response = self.client.post(self.intake_url, self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ai trimis deja mai multe solicitări astăzi")
        self.assertEqual(ManagedSiteInquiry.objects.count(), 3)
        self.assertEqual(len(mail.outbox), 0)

    @patch("services.views.send_mail", side_effect=RuntimeError("SMTP indisponibil"))
    def test_notification_failure_preserves_the_brief_for_operator_follow_up(self, _send):
        response = self.client.post(self.intake_url, self.payload)

        self.assertRedirects(response, self.success_url)
        self.assertEqual(
            ManagedSiteInquiry.objects.get().notification_state,
            ManagedSiteInquiry.NotificationState.FAILED,
        )

    @override_settings(READ_ONLY_PREVIEW=True)
    def test_read_only_preview_exposes_neither_intake_nor_confirmation(self):
        self.assertEqual(self.client.get(self.intake_url).status_code, 404)
        self.assertEqual(self.client.get(self.success_url).status_code, 404)

    def test_success_page_is_provider_only_and_truthful(self):
        response = self.client.get(self.success_url)
        self.assertContains(response, "Nu am creat o comandă")
        self.assertContains(response, "nu am procesat nicio plată")

        self.client.logout()
        self.assertRedirects(
            self.client.get(self.success_url),
            f"{reverse('services:provider_login')}?next={self.success_url}",
        )


class ManagedSiteInquiryWorkflowTests(ProviderOfferingFixtureMixin, TestCase):
    """Keep Partner progress forward-only, audited and provider-visible."""

    def setUp(self):
        self.create_fixture()
        self.inquiry = ManagedSiteInquiry.objects.create(
            profile=self.profile,
            created_by=self.owner,
            goal=ManagedSiteInquiry.Goal.MORE_REQUESTS,
            desired_launch=ManagedSiteInquiry.DesiredLaunch.SIXTY_DAYS,
            brief="Dorim un site administrat care să aducă solicitări locale relevante.",
            privacy_notice_version="test",
            consented_at=timezone.now(),
        )
        self.permission = Permission.objects.get(
            codename="process_managed_site_inquiry"
        )
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_managedsiteinquiry")
        )

    def transition(self, **overrides):
        values = {
            "inquiry_id": self.inquiry.pk,
            "actor": self.reviewer,
            "expected_revision": self.inquiry.revision,
            "new_status": ManagedSiteInquiry.Status.CONTACTED,
            "internal_note": "Furnizorul a fost contactat telefonic pentru clarificări.",
            "acknowledgement": PROCESS_ACKNOWLEDGEMENT,
        }
        values.update(overrides)
        return transition_managed_site_inquiry(**values)

    def test_transition_requires_the_dedicated_permission(self):
        with self.assertRaises(PermissionError):
            self.transition()
        self.assertFalse(ManagedSiteInquiryEvent.objects.exists())

    def test_forward_transition_is_revisioned_and_audited(self):
        self.reviewer.user_permissions.add(self.permission)

        transitioned = self.transition()

        self.assertEqual(transitioned.status, ManagedSiteInquiry.Status.CONTACTED)
        self.assertEqual(transitioned.revision, 1)
        event = ManagedSiteInquiryEvent.objects.get(inquiry=self.inquiry)
        self.assertEqual(event.previous_status, ManagedSiteInquiry.Status.RECEIVED)
        self.assertEqual(event.new_status, ManagedSiteInquiry.Status.CONTACTED)
        self.assertEqual(event.actor, self.reviewer)
        self.assertFalse(ProviderSubscription.objects.filter(profile=self.profile).exists())

    def test_invalid_jump_and_stale_revision_do_not_mutate_state(self):
        self.reviewer.user_permissions.add(self.permission)
        with self.assertRaises(ValueError):
            self.transition(new_status=ManagedSiteInquiry.Status.ACCEPTED)

        self.transition()
        with self.assertRaises(ValueError):
            self.transition(expected_revision=0, new_status=ManagedSiteInquiry.Status.PROPOSAL_SENT)
        self.assertEqual(ManagedSiteInquiryEvent.objects.count(), 1)

    def test_retained_inquiry_cannot_be_processed(self):
        self.reviewer.user_permissions.add(self.permission)
        self.inquiry.retention_applied_at = timezone.now()
        self.inquiry.save(update_fields=("retention_applied_at", "updated_at"))
        with self.assertRaises(ValueError):
            self.transition()

    def test_owner_dashboard_shows_status_without_internal_notes(self):
        self.reviewer.user_permissions.add(self.permission)
        self.transition()
        self.client.force_login(self.owner)

        response = self.client.get(reverse("services:provider_dashboard"))

        self.assertContains(response, "Site administrat · plan Partener")
        self.assertContains(response, "Discuție începută")
        self.assertNotContains(response, "contactat telefonic")

    def test_admin_workflow_requires_permission_and_records_post(self):
        url = reverse(
            "admin:services_managedsiteinquiry_process", args=(self.inquiry.pk,)
        )
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.reviewer.user_permissions.add(self.permission)
        self.reviewer = type(self.reviewer).objects.get(pk=self.reviewer.pk)
        self.client.force_login(self.reviewer)

        response = self.client.post(
            url,
            {
                "expected_revision": 0,
                "action": ManagedSiteInquiry.Status.CONTACTED,
                "internal_note": "Am stabilit o discuție inițială cu furnizorul.",
                "acknowledgement": "on",
            },
        )

        self.assertRedirects(response, url)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, ManagedSiteInquiry.Status.CONTACTED)
