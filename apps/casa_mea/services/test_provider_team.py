"""Technician assignment must not inherit the owner's customer-request access."""

from datetime import timedelta
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    ProviderLead,
    ProviderPublicationSubmission,
    ProviderQuote,
    ProviderTeamMember,
    ProviderTeamInvitation,
    ProviderWorkOrder,
)
from .provider_leads import (
    cancel_provider_work_schedule, complete_provider_work_order,
    provider_leads_for_owner, schedule_provider_work_order,
)
from .provider_offerings import (
    replace_provider_services_and_coverage_for_owner,
    submit_provider_service_area_for_review,
)
from .provider_team import (
    assign_provider_technician,
    assigned_provider_work_for_technician,
    issue_provider_team_invitation,
    pending_provider_team_invitation,
    revoke_provider_technician,
    update_assigned_work_execution,
)
from .test_provider_offerings import ProviderOfferingFixtureMixin


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ProviderTeamTests(ProviderOfferingFixtureMixin, TestCase):
    """Exercise the new boundary with synthetic records and no live customer data."""

    def setUp(self):
        self.create_fixture()
        replace_provider_services_and_coverage_for_owner(
            user=self.owner, expected_revision=0,
            categories=["constructii"], coverage_pairs=[("Iași", "95079")],
        )
        offering, _ = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1,
        )
        submission = ProviderPublicationSubmission.objects.create(
            profile=self.profile, version=1, profile_content_revision=0,
            display_name="Atelier Test", service_area_submission=offering,
            authorization_run=self.current, catalogue_run=self.current,
            siruta_catalogue_version="test", siruta_catalogue_sha256="a" * 64,
            contract_sha256="b" * 64, submitted_by=self.owner,
        )
        User = get_user_model()
        self.technician = User.objects.create_user(
            username="team-technician", email="technician@example.test", password="example-pass",
        )
        self.other_technician = User.objects.create_user(
            username="other-technician", email="other@example.test", password="example-pass",
        )
        self.member = ProviderTeamMember.objects.create(
            profile=self.profile, user=self.technician,
        )
        self.other_member = ProviderTeamMember.objects.create(
            profile=self.profile, user=self.other_technician,
        )
        self.lead = ProviderLead.objects.create(
            submission=submission,
            category="constructii", county="Iași", siruta_code="95079",
            customer_name="Client de test", customer_email="client@example.test",
            customer_phone="0712000111", description="Lucrare de test cu informații private.",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            status=ProviderLead.Status.WON,
            visitor_session_digest="a" * 64,
            customer_access_digest="b" * 64,
            customer_access_expires_at=timezone.now() + timedelta(days=30),
            privacy_notice_version="test",
        )
        self.quote = ProviderQuote.objects.create(
            lead=self.lead, revision=1, amount_ron="7500.00",
            summary="Executarea lucrării de test.", estimated_duration="O zi",
            valid_until=timezone.localdate() + timedelta(days=7),
            status=ProviderQuote.Status.ACCEPTED, sent_by=self.owner,
            responded_at=timezone.now(),
        )
        self.order = ProviderWorkOrder.objects.create(
            lead=self.lead, accepted_quote=self.quote,
            status=ProviderWorkOrder.Status.SCHEDULED,
            scheduled_start=timezone.now() + timedelta(days=2),
        )

    def test_assignment_is_revisioned_and_reader_excludes_unassigned_users(self):
        """Technician reader grants one current job, never the owner's lead queue."""

        with self.assertRaises(PermissionError):
            provider_leads_for_owner(self.technician)
        self.assertEqual(list(assigned_provider_work_for_technician(self.technician)), [])
        order = assign_provider_technician(
            user=self.owner, lead_id=self.lead.pk,
            member_id=self.member.pk, expected_revision=0,
        )
        self.assertEqual(order.assignment_revision, 1)
        self.assertEqual(list(assigned_provider_work_for_technician(self.technician)), [order])
        self.assertEqual(list(assigned_provider_work_for_technician(self.other_technician)), [])
        self.technician.is_active = False
        self.technician.save(update_fields=("is_active",))
        with self.assertRaises(PermissionError):
            assigned_provider_work_for_technician(self.technician)
        self.technician.is_active = True
        self.technician.save(update_fields=("is_active",))
        self.assertEqual(order.assignment_events.count(), 1)
        with self.assertRaisesMessage(ValueError, "modificată"):
            assign_provider_technician(
                user=self.owner, lead_id=self.lead.pk,
                member_id=self.other_member.pk, expected_revision=0,
            )
        with self.assertRaises(PermissionError):
            assign_provider_technician(
                user=self.technician, lead_id=self.lead.pk,
                member_id=self.member.pk, expected_revision=1,
            )
        order = assign_provider_technician(
            user=self.owner, lead_id=self.lead.pk,
            member_id=self.other_member.pk, expected_revision=1,
        )
        self.assertEqual(list(assigned_provider_work_for_technician(self.technician)), [])
        self.assertEqual(list(assigned_provider_work_for_technician(self.other_technician)), [order])
        self.assertEqual(order.assignment_events.get(revision=2).previous_technician, self.member)

    def test_revocation_cuts_access_and_cancel_removes_assignment(self):
        """A revoked account sees nothing even when its order still points to it."""

        order = assign_provider_technician(
            user=self.owner, lead_id=self.lead.pk,
            member_id=self.member.pk, expected_revision=0,
        )
        pending_read = assigned_provider_work_for_technician(self.technician)
        revoke_provider_technician(user=self.owner, member_id=self.member.pk)
        self.member.refresh_from_db()
        self.assertEqual(self.member.revoked_by, self.owner)
        with self.assertRaises(PermissionError):
            assigned_provider_work_for_technician(self.technician)
        self.assertEqual(list(pending_read), [])
        order = assign_provider_technician(
            user=self.owner, lead_id=self.lead.pk,
            member_id=self.other_member.pk, expected_revision=order.assignment_revision,
        )
        self.assertEqual(list(assigned_provider_work_for_technician(self.other_technician)), [order])
        cancelled = cancel_provider_work_schedule(
            user=self.owner, lead_id=self.lead.pk, expected_revision=order.revision,
        )
        self.assertIsNone(cancelled.assigned_technician)
        self.assertEqual(cancelled.assignment_revision, 3)
        self.assertEqual(cancelled.assignment_events.get(revision=3).actor, self.owner)
        self.assertEqual(list(assigned_provider_work_for_technician(self.other_technician)), [])
        with self.assertRaises(ValueError):
            assign_provider_technician(
                user=self.owner, lead_id=self.lead.pk,
                member_id=self.other_member.pk, expected_revision=3,
            )

    def test_membership_uniqueness_and_unknown_member_fail_closed(self):
        """Duplicate memberships and missing assignees cannot grant access."""

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                ProviderTeamMember.objects.create(profile=self.profile, user=self.member.user)
        self.assertEqual(self.member.profile_id, self.profile.pk)
        with self.assertRaises(ProviderTeamMember.DoesNotExist):
            assign_provider_technician(
                user=self.owner, lead_id=self.lead.pk,
                member_id=999999, expected_revision=0,
            )

    def test_technician_confirms_start_and_completion_without_owner_access(self):
        """Execution has separate confirmations and auditable revisions."""

        assign_provider_technician(
            user=self.owner, lead_id=self.lead.pk,
            member_id=self.member.pk, expected_revision=0,
        )
        url = reverse("services:technician_work")
        self.client.force_login(self.technician)
        self.assertContains(self.client.get(url), "Poți confirma începutul după ora programată")
        early = self.client.post(url, {
            "order_id": self.order.pk, "expected_revision": 0, "action": "start",
        }, follow=True)
        self.assertContains(early, "Lucrarea nu poate începe înainte de ora programată")
        self.order.refresh_from_db()
        self.assertIsNone(self.order.started_at)
        ProviderWorkOrder.objects.filter(pk=self.order.pk).update(
            scheduled_start=timezone.now() - timedelta(minutes=15),
        )
        started = self.client.post(url, {
            "order_id": self.order.pk, "expected_revision": 0, "action": "start",
        }, follow=True)
        self.assertContains(started, "Începerea lucrării a fost înregistrată")
        self.order.refresh_from_db()
        self.assertEqual(self.order.revision, 1)
        self.assertIsNotNone(self.order.started_at)
        self.assertEqual(self.order.events.get(revision=1).actor, self.technician)
        with self.assertRaisesMessage(ValueError, "atribui"):
            assign_provider_technician(
                user=self.owner, lead_id=self.lead.pk,
                member_id=self.other_member.pk, expected_revision=1,
            )
        with self.assertRaisesMessage(ValueError, "reprogramată"):
            schedule_provider_work_order(
                user=self.owner, lead_id=self.lead.pk, expected_revision=1,
                starts_at=timezone.now() + timedelta(days=1),
            )
        self.assertEqual(self.client.post(url, {
            "order_id": self.order.pk, "expected_revision": 1,
            "action": "complete",
        }, follow=True).status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ProviderWorkOrder.Status.SCHEDULED)
        self.client.force_login(self.other_technician)
        self.assertEqual(self.client.post(url, {
            "order_id": self.order.pk, "expected_revision": 1,
            "action": "complete", "confirm_completion": "on",
        }).status_code, 404)
        self.client.force_login(self.technician)
        finished = self.client.post(url, {
            "order_id": self.order.pk, "expected_revision": 1,
            "action": "complete", "confirm_completion": "on",
        }, follow=True)
        self.assertContains(finished, "Nu a fost emisă nicio factură")
        self.order.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(self.order.status, ProviderWorkOrder.Status.COMPLETED)
        self.assertEqual(self.lead.status, ProviderLead.Status.COMPLETED)
        self.assertEqual(self.order.events.get(revision=2).actor, self.technician)
        self.assertEqual(list(assigned_provider_work_for_technician(self.technician)), [])
        replay = self.client.post(url, {
            "order_id": self.order.pk, "expected_revision": 1,
            "action": "complete", "confirm_completion": "on",
        }, follow=True)
        self.assertContains(replay, "Lucrarea a fost modificată")
        self.order.refresh_from_db()
        self.assertEqual(self.order.revision, 2)

    def test_revoked_technician_cannot_finish_started_job(self):
        """Owner can still close a job when the assigned technician loses access."""

        assign_provider_technician(
            user=self.owner, lead_id=self.lead.pk,
            member_id=self.member.pk, expected_revision=0,
        )
        ProviderWorkOrder.objects.filter(pk=self.order.pk).update(
            scheduled_start=timezone.now() - timedelta(minutes=15),
        )
        update_assigned_work_execution(
            user=self.technician, order_id=self.order.pk,
            action="start", expected_revision=0,
        )
        revoke_provider_technician(user=self.owner, member_id=self.member.pk)
        with self.assertRaises(PermissionError):
            update_assigned_work_execution(
                user=self.technician, order_id=self.order.pk,
                action="complete", expected_revision=1,
            )
        completed = complete_provider_work_order(
            user=self.owner, lead_id=self.lead.pk, expected_revision=1,
        )
        self.assertEqual(completed.status, ProviderWorkOrder.Status.COMPLETED)

    def test_owner_sees_only_confirmed_same_technician_interval_overlap(self):
        """A shared assignee and two complete slots produce a scoped warning."""

        start = timezone.now() + timedelta(days=2)
        ProviderWorkOrder.objects.filter(pk=self.order.pk).update(
            scheduled_start=start, scheduled_end=start + timedelta(hours=3),
        )
        second_lead = ProviderLead.objects.create(
            submission=self.lead.submission, category="constructii", county="Iași",
            siruta_code="95079", customer_name="Alt client de test",
            customer_email="second@example.test", customer_phone="0712000222",
            description="A doua lucrare sintetică pentru calendar.",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            status=ProviderLead.Status.WON,
            visitor_session_digest="c" * 64, customer_access_digest="d" * 64,
            customer_access_expires_at=timezone.now() + timedelta(days=30),
            privacy_notice_version="test",
        )
        second_quote = ProviderQuote.objects.create(
            lead=second_lead, revision=1, amount_ron="200.00",
            summary="A doua lucrare de test.", estimated_duration="O oră",
            valid_until=timezone.localdate() + timedelta(days=7),
            status=ProviderQuote.Status.ACCEPTED, sent_by=self.owner,
            responded_at=timezone.now(),
        )
        second_order = ProviderWorkOrder.objects.create(
            lead=second_lead, accepted_quote=second_quote,
            status=ProviderWorkOrder.Status.SCHEDULED,
            scheduled_start=start + timedelta(hours=1),
            scheduled_end=start + timedelta(hours=2),
        )
        assign_provider_technician(user=self.owner, lead_id=self.lead.pk,
                                   member_id=self.member.pk, expected_revision=0)
        assign_provider_technician(user=self.owner, lead_id=second_lead.pk,
                                   member_id=self.other_member.pk, expected_revision=0)
        self.client.force_login(self.owner)
        url = reverse("services:provider_leads")
        separate = self.client.get(url, {"view": "work", "display": "calendar"})
        self.assertNotContains(separate, "Același tehnician are o altă lucrare")
        assign_provider_technician(user=self.owner, lead_id=second_lead.pk,
                                   member_id=self.member.pk, expected_revision=1)
        calendar = self.client.get(url, {"view": "work", "display": "calendar"})
        self.assertContains(calendar, "Același tehnician are o altă lucrare", count=2)
        requests = self.client.get(url, {"view": "requests"})
        self.assertContains(requests, "Același tehnician are o altă lucrare", count=2)
        technician_jobs = list(assigned_provider_work_for_technician(self.technician))
        self.assertEqual(len(technician_jobs), 2)
        self.assertTrue(all(job.known_assignee_overlap for job in technician_jobs))
        self.client.force_login(self.technician)
        self.assertContains(
            self.client.get(reverse("services:technician_work")),
            "Ai o altă lucrare în acest interval", count=2,
        )
        second_order.scheduled_end = None
        second_order.save(update_fields=("scheduled_end",))
        self.client.force_login(self.owner)
        incomplete = self.client.get(url, {"view": "work", "display": "calendar"})
        self.assertNotContains(incomplete, "Același tehnician are o altă lucrare")
        second_order.scheduled_start = start + timedelta(hours=3)
        second_order.scheduled_end = start + timedelta(hours=4)
        second_order.save(update_fields=("scheduled_start", "scheduled_end"))
        touching = self.client.get(url, {"view": "work", "display": "calendar"})
        self.assertNotContains(touching, "Același tehnician are o altă lucrare")

    def test_owner_invites_new_account_and_technician_sees_only_assigned_work(self):
        """Mailbox proof activates a separate account, never owner inbox access."""

        team_url = reverse("services:provider_team")
        self.client.force_login(self.technician)
        self.assertEqual(self.client.get(team_url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(team_url), "Invită un tehnician")
        sent = self.client.post(team_url, {"action": "invite", "email": "invitee@example.test"})
        self.assertRedirects(sent, team_url)
        invitation = ProviderTeamInvitation.objects.get(normalized_email="invitee@example.test")
        self.assertIsNone(invitation.accepted_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.lead.customer_name, mail.outbox[0].body)
        accept_url = re.search(r"https?://[^\s]+/cont/echipa/accepta/[^\s]+/", mail.outbox[0].body).group(0).removeprefix("http://testserver")
        self.client.logout()
        self.assertContains(self.client.get(accept_url), "Creează contul de tehnician")
        accepted = self.client.post(accept_url, {
            "first_name": "Ana", "last_name": "Tehnician",
            "username": "ana-tech", "password1": "ExamplePassword987!",
            "password2": "ExamplePassword987!",
        })
        self.assertRedirects(accepted, reverse("services:technician_work"))
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(invitation.accepted_by.username, "ana-tech")
        self.assertEqual(self.client.get(accept_url).status_code, 404)
        self.assertContains(self.client.get(reverse("services:technician_work")), "Nicio lucrare atribuită acum")
        self.assertEqual(self.client.get(reverse("services:provider_leads")).status_code, 403)
        self.assertEqual(self.client.get(reverse("services:provider_billing_identity")).status_code, 403)
        self.client.logout()
        logged_in = self.client.post(reverse("services:provider_login"), {
            "email": "invitee@example.test", "password": "ExamplePassword987!",
        })
        self.assertRedirects(logged_in, reverse("services:technician_work"))
        self.client.force_login(self.owner)
        member = ProviderTeamMember.objects.get(user=invitation.accepted_by)
        assigned = self.client.post(reverse("services:provider_leads"), {
            "lead_id": self.lead.pk, "action": "work_assign",
            f"assign-{self.lead.pk}-expected_revision": 0,
            f"assign-{self.lead.pk}-member_id": member.pk,
        })
        self.assertEqual(assigned.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotIn(self.lead.customer_name, mail.outbox[-1].body)
        self.client.force_login(invitation.accepted_by)
        self.assertContains(self.client.get(reverse("services:technician_work")), self.lead.customer_name)
        self.client.force_login(self.owner)
        revoked = self.client.post(team_url, {"action": "revoke_member", "record_id": member.pk})
        self.assertRedirects(revoked, team_url)
        self.client.force_login(invitation.accepted_by)
        self.assertEqual(self.client.get(reverse("services:technician_work")).status_code, 403)

    def test_existing_account_expiry_replay_and_delivery_failure(self):
        """Old or undelivered links cannot silently activate another account."""

        User = get_user_model()
        existing = User.objects.create_user(
            username="existing-tech", email="existing@example.test", password="ExamplePassword987!",
        )
        invitation, token = issue_provider_team_invitation(user=self.owner, email=existing.email)
        accept_url = reverse("services:provider_team_accept", args=(token,))
        self.assertContains(self.client.get(accept_url), "Confirmă contul existent")
        wrong = self.client.post(accept_url, {"password": "wrong"})
        self.assertContains(wrong, "Parola contului nu este corectă")
        self.assertFalse(ProviderTeamMember.objects.filter(user=existing).exists())
        accepted = self.client.post(accept_url, {"password": "ExamplePassword987!"})
        self.assertRedirects(accepted, reverse("services:technician_work"))
        self.assertEqual(self.client.post(accept_url, {"password": "ExamplePassword987!"}).status_code, 404)

        expiring, expiring_token = issue_provider_team_invitation(
            user=self.owner, email="expired@example.test",
        )
        ProviderTeamInvitation.objects.filter(pk=expiring.pk).update(
            created_at=timezone.now() - timedelta(days=3),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(ProviderTeamInvitation.DoesNotExist):
            pending_provider_team_invitation(expiring_token)
        self.assertEqual(self.client.get(reverse("services:provider_team_accept", args=(expiring_token,))).status_code, 404)
        replacement, _token = issue_provider_team_invitation(
            user=self.owner, email="expired@example.test",
        )
        expiring.refresh_from_db()
        self.assertIsNotNone(expiring.revoked_at)
        self.assertNotEqual(replacement.pk, expiring.pk)

        self.client.force_login(self.owner)
        with patch("services.views.send_mail", side_effect=RuntimeError("smtp unavailable")):
            failed = self.client.post(reverse("services:provider_team"), {
                "action": "invite", "email": "undelivered@example.test",
            })
        self.assertContains(failed, "Invitația nu a putut fi trimisă")
        undelivered = ProviderTeamInvitation.objects.get(normalized_email="undelivered@example.test")
        self.assertIsNotNone(undelivered.revoked_at)
