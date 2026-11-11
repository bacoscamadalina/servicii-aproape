"""End-to-end contracts for private customer requests sent to providers."""

from io import BytesIO
from io import StringIO
import re
import json
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.admin.models import LogEntry
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from .models import (
    CustomerAccount,
    ProviderCustomerReview,
    ProviderCustomerReviewEvent,
    ProviderCustomerReviewReply,
    ProviderLead,
    ProviderLeadBatch,
    ProviderLeadEvent,
    ProviderLeadMessage,
    ProviderQuote,
    ProviderVisitProposal,
    ProviderWorkOrder,
    ProviderWorkOrderEvent,
    ProviderInvoiceDraft,
    ProviderManualPayment,
    ProviderReceivable,
    ProviderReceivableFollowUpEvent,
    ProviderCRMCustomer,
    ProviderCRMCustomerEvent,
    ProviderLeadCustomerLinkEvent,
    ProviderPublicationSubmission,
)
from .owner_commands import owner_command_kind, parse_quote_command
from .provider_leads import (
    cancel_provider_visit_for_owner,
    create_provider_lead_batch,
    propose_provider_visit,
    respond_to_provider_visit,
    send_provider_quote,
    respond_to_provider_quote,
    schedule_provider_work_order,
    cancel_provider_work_schedule,
    complete_provider_work_order,
    save_provider_invoice_draft,
    update_provider_lead_for_owner,
)
from .provider_receivables import (
    open_provider_receivable,
    provider_receivable_totals,
    record_provider_manual_payment,
    schedule_provider_receivable_follow_up,
    void_provider_manual_payment,
)
from .delivery_audit import audit_request_delivery
from .lead_insights import provider_lead_insights
from .pilot_readiness import pilot_readiness
from .provider_offerings import (
    REVIEW_ACKNOWLEDGEMENT as OFFERING_ACKNOWLEDGEMENT,
    replace_provider_services_and_coverage_for_owner,
    review_provider_service_area_submission,
    submit_provider_service_area_for_review,
)
from .provider_publication import (
    REVIEW_ACKNOWLEDGEMENT,
    add_portfolio_image_for_owner,
    review_provider_publication,
    save_provider_profile_for_owner,
    submit_provider_publication_for_review,
)
from .provider_subscriptions import (
    SUBSCRIPTION_ACKNOWLEDGEMENT,
    activate_or_extend_provider_subscription,
)
from .test_provider_offerings import ProviderOfferingFixtureMixin


@override_settings(
    DEBUG=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@serviciiaproape.test",
)
class ProviderLeadTests(ProviderOfferingFixtureMixin, TestCase):
    """Keep public intake, owner access, and workflow transitions coherent."""

    def setUp(self):
        self.create_fixture()
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_service_area"),
            Permission.objects.get(codename="review_provider_publication"),
            Permission.objects.get(codename="publish_provider_profile"),
            Permission.objects.get(codename="manage_provider_subscription"),
            Permission.objects.get(codename="moderate_customer_review"),
            Permission.objects.get(codename="view_providercustomerreview"),
            Permission.objects.get(codename="moderate_customer_review_reply"),
            Permission.objects.get(codename="view_providercustomerreviewreply"),
        )
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        offering, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )
        review_provider_service_area_submission(
            submission_id=offering.pk,
            reviewer=self.reviewer,
            decision=offering.Decision.APPROVED,
            internal_note="Serviciul și localitatea au fost verificate.",
            provider_feedback="",
            acknowledgement=OFFERING_ACKNOWLEDGEMENT,
        )
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Test Aproape",
                "description": (
                    "Executăm lucrări de construcții pentru locuințe, cu evaluare "
                    "prealabilă, ofertă clară și acoperire declarată în Iași."
                ),
                "public_address": "Strada Atelierului 12, Iași",
                "public_phone": "0712 345 678",
                "public_email": "contact@atelier.example",
                "website": "https://atelier.example",
                "availability": self.profile.Availability.ACCEPTING,
                "contact_preference": self.profile.ContactPreference.PHONE,
            },
        )
        rendered = BytesIO()
        Image.new("RGB", (640, 480), "#d59b47").save(rendered, format="JPEG")
        add_portfolio_image_for_owner(
            user=self.owner,
            upload=SimpleUploadedFile(
                "lucrare.jpg", rendered.getvalue(), content_type="image/jpeg"
            ),
            caption="Renovare interioară finalizată",
        )
        self.submission, _created = submit_provider_publication_for_review(user=self.owner)
        activate_or_extend_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=0,
            internal_note="Activare pentru testarea solicitărilor.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )
        review_provider_publication(
            submission_id=self.submission.pk,
            reviewer=self.reviewer,
            decision=self.submission.Decision.APPROVED,
            visibility="internal_preview",
            internal_note="Profil verificat pentru testare.",
            provider_feedback="",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        self.query = urlencode(
            {"county": "Iași", "locality": "95079", "category": "constructii"}
        )
        self.url = (
            reverse("services:provider_lead_create", args=(self.profile.public_id,))
            + "?"
            + self.query
        )
        self.valid_payload = {
            "category": "constructii",
            "customer_name": "  Maria   Popescu ",
            "customer_email": "MARIA@example.test",
            "customer_phone": "0712 000 111",
            "project_address": "Copou",
            "description": (
                "Doresc renovarea completă a unei case de aproximativ o sută de metri pătrați."
            ),
            "budget": ProviderLead.Budget.FROM_15000_TO_50000,
            "desired_start": ProviderLead.DesiredStart.WITHIN_MONTH,
            "consent": "on",
            "website": "",
        }
        self.valid_payload["submission_token"] = self.client.get(self.url).context[
            "submission_token"
        ]

    def direct_payload(self, **overrides):
        """Start a distinct direct request from a fresh signed form."""

        page = self.client.get(self.url)
        return {
            **self.valid_payload,
            "submission_token": page.context["submission_token"],
            **overrides,
        }

    def batch_payload(self, **overrides):
        """Build a POST from the same one-time form token a visitor receives."""

        page = self.client.get(reverse("services:provider_lead_batch_create"))
        return {
            **self.valid_payload,
            "county": "Iași",
            "locality": "95079",
            "submission_token": page.context["submission_token"],
            **overrides,
        }

    def test_visible_profile_accepts_and_notifies_for_one_exact_request(self):
        """A valid request is pinned to the viewed snapshot and notifies its owner."""

        response = self.client.post(self.url, self.valid_payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solicitarea a fost trimisă")
        lead = ProviderLead.objects.get()
        self.assertEqual(lead.submission, self.submission)
        self.assertEqual(lead.customer_name, "Maria Popescu")
        self.assertEqual(lead.customer_email, "maria@example.test")
        self.assertEqual(lead.county, "Iași")
        self.assertEqual(lead.siruta_code, "95079")
        self.assertEqual(lead.notification_state, ProviderLead.NotificationState.SENT)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["contact@atelier.example"])
        self.assertIn("Maria Popescu caută o firmă", mail.outbox[0].body)
        self.assertNotIn(lead.customer_email, mail.outbox[0].body)
        self.assertIn(f"focus={lead.public_id}", mail.outbox[0].body)
        self.assertNotIn(f"#lead-{lead.public_id}", mail.outbox[0].body)
        self.assertEqual(mail.outbox[1].to, ["maria@example.test"])
        self.assertIn("/solicitari/", mail.outbox[1].body)
        self.assertNotIn(lead.description, mail.outbox[1].body)
        self.assertIsNotNone(lead.customer_access_digest)
        self.assertIsNotNone(lead.customer_notified_at)
        self.assertNotContains(response, "Deschide solicitarea privată")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_direct_request_replay_creates_no_second_lead_or_notifications(self):
        """The unique direct-request nonce rejects a repeated POST before mail delivery."""

        page = self.client.get(self.url)
        self.assertContains(page, 'name="submission_token"')
        self.assertContains(page, "lead_submit.js")
        payload = self.direct_payload()
        first = self.client.post(self.url, payload)
        self.assertContains(first, "Solicitarea a fost trimisă")
        self.assertEqual(ProviderLead.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

        replay = self.client.post(self.url, payload)
        self.assertContains(replay, "Această solicitare a fost deja trimisă.")
        self.assertEqual(ProviderLead.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotContains(replay, "Deschide solicitarea privată")

        next_request = self.client.post(self.url, self.direct_payload())
        self.assertContains(next_request, "Solicitarea a fost trimisă")
        self.assertEqual(ProviderLead.objects.count(), 2)

    def test_direct_request_token_survives_validation_but_missing_token_is_rejected(self):
        """Correcting an invalid form does not consume its one-time token."""

        payload = self.direct_payload(description="")
        invalid = self.client.post(self.url, payload)
        self.assertEqual(invalid.context["submission_token"], payload["submission_token"])
        self.assertFalse(ProviderLead.objects.exists())

        corrected = self.client.post(
            self.url, {**payload, "description": self.valid_payload["description"]}
        )
        self.assertContains(corrected, "Solicitarea a fost trimisă")

        missing = self.client.post(self.url, self.direct_payload(submission_token=""))
        self.assertContains(missing, "Reîncarcă formularul înainte de a trimite solicitarea.")
        self.assertEqual(ProviderLead.objects.count(), 1)

    def test_failed_customer_email_shows_private_access_only_on_submission_response(self):
        """A mail outage does not strand the anonymous customer who still has this page."""

        with patch(
            "services.provider_leads.send_mail",
            side_effect=[1, RuntimeError("SMTP indisponibil")],
        ):
            response = self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deschide solicitarea privată")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("noarchive", response.headers["X-Robots-Tag"])
        self.assertIsNotNone(lead.customer_notification_failed_at)
        self.assertIsNone(lead.customer_notified_at)
        access_path = re.search(
            r'href="(/solicitari/[^" ]+)"', response.content.decode()
        ).group(1)
        self.assertEqual(self.client.get(access_path).status_code, 200)
        self.assertNotContains(self.client.get(self.url), "Deschide solicitarea privată")

    def test_failed_comparison_email_shows_one_private_access_link(self):
        """A broadcast failure exposes only its parent comparison capability."""

        with patch(
            "services.provider_leads.send_mail",
            side_effect=[1, RuntimeError("SMTP indisponibil")],
        ):
            response = self.client.post(
                reverse("services:provider_lead_batch_create"),
                self.batch_payload(),
            )
        batch = ProviderLeadBatch.objects.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deschide comparația privată")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertIsNotNone(batch.customer_access_digest)
        access_path = re.search(
            r'href="(/solicitari-comparate/[^" ]+)"', response.content.decode()
        ).group(1)
        self.assertEqual(self.client.get(access_path).status_code, 200)
        self.assertNotContains(
            self.client.get(reverse("services:provider_lead_batch_create")),
            "Deschide comparația privată",
        )

    def test_delivery_audit_counts_unresolved_single_request_without_identity(self):
        """The operator sees failed delivery, not customer or project content."""

        self.client.post(self.url, self.valid_payload)
        with CaptureQueriesContext(connection) as queries:
            clean = audit_request_delivery()
        self.assertTrue(clean["valid"])
        self.assertTrue(
            all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)
        )
        clean_output = StringIO()
        call_command("audit_request_delivery", stdout=clean_output)
        self.assertEqual(json.loads(clean_output.getvalue()), clean)
        lead = ProviderLead.objects.get()
        ProviderLead.objects.filter(pk=lead.pk).update(
            notification_state=ProviderLead.NotificationState.FAILED,
            notified_at=None,
            notification_failed_at=timezone.now(),
            customer_notified_at=None,
            customer_notification_failed_at=timezone.now(),
        )
        report = audit_request_delivery()
        self.assertFalse(report["valid"])
        self.assertEqual(report["provider"], {"failed": 1, "pending": 0})
        self.assertEqual(report["customer_single"], {"recoverable": 1, "expired": 0})
        self.assertEqual(report["customer_comparison"], {
            "recoverable": 0, "expired": 0, "mixed": 0,
        })
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_request_delivery", stdout=output)
        self.assertEqual(json.loads(output.getvalue()), report)
        self.assertNotIn(lead.customer_email, output.getvalue())
        self.assertNotIn(lead.description, output.getvalue())

        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_access_expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(audit_request_delivery()["customer_single"], {
            "recoverable": 0, "expired": 1,
        })

    def test_delivery_audit_counts_comparison_once_and_ignores_retained(self):
        """A child failure belongs to one active comparison project."""

        self.client.post(
            reverse("services:provider_lead_batch_create"),
            self.batch_payload(),
        )
        batch = ProviderLeadBatch.objects.get()
        lead = ProviderLead.objects.get(batch=batch)
        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_notified_at=None,
            customer_notification_failed_at=timezone.now(),
        )
        report = audit_request_delivery()
        self.assertEqual(report["customer_comparison"], {
            "recoverable": 1, "expired": 0, "mixed": 0,
        })
        self.assertEqual(report["customer_single"], {"recoverable": 0, "expired": 0})

        ProviderLead.objects.filter(pk=lead.pk).update(retention_applied_at=timezone.now())
        self.assertTrue(audit_request_delivery()["valid"])

    def test_admin_retries_only_failed_provider_notification_with_explicit_permission(self):
        """A failed send is recoverable once, with permission and an audit entry."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        ProviderLead.objects.filter(pk=lead.pk).update(
            notification_state=ProviderLead.NotificationState.FAILED,
            notified_at=None,
            notification_failed_at=timezone.now(),
        )
        mail.outbox.clear()
        retry_url = reverse("admin:services_providerlead_retry_notification", args=(lead.pk,))
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(retry_url).status_code, 403)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="retry_provider_lead_notification")
        )
        self.assertEqual(self.client.get(retry_url).status_code, 403)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_providerlead")
        )
        self.assertContains(self.client.get(retry_url), "posibilitatea unui e-mail duplicat")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.reviewer)
        self.assertEqual(csrf_client.get(retry_url).status_code, 200)
        self.assertEqual(
            csrf_client.post(retry_url, {"acknowledgement": "RETRIMITE"}).status_code,
            403,
        )
        self.assertEqual(self.client.post(retry_url, {}).status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

        with patch("services.provider_leads.send_mail", side_effect=RuntimeError("SMTP indisponibil")):
            self.assertEqual(
                self.client.post(retry_url, {"acknowledgement": "RETRIMITE"}).status_code,
                302,
            )
        lead.refresh_from_db()
        self.assertEqual(lead.notification_state, ProviderLead.NotificationState.FAILED)
        self.assertIsNotNone(lead.notification_failed_at)
        self.assertEqual(len(mail.outbox), 0)

        with patch("services.provider_leads.send_mail", return_value=0):
            self.client.post(retry_url, {"acknowledgement": "RETRIMITE"})
        lead.refresh_from_db()
        self.assertEqual(lead.notification_state, ProviderLead.NotificationState.FAILED)
        self.assertEqual(len(mail.outbox), 0)

        self.assertEqual(
            self.client.post(retry_url, {"acknowledgement": "RETRIMITE"}).status_code,
            302,
        )
        lead.refresh_from_db()
        self.assertEqual(lead.notification_state, ProviderLead.NotificationState.SENT)
        self.assertIsNone(lead.notification_failed_at)
        self.assertIsNotNone(lead.notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"focus={lead.public_id}", mail.outbox[0].body)
        self.assertEqual(
            LogEntry.objects.filter(object_id=str(lead.pk), action_flag=2).count(), 3
        )
        self.client.post(retry_url, {"acknowledgement": "RETRIMITE"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            LogEntry.objects.filter(object_id=str(lead.pk), action_flag=2).count(), 3
        )

    def test_admin_reissues_failed_anonymous_customer_link_only_with_separate_permission(self):
        """Recovery rotates the bearer secret, preserves expiry and never resends success."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        original_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body).group(0)
        original_digest = lead.customer_access_digest
        original_expiry = lead.customer_access_expires_at
        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_notified_at=None, customer_notification_failed_at=timezone.now(),
        )
        mail.outbox.clear()
        retry_url = reverse("admin:services_providerlead_retry_customer_access", args=(lead.pk,))
        self.client.force_login(self.reviewer)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="view_providerlead"))
        self.assertEqual(self.client.get(retry_url).status_code, 403)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="retry_customer_access_notification")
        )
        self.assertContains(self.client.get(retry_url), "Linkul anterior va deveni invalid")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.reviewer)
        self.assertEqual(csrf_client.post(retry_url, {"acknowledgement": "REEMITE"}).status_code, 403)
        self.client.post(retry_url, {})
        self.assertEqual(len(mail.outbox), 0)
        with patch("services.provider_leads.send_mail", return_value=0):
            self.client.post(retry_url, {"acknowledgement": "REEMITE"})
        lead.refresh_from_db()
        self.assertNotEqual(lead.customer_access_digest, original_digest)
        self.assertEqual(lead.customer_access_expires_at, original_expiry)
        self.assertIsNotNone(lead.customer_notification_failed_at)
        self.assertEqual(self.client.get(original_url.removeprefix("http://testserver")).status_code, 404)
        self.client.post(retry_url, {"acknowledgement": "REEMITE"})
        lead.refresh_from_db()
        self.assertIsNotNone(lead.customer_notified_at)
        self.assertIsNone(lead.customer_notification_failed_at)
        self.assertEqual(len(mail.outbox), 1)
        new_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[0].body).group(0)
        self.assertEqual(self.client.get(new_url.removeprefix("http://testserver")).status_code, 200)
        self.client.post(retry_url, {"acknowledgement": "REEMITE"})
        self.assertEqual(len(mail.outbox), 1)

    def test_admin_reissues_failed_anonymous_comparison_link(self):
        """A batch has one rotated parent capability and one customer e-mail."""

        self.client.post(reverse("services:provider_lead_batch_create"), self.batch_payload())
        batch = ProviderLeadBatch.objects.get()
        lead = ProviderLead.objects.get(batch=batch)
        old_url = re.search(r"https?://[^\s]+/solicitari-comparate/[^\s]+", mail.outbox[1].body).group(0)
        old_digest = batch.customer_access_digest
        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_notified_at=None, customer_notification_failed_at=timezone.now(),
        )
        mail.outbox.clear()
        retry_url = reverse("admin:services_providerleadbatch_retry_customer_access", args=(batch.pk,))
        self.client.force_login(self.reviewer)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_providerleadbatch"),
            Permission.objects.get(codename="retry_customer_access_notification"),
        )
        self.assertEqual(self.client.get(retry_url).status_code, 200)
        self.client.post(retry_url, {"acknowledgement": "REEMITE"})
        batch.refresh_from_db()
        lead.refresh_from_db()
        self.assertNotEqual(batch.customer_access_digest, old_digest)
        self.assertIsNotNone(lead.customer_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.client.get(old_url.removeprefix("http://testserver")).status_code, 404)
        new_url = re.search(r"https?://[^\s]+/solicitari-comparate/[^\s]+", mail.outbox[0].body).group(0)
        self.assertEqual(self.client.get(new_url.removeprefix("http://testserver")).status_code, 200)

    def test_customer_link_recovery_rejects_expired_and_account_owned_requests(self):
        """No recovery e-mail may bypass expiry or a logged-in customer's ownership."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_notified_at=None, customer_notification_failed_at=timezone.now(),
            customer_access_expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.client.force_login(self.reviewer)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_providerlead"),
            Permission.objects.get(codename="retry_customer_access_notification"),
        )
        mail.outbox.clear()
        retry_url = reverse("admin:services_providerlead_retry_customer_access", args=(lead.pk,))
        self.assertEqual(self.client.get(retry_url).status_code, 302)
        self.client.post(retry_url, {"acknowledgement": "REEMITE"})
        self.assertEqual(len(mail.outbox), 0)
        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_access_expires_at=timezone.now() + timedelta(days=1),
            customer_account=CustomerAccount.objects.create(
                user=get_user_model().objects.create_user(
                    username="client-recuperare", email="client@example.test", password="test-password",
                ),
                normalized_email="client@example.test", privacy_notice_version="test",
            ),
        )
        self.client.post(retry_url, {"acknowledgement": "REEMITE"})
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_lists_only_recoverable_customer_emails_once_per_project(self):
        """The recovery filter distinguishes a single lead from one broadcast project."""

        self.client.post(self.url, self.valid_payload)
        direct = ProviderLead.objects.get(batch__isnull=True)
        self.client.post(reverse("services:provider_lead_batch_create"), self.batch_payload())
        batch = ProviderLeadBatch.objects.get()
        child = ProviderLead.objects.get(batch=batch)
        ProviderLead.objects.filter(pk__in=(direct.pk, child.pk)).update(
            customer_notified_at=None, customer_notification_failed_at=timezone.now(),
        )
        self.client.force_login(self.reviewer)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_providerlead"),
            Permission.objects.get(codename="view_providerleadbatch"),
        )
        direct_list = self.client.get(reverse("admin:services_providerlead_changelist") + "?customer_access=needs_reissue")
        self.assertEqual(direct_list.status_code, 200)
        self.assertContains(direct_list, "Necesită reemitere")
        self.assertEqual(list(direct_list.context["cl"].queryset.values_list("pk", flat=True)), [direct.pk])
        batch_list = self.client.get(reverse("admin:services_providerleadbatch_changelist") + "?customer_access=needs_reissue")
        self.assertEqual(batch_list.status_code, 200)
        self.assertEqual(list(batch_list.context["cl"].queryset.values_list("pk", flat=True)), [batch.pk])
        ProviderLead.objects.filter(pk=child.pk).update(customer_notification_failed_at=None, customer_notified_at=timezone.now())
        self.assertEqual(
            self.client.get(reverse("admin:services_providerleadbatch_changelist") + "?customer_access=needs_reissue").context["cl"].result_count,
            0,
        )

        # An expired direct link is never confused with a batch child or a retryable link.
        ProviderLead.objects.filter(pk=direct.pk).update(
            customer_access_expires_at=timezone.now() - timedelta(seconds=1),
        )
        expired_direct = self.client.get(reverse("admin:services_providerlead_changelist") + "?customer_access=expired")
        self.assertEqual(list(expired_direct.context["cl"].queryset.values_list("pk", flat=True)), [direct.pk])
        self.assertEqual(
            self.client.get(reverse("admin:services_providerlead_changelist") + "?customer_access=needs_reissue").context["cl"].result_count,
            0,
        )

        # A comparison is listed only while all its active children have failed.
        ProviderLead.objects.filter(pk=child.pk).update(
            customer_notified_at=None, customer_notification_failed_at=timezone.now(),
        )
        ProviderLeadBatch.objects.filter(pk=batch.pk).update(
            customer_access_expires_at=timezone.now() - timedelta(seconds=1),
        )
        expired_batch = self.client.get(reverse("admin:services_providerleadbatch_changelist") + "?customer_access=expired")
        self.assertEqual(list(expired_batch.context["cl"].queryset.values_list("pk", flat=True)), [batch.pk])
        self.assertEqual(
            self.client.get(reverse("admin:services_providerleadbatch_changelist") + "?customer_access=needs_reissue").context["cl"].result_count,
            0,
        )

        # A second pinned recipient with a successful customer-mail state makes
        # this comparison inconsistent, never an eligible expired-link retry.
        ProviderPublicationSubmission.objects.filter(pk=self.submission.pk).update(
            superseded_at=timezone.now(),
            superseded_by=self.reviewer,
            superseded_by_version=2,
        )
        next_submission = ProviderPublicationSubmission.objects.get(pk=self.submission.pk)
        next_submission.pk = None
        next_submission.version = 2
        next_submission.superseded_at = None
        next_submission.superseded_by = None
        next_submission.superseded_by_version = None
        next_submission.save()
        other_child = ProviderLead.objects.get(pk=child.pk)
        other_child.pk = None
        other_child.public_id = uuid4()
        other_child.submission = next_submission
        other_child.customer_notification_failed_at = None
        other_child.customer_notified_at = timezone.now()
        other_child.save()
        mixed_batch = self.client.get(reverse("admin:services_providerleadbatch_changelist") + "?customer_access=mixed")
        self.assertEqual(list(mixed_batch.context["cl"].queryset.values_list("pk", flat=True)), [batch.pk])
        self.assertEqual(
            self.client.get(reverse("admin:services_providerleadbatch_changelist") + "?customer_access=expired").context["cl"].result_count,
            0,
        )
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_provider_lead_insights"),
        )
        report = self.client.get(reverse("admin:services_providerlead_delivery"))
        self.assertContains(report, "?customer_access=mixed")
        self.assertContains(report, "?customer_access=expired")
        self.assertNotContains(report, direct.customer_email)

    def test_customer_account_owns_request_and_returns_without_email_link(self):
        """An authenticated customer sees a submitted request through the portal."""

        self.client.post(
            reverse("services:customer_register"),
            {
                "last_name": "Popescu", "first_name": "Maria",
                "username": "maria-client", "email": "maria-client@example.test",
                "password1": "CasaMea-Sigura-2026!", "password2": "CasaMea-Sigura-2026!",
                "privacy_consent": "on", "website": "",
            },
        )
        response = self.client.post(
            self.url,
            {**self.valid_payload, "customer_name": "Nume fals", "customer_email": "fals@example.test"},
        )

        self.assertEqual(response.status_code, 200)
        lead = ProviderLead.objects.get()
        self.assertEqual(lead.customer_name, "Maria Popescu")
        self.assertEqual(lead.customer_email, "maria-client@example.test")
        self.assertIsNotNone(lead.customer_account)
        self.assertEqual(len(mail.outbox), 1)
        dashboard = self.client.get(reverse("services:customer_dashboard"))
        self.assertContains(dashboard, "Atelier Test Aproape")
        detail = self.client.get(
            reverse("services:customer_lead_detail", args=(lead.public_id,))
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Solicitarea mea")

    def test_account_customer_notifications_link_to_owned_workspaces(self):
        """Offer and message e-mails use login-guarded project routes, not capabilities."""

        self.client.post(reverse("services:customer_register"), {
            "last_name": "Popescu", "first_name": "Maria", "username": "maria-linkuri",
            "email": "maria-linkuri@example.test", "password1": "CasaMea-Sigura-2026!",
            "password2": "CasaMea-Sigura-2026!", "privacy_consent": "on", "website": "",
        })
        account = CustomerAccount.objects.get()
        self.client.post(self.url, self.valid_payload)
        direct_lead = ProviderLead.objects.get(batch__isnull=True)
        self.client.post(reverse("services:provider_lead_batch_create"), self.batch_payload())
        batch = ProviderLeadBatch.objects.get()
        batch_lead = ProviderLead.objects.get(batch=batch)
        self.assertEqual(len(mail.outbox), 2)

        self.client.force_login(self.owner)
        self.client.post(reverse("services:provider_leads"), {
            "lead_id": direct_lead.pk, "action": "quote",
            f"quote-{direct_lead.pk}-amount_ron": "2500.00",
            f"quote-{direct_lead.pk}-item_1_description": "Reparația instalației electrice",
            f"quote-{direct_lead.pk}-item_1_quantity": "1",
            f"quote-{direct_lead.pk}-item_1_unit": "lucrare",
            f"quote-{direct_lead.pk}-item_1_unit_price_ron": "2500.00",
            f"quote-{direct_lead.pk}-estimated_duration": "Două zile",
            f"quote-{direct_lead.pk}-valid_until": (
                timezone.localdate() + timedelta(days=14)
            ).isoformat(),
            f"quote-{direct_lead.pk}-summary": "Reparația completă a instalației electrice.",
        })
        direct_path = reverse("services:customer_lead_detail", args=(direct_lead.public_id,))
        self.assertIn(f"http://testserver{direct_path}", mail.outbox[-1].body)
        self.assertIn("Actualizare în solicitarea", mail.outbox[-1].subject)
        self.assertNotIn("2500", mail.outbox[-1].body)
        self.assertNotIn(direct_lead.description, mail.outbox[-1].body)

        self.client.post(reverse("services:provider_leads"), {
            "lead_id": batch_lead.pk, "action": "message",
            f"message-{batch_lead.pk}-body": "Putem discuta despre lucrare mâine.",
        })
        batch_path = reverse("services:customer_batch_detail", args=(batch.public_id,))
        self.assertIn(f"http://testserver{batch_path}", mail.outbox[-1].body)
        self.assertNotIn("Putem discuta", mail.outbox[-1].body)
        self.assertNotIn("/solicitari-comparate/", mail.outbox[-1].body)

        self.client.logout()
        anonymous = self.client.get(direct_path)
        self.assertRedirects(
            anonymous,
            reverse("services:customer_login") + f"?next={direct_path.replace('/', '%2F')}",
            fetch_redirect_response=False,
        )
        other_user = get_user_model().objects.create_user(
            username="alt-client-link", email="alt-link@example.test", password="Alta-Parola-Sigura-2026!",
        )
        CustomerAccount.objects.create(
            user=other_user, normalized_email="alt-link@example.test", privacy_notice_version="test",
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(direct_path).status_code, 404)
        self.assertEqual(self.client.get(batch_path).status_code, 404)
        self.client.force_login(account.user)
        self.assertEqual(self.client.get(direct_path).status_code, 200)
        self.assertEqual(self.client.get(batch_path).status_code, 200)

    def test_customer_dashboard_pages_owned_requests_without_loading_other_accounts(self):
        """Both request types stay bounded and retain their independent page positions."""

        self.client.post(reverse("services:customer_register"), {
            "last_name": "Popescu", "first_name": "Maria", "username": "maria-pagini",
            "email": "maria-pagini@example.test", "password1": "CasaMea-Sigura-2026!",
            "password2": "CasaMea-Sigura-2026!", "privacy_consent": "on", "website": "",
        })
        account = CustomerAccount.objects.get()
        for index in range(12):
            batch = ProviderLeadBatch.objects.create(
                category="constructii", county="Iași", siruta_code="95079",
                visitor_session_digest=uuid4().hex, privacy_notice_version="test",
                customer_access_digest=uuid4().hex * 2,
                customer_access_expires_at=timezone.now() + timedelta(days=30),
                customer_account=account,
            )
            for parent in (None, batch):
                ProviderLead.objects.create(
                    submission=self.submission, batch=parent, category="constructii",
                    county="Iași", siruta_code="95079", customer_name="Maria Popescu",
                    customer_email="maria-pagini@example.test", customer_phone="0712000111",
                    description=f"Proiectul {index}", desired_start=ProviderLead.DesiredStart.FLEXIBLE,
                    visitor_session_digest=uuid4().hex, privacy_notice_version="test",
                    customer_access_digest=(uuid4().hex * 2 if parent is None else None),
                    customer_access_expires_at=(timezone.now() + timedelta(days=30) if parent is None else None),
                    customer_account=account,
                )

        other_user = get_user_model().objects.create_user(
            username="alt-client", email="alt-client@example.test", password="Alta-Parola-Sigura-2026!",
        )
        other_account = CustomerAccount.objects.create(
            user=other_user, normalized_email="alt-client@example.test", privacy_notice_version="test",
        )
        ProviderLead.objects.create(
            submission=self.submission, category="constructii", county="Iași", siruta_code="95079",
            customer_name="Alt Client", customer_email="alt-client@example.test",
            customer_phone="0712000222", description="Proiectul altui client",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE, visitor_session_digest=uuid4().hex,
            privacy_notice_version="test", customer_access_digest=uuid4().hex * 2,
            customer_access_expires_at=timezone.now() + timedelta(days=30),
            customer_account=other_account,
        )
        ProviderLeadBatch.objects.create(
            category="constructii", county="Iași", siruta_code="95079",
            visitor_session_digest=uuid4().hex, privacy_notice_version="test",
            customer_access_digest=uuid4().hex * 2,
            customer_access_expires_at=timezone.now() + timedelta(days=30),
            customer_account=account,
        )

        with CaptureQueriesContext(connection) as queries:
            first = self.client.get(reverse("services:customer_dashboard"))
        self.assertLessEqual(len(queries), 12)
        self.assertEqual(first.context["request_count"], 24)
        self.assertNotContains(first, "Alt Client")
        self.assertEqual(len(first.context["batch_cards"]), 10)
        self.assertEqual(len(first.context["standalone_cards"]), 10)
        second = self.client.get(reverse("services:customer_dashboard") + "?comparisons_page=2&requests_page=2")
        self.assertEqual(len(second.context["batch_cards"]), 2)
        self.assertEqual(len(second.context["standalone_cards"]), 2)
        self.assertContains(second, "comparisons_page=1&amp;requests_page=2")
        self.assertContains(second, "requests_page=1&amp;comparisons_page=2")
        empty_offers = self.client.get(reverse("services:customer_dashboard") + "?view=offers")
        self.assertEqual(empty_offers.context["request_count"], 0)
        self.assertContains(empty_offers, "Nu ai oferte valabile de evaluat acum.")
        self.assertNotContains(empty_offers, "Primul proiect începe cu o căutare locală.")
        self.assertEqual(
            self.client.get(reverse("services:customer_dashboard") + "?view=invalid").context["request_count"],
            24,
        )
        for batched in (False, True):
            for lead in ProviderLead.objects.filter(
                customer_account=account, batch__isnull=not batched,
            ).order_by("pk")[:11]:
                lead.status = ProviderLead.Status.QUOTE_SENT
                lead.save(update_fields=["status"])
                ProviderQuote.objects.create(
                    lead=lead, revision=1, amount_ron=100, summary="Ofertă de test",
                    estimated_duration="O zi", valid_until=timezone.localdate() + timedelta(days=7),
                    sent_by=self.owner,
                )
        filtered = self.client.get(reverse("services:customer_dashboard") + "?view=offers")
        self.assertEqual(filtered.context["request_count"], 22)
        self.assertEqual(len(filtered.context["batch_cards"]), 10)
        self.assertEqual(len(filtered.context["standalone_cards"]), 10)
        self.assertContains(filtered, "view=offers#comparisons")
        self.assertContains(filtered, "view=offers#requests")
        filtered_second = self.client.get(
            reverse("services:customer_dashboard") + "?view=offers&comparisons_page=2&requests_page=2"
        )
        self.assertEqual(len(filtered_second.context["batch_cards"]), 1)
        self.assertEqual(len(filtered_second.context["standalone_cards"]), 1)
        with translation.override("en"):
            english = self.client.get(reverse("services:customer_dashboard"))
        self.assertContains(english, "Requests to multiple providers")
        self.assertContains(english, "Page 1 of 2")
        self.assertContains(english, "Offers to review")
        self.assertEqual(
            self.client.get(reverse("services:customer_dashboard") + "?comparisons_page=invalid").status_code,
            200,
        )

    def test_customer_dashboard_prioritizes_valid_offers_and_provider_activity(self):
        """Only live offers demand a response; provider activity never means unread."""

        self.client.post(reverse("services:customer_register"), {
            "last_name": "Popescu", "first_name": "Maria", "username": "maria-prioritati",
            "email": "maria-prioritati@example.test", "password1": "CasaMea-Sigura-2026!",
            "password2": "CasaMea-Sigura-2026!", "privacy_consent": "on", "website": "",
        })
        account = CustomerAccount.objects.get()
        leads = []
        for index in range(3):
            leads.append(ProviderLead.objects.create(
                submission=self.submission, category="constructii", county="Iași",
                siruta_code="95079", customer_name="Maria Popescu",
                customer_email="maria-prioritati@example.test", customer_phone="0712000111",
                description=f"Proiect prioritar {index}",
                desired_start=ProviderLead.DesiredStart.FLEXIBLE,
                visitor_session_digest=uuid4().hex, privacy_notice_version="test",
                customer_access_digest=uuid4().hex * 2,
                customer_access_expires_at=timezone.now() + timedelta(days=30),
                customer_account=account,
            ))
        ProviderLead.objects.filter(pk__in=[lead.pk for lead in leads]).update(
            created_at=timezone.now() - timedelta(days=3),
        )
        for lead, validity in ((leads[0], -1), (leads[1], 7)):
            lead.status = ProviderLead.Status.QUOTE_SENT
            lead.save(update_fields=["status"])
            ProviderQuote.objects.create(
                lead=lead, revision=1, amount_ron=100, summary="Lucrare completă",
                estimated_duration="O zi", valid_until=timezone.localdate() + timedelta(days=validity),
                sent_by=self.owner,
            )
        ProviderLeadMessage.objects.create(
            lead=leads[2], sender_role=ProviderLeadMessage.SenderRole.PROVIDER,
            actor=self.owner, body="Pot veni mâine pentru măsurători.",
        )
        batch = ProviderLeadBatch.objects.create(
            category="constructii", county="Iași", siruta_code="95079",
            visitor_session_digest=uuid4().hex, privacy_notice_version="test",
            customer_access_digest=uuid4().hex * 2,
            customer_access_expires_at=timezone.now() + timedelta(days=30),
            customer_account=account,
        )
        batch_lead = ProviderLead.objects.create(
            submission=self.submission, batch=batch, category="constructii",
            county="Iași", siruta_code="95079", customer_name="Maria Popescu",
            customer_email="maria-prioritati@example.test", customer_phone="0712000111",
            description="Proiect comparat", desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            visitor_session_digest=uuid4().hex, privacy_notice_version="test",
            customer_account=account, status=ProviderLead.Status.QUOTE_SENT,
        )
        ProviderQuote.objects.create(
            lead=batch_lead, revision=1, amount_ron=200, summary="Comparație completă",
            estimated_duration="Două zile", valid_until=timezone.localdate() + timedelta(days=7),
            sent_by=self.owner,
        )

        response = self.client.get(reverse("services:customer_dashboard"))
        cards = response.context["standalone_cards"]
        self.assertEqual([card["lead"].pk for card in cards], [leads[1].pk, leads[2].pk, leads[0].pk])
        self.assertEqual([card["needs_response"] for card in cards], [True, False, False])
        self.assertContains(response, "Ofertă valabilă — răspunde", count=1)
        self.assertEqual(response.context["batch_cards"][0]["valid_offer_count"], 1)
        self.assertContains(response, "1 ofertă valabilă așteaptă răspuns")
        self.assertNotContains(response, "necitit")
        filtered = self.client.get(reverse("services:customer_dashboard") + "?view=offers")
        self.assertEqual(filtered.context["request_count"], 2)
        self.assertEqual(len(filtered.context["batch_cards"]), 1)
        self.assertEqual([card["lead"].pk for card in filtered.context["standalone_cards"]], [leads[1].pk])
        self.assertContains(filtered, 'aria-current="page">Oferte de evaluat</a>')
        with translation.override("en"):
            english = self.client.get(reverse("services:customer_dashboard"))
        self.assertContains(english, "Valid offer — respond")
        self.assertContains(english, "1 valid offer awaits your response")

    def test_general_request_creates_one_private_batch_and_comparison_link(self):
        """One project creates snapshot-bound copies and one customer capability."""

        payload = self.batch_payload()
        response = self.client.post(
            reverse("services:provider_lead_batch_create"), payload
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solicitarea a ajuns la o firmă")
        self.assertNotContains(response, "Deschide comparația privată")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        batch = ProviderLeadBatch.objects.get()
        lead = ProviderLead.objects.get(batch=batch)
        self.assertIsNone(lead.customer_access_digest)
        self.assertIsNone(lead.customer_access_expires_at)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["contact@atelier.example"])
        self.assertEqual(mail.outbox[1].to, ["maria@example.test"])
        access_url = re.search(
            r"https?://[^\s]+/solicitari-comparate/[^\s]+", mail.outbox[1].body
        ).group(0)
        access_path = access_url.removeprefix("http://testserver")
        private_page = self.client.get(access_path)
        self.assertEqual(private_page.status_code, 200)
        self.assertContains(private_page, "Compară răspunsurile firmelor")
        self.assertContains(private_page, "Atelier Test Aproape")
        self.assertEqual(private_page.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            self.client.get(
                reverse(
                    "services:provider_lead_batch_customer",
                    args=(batch.public_id, "token-incorect"),
                )
            ).status_code,
            404,
        )

        message = self.client.post(
            access_path,
            {
                "action": "message",
                "lead_id": str(lead.public_id),
                f"message-{lead.pk}-body": "Puteți include și materialele în ofertă?",
            },
        )
        self.assertRedirects(message, access_path)
        self.assertEqual(
            ProviderLeadMessage.objects.get().sender_role,
            ProviderLeadMessage.SenderRole.CUSTOMER,
        )

    def test_batch_customer_can_confirm_only_its_provider_visit(self):
        """The comparison capability answers the selected provider's slot privately."""

        self.client.post(reverse("services:provider_lead_batch_create"), self.batch_payload())
        lead = ProviderLead.objects.get(batch__isnull=False)
        access_url = re.search(
            r"https?://[^\s]+/solicitari-comparate/[^\s]+", mail.outbox[1].body
        ).group(0)
        access_path = access_url.removeprefix("http://testserver")
        proposal = propose_provider_visit(
            user=self.owner, lead_id=lead.pk,
            starts_at=timezone.now() + timedelta(days=2), note="La adresa proiectului",
        )
        page = self.client.get(access_path)
        self.assertContains(page, "Confirmă vizita")
        self.assertContains(page, "La adresa proiectului")
        reply = self.client.post(access_path, {
            "lead_id": str(lead.public_id), "action": "visit_declined",
            "proposal_id": proposal.pk,
        })
        self.assertRedirects(reply, access_path)
        proposal.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(proposal.status, ProviderVisitProposal.Status.DECLINED)
        self.assertEqual(lead.status, ProviderLead.Status.CONTACTED)

    def test_batch_customer_can_cancel_confirmed_visit(self):
        """The batch workspace cancels only the selected provider's accepted slot."""

        self.client.post(reverse("services:provider_lead_batch_create"), self.batch_payload())
        lead = ProviderLead.objects.get(batch__isnull=False)
        access_url = re.search(
            r"https?://[^\s]+/solicitari-comparate/[^\s]+", mail.outbox[1].body
        ).group(0)
        access_path = access_url.removeprefix("http://testserver")
        proposal = propose_provider_visit(
            user=self.owner, lead_id=lead.pk,
            starts_at=timezone.now() + timedelta(days=2), note="La adresa proiectului",
        )
        accepted = self.client.post(access_path, {
            "lead_id": str(lead.public_id), "action": "visit_accepted", "proposal_id": proposal.pk,
        })
        self.assertRedirects(accepted, access_path)
        self.assertContains(self.client.get(access_path), "Anulează vizita")
        cancelled = self.client.post(access_path, {
            "lead_id": str(lead.public_id), "action": "visit_cancel", "proposal_id": proposal.pk,
        })
        self.assertRedirects(cancelled, access_path)
        proposal.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(proposal.status, ProviderVisitProposal.Status.CANCELLED)
        self.assertEqual(proposal.cancelled_by, ProviderVisitProposal.CancelledBy.CUSTOMER)
        self.assertEqual(lead.status, ProviderLead.Status.CONTACTED)

    def test_batch_quote_acceptance_opens_one_work_order(self):
        """Accepting a comparison offer opens work only for the selected firm."""

        self.client.post(reverse("services:provider_lead_batch_create"), self.batch_payload())
        lead = ProviderLead.objects.get(batch__isnull=False)
        access_url = re.search(
            r"https?://[^\s]+/solicitari-comparate/[^\s]+", mail.outbox[1].body
        ).group(0)
        access_path = access_url.removeprefix("http://testserver")
        quote = send_provider_quote(
            user=self.owner, lead_id=lead.pk, amount_ron=1200,
            summary="Montajul instalației potrivit descrierii transmise de client.",
            estimated_duration="O zi", valid_until=timezone.localdate() + timedelta(days=10),
        )
        response = self.client.post(access_path, {
            "lead_id": str(lead.public_id), "action": "accepted", "quote_id": quote.pk,
        })
        self.assertRedirects(response, access_path)
        order = ProviderWorkOrder.objects.get(lead=lead)
        self.assertEqual(order.accepted_quote, quote)
        self.assertContains(self.client.get(access_path), "Lucrarea a fost deschisă")
        self.assertEqual(
            self.client.post(access_path, {
                "lead_id": str(lead.public_id), "action": "accepted", "quote_id": quote.pk,
            }).status_code, 200,
        )
        self.assertEqual(ProviderWorkOrder.objects.filter(lead=lead).count(), 1)

    def test_general_request_replay_creates_no_second_project_or_notifications(self):
        """A repeated POST with one issued token cannot duplicate the project."""

        url = reverse("services:provider_lead_batch_create")
        payload = self.batch_payload()
        first = self.client.post(url, payload)
        self.assertContains(first, "Solicitarea a ajuns la o firmă")
        self.assertEqual(ProviderLeadBatch.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

        replay = self.client.post(url, payload)
        self.assertContains(replay, "Această solicitare a fost deja trimisă.")
        self.assertEqual(ProviderLeadBatch.objects.count(), 1)
        self.assertEqual(ProviderLead.objects.filter(batch__isnull=False).count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotContains(replay, "Deschide comparația privată")

        # A deliberate new visit issues a new token and remains within the ordinary limit.
        next_request = self.client.post(url, self.batch_payload())
        self.assertContains(next_request, "Solicitarea a ajuns la o firmă")
        self.assertEqual(ProviderLeadBatch.objects.count(), 2)

    def test_general_request_rejects_missing_token_but_retains_valid_token_after_errors(self):
        """An invalid form can be corrected without issuing a second token."""

        url = reverse("services:provider_lead_batch_create")
        payload = self.batch_payload(description="")
        invalid = self.client.post(url, payload)
        self.assertEqual(invalid.context["submission_token"], payload["submission_token"])
        self.assertFalse(ProviderLeadBatch.objects.exists())

        corrected = self.client.post(url, {**payload, "description": self.valid_payload["description"]})
        self.assertContains(corrected, "Solicitarea a ajuns la o firmă")

        missing = self.client.post(url, self.batch_payload(submission_token=""))
        self.assertContains(missing, "Reîncarcă formularul înainte de a trimite solicitarea.")
        self.assertEqual(ProviderLeadBatch.objects.count(), 1)
        tampered = self.client.post(url, self.batch_payload(submission_token="invalid"))
        self.assertContains(tampered, "Reîncarcă formularul înainte de a trimite solicitarea.")
        self.assertEqual(ProviderLeadBatch.objects.count(), 1)

    def test_general_request_batch_accepts_every_eligible_provider(self):
        """A paid-provider broadcast has no arbitrary three-recipient cap."""

        submissions = tuple(
            SimpleNamespace(pk=index, profile_id=index, public_id=uuid4())
            for index in range(1, 9)
        )
        created_leads = tuple(SimpleNamespace(pk=index) for index in range(1, 9))
        with patch(
            "services.provider_leads.create_provider_lead",
            side_effect=((lead, "") for lead in created_leads),
        ) as create_lead:
            batch, _token, leads = create_provider_lead_batch(
                submissions=submissions,
                category="constructii",
                county="Iași",
                siruta_code="95079",
                customer_name="Maria Popescu",
                customer_email="maria@example.test",
                customer_phone="0712 000 111",
                project_address="Copou",
                description="Renovarea completă a unei locuințe din municipiul Iași.",
                budget=ProviderLead.Budget.FROM_15000_TO_50000,
                desired_start=ProviderLead.DesiredStart.WITHIN_MONTH,
                session_key="broadcast-session",
                submission_nonce="direct-broadcast-test",
            )

        self.assertIsNotNone(batch.pk)
        self.assertEqual(leads, created_leads)
        self.assertEqual(create_lead.call_count, 8)

    def test_customer_account_owns_general_request_without_capability_email(self):
        """A signed-in customer owns both the batch and its provider copies."""

        self.client.post(
            reverse("services:customer_register"),
            {
                "last_name": "Popescu",
                "first_name": "Maria",
                "username": "maria-proiect",
                "email": "maria-proiect@example.test",
                "password1": "CasaMea-Sigura-2026!",
                "password2": "CasaMea-Sigura-2026!",
                "privacy_consent": "on",
                "website": "",
            },
        )
        response = self.client.post(
            reverse("services:provider_lead_batch_create"),
            self.batch_payload(customer_name="Nume fals", customer_email="fals@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        batch = ProviderLeadBatch.objects.get()
        lead = ProviderLead.objects.get(batch=batch)
        self.assertIsNotNone(batch.customer_account)
        self.assertEqual(lead.customer_account, batch.customer_account)
        self.assertEqual(lead.customer_name, "Maria Popescu")
        self.assertEqual(lead.customer_email, "maria-proiect@example.test")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"focus={lead.public_id}", mail.outbox[0].body)
        self.assertNotIn(str(batch.public_id), mail.outbox[0].body)
        dashboard = self.client.get(reverse("services:customer_dashboard"))
        self.assertContains(dashboard, "Cerere trimisă mai multor firme")
        detail = self.client.get(
            reverse("services:customer_batch_detail", args=(batch.public_id,))
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Compară răspunsurile firmelor")

    def test_general_request_requires_exact_locality_and_service(self):
        """County-only discovery stays broad, but private dispatch never guesses scope."""

        payload = self.batch_payload(locality="")
        response = self.client.post(
            reverse("services:provider_lead_batch_create"), payload
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Alege localitatea în care va fi realizată lucrarea."
        )
        self.assertFalse(ProviderLeadBatch.objects.exists())

    def test_general_request_exposes_the_shared_locality_loader_contract(self):
        """The batch form must use the data attributes consumed by locations.js."""

        response = self.client.get(reverse("services:provider_lead_batch_create"))

        self.assertContains(response, 'data-locations-url="/api/localitati/"')
        self.assertContains(response, 'data-locality-all="Alege localitatea"')
        self.assertContains(response, 'data-locality-none="Nu există localități"')
        self.assertContains(
            response, 'data-locality-county-first="Alege întâi județul"'
        )
        self.assertContains(response, 'data-submitting-label="Se trimite solicitarea…"')
        self.assertContains(response, "lead_submit.js")

    def test_general_request_previews_only_exact_eligible_recipient_count(self):
        """The preflight count uses the same public visibility reader as dispatch."""

        scope = {"county": "Iași", "locality": "95079", "category": "constructii"}
        page = self.client.get(reverse("services:provider_lead_batch_create"), scope)
        self.assertContains(page, "O firmă poate primi această solicitare.")
        self.assertContains(page, 'data-availability-url="/solicita-oferte/disponibilitate/"')
        self.assertContains(page, "lead_availability.js")

        url = reverse("services:provider_lead_batch_availability")
        available = self.client.get(url, scope)
        self.assertEqual(available.status_code, 200)
        self.assertEqual(available.json(), {"count": 1})
        self.assertIn("no-store", available.headers["Cache-Control"])
        self.assertEqual(self.client.get(url, {**scope, "category": "electricieni"}).json(), {"count": 0})
        self.assertEqual(self.client.get(url, {**scope, "locality": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(url, {**scope, "category": ""}).status_code, 400)
        self.assertEqual(self.client.post(url, scope).status_code, 405)
        self.assertFalse(ProviderLeadBatch.objects.exists())

        with patch("services.views.published_provider_search", return_value=tuple(range(8))):
            self.assertEqual(self.client.get(url, scope).json(), {"count": 8})
            self.assertContains(
                self.client.get(reverse("services:provider_lead_batch_create"), scope),
                "8 firme pot primi această solicitare.",
            )

        with translation.override("en"):
            english = self.client.get(reverse("services:provider_lead_batch_create"), scope)
        self.assertContains(english, "One provider can receive this request.")
        self.assertContains(english, "This count is an estimate")

    def test_operational_insights_count_one_batch_as_one_project(self):
        """Aggregate demand without multiplying one project by its recipients."""

        self.client.post(self.url, self.valid_payload)
        batch_payload = self.batch_payload()
        self.client.post(
            reverse("services:provider_lead_batch_create"),
            batch_payload,
        )
        direct_lead = ProviderLead.objects.get(batch__isnull=True)
        batch_lead = ProviderLead.objects.get(batch__isnull=False)
        ProviderQuote.objects.create(
            lead=direct_lead,
            revision=1,
            amount_ron="12500.00",
            summary="Oferta completă pentru lucrarea descrisă.",
            estimated_duration="Patru săptămâni",
            valid_until=timezone.localdate() + timedelta(days=7),
            status=ProviderQuote.Status.ACCEPTED,
            sent_by=self.owner,
            responded_at=timezone.now(),
        )
        ProviderQuote.objects.create(
            lead=batch_lead,
            revision=1,
            amount_ron="13500.00",
            summary="Oferta comparabilă pentru aceeași lucrare.",
            estimated_duration="Cinci săptămâni",
            valid_until=timezone.localdate() + timedelta(days=7),
            sent_by=self.owner,
        )

        with self.assertNumQueries(1):
            insights = provider_lead_insights(calculated_at=timezone.now() + timedelta(seconds=1))

        self.assertEqual(insights.total_projects, 2)
        self.assertEqual(insights.provider_deliveries, 2)
        self.assertEqual(insights.provider_responses, 2)
        self.assertEqual(insights.quoted_projects, 2)
        self.assertEqual(insights.awarded_projects, 1)
        area = insights.demand_areas[0]
        self.assertEqual((area.county, area.locality), ("Iași", "Iași"))
        self.assertEqual(area.average_recipients, 1.0)

        report = pilot_readiness(county="Iași", category="constructii")
        self.assertEqual(report.projects, 2)
        self.assertEqual(report.quoted_projects, 2)
        self.assertEqual(report.awarded_projects, 1)
        self.assertIsNotNone(report.first_quote_hours)

    def test_lead_insights_admin_is_get_only_and_separately_permissioned(self):
        """Raw-lead viewers still need the dedicated aggregate permission."""

        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_providerlead")
        )
        self.client.force_login(self.reviewer)
        url = reverse("admin:services_providerlead_insights")
        self.assertEqual(self.client.get(url).status_code, 403)

        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_provider_lead_insights")
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cerere și acoperire")
        self.assertContains(response, "Sunt măsurate numai solicitările trimise")
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_delivery_admin_is_get_only_permissioned_and_identity_free(self):
        """Staff see the same aggregate audit, with paths to existing recovery lists."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        ProviderLead.objects.filter(pk=lead.pk).update(
            notification_state=ProviderLead.NotificationState.FAILED,
            notified_at=None,
            notification_failed_at=timezone.now(),
            customer_notified_at=None,
            customer_notification_failed_at=timezone.now(),
        )
        url = reverse("admin:services_providerlead_delivery")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="view_providerlead"))
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_provider_lead_insights")
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["delivery"], audit_request_delivery())
        self.assertContains(response, "Sunt livrări de verificat")
        self.assertContains(response, "?customer_access=needs_reissue")
        self.assertContains(response, "?provider_delivery=failed")
        self.assertNotContains(response, lead.customer_name)
        self.assertNotContains(response, lead.customer_email)
        self.assertNotContains(response, lead.description)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(self.client.post(url).status_code, 405)

        lead_list = reverse("admin:services_providerlead_changelist")
        self.assertEqual(
            self.client.get(f"{lead_list}?provider_delivery=failed").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"{lead_list}?customer_access=needs_reissue").status_code,
            200,
        )

        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_access_expires_at=timezone.now() - timedelta(seconds=1),
        )
        expired_report = self.client.get(url)
        self.assertContains(expired_report, "?customer_access=expired")
        self.assertNotContains(expired_report, "?customer_access=needs_reissue")
        self.assertNotContains(expired_report, lead.customer_email)

        list_page = self.client.get(lead_list)
        self.assertContains(list_page, "Livrarea notificărilor")

    def test_provider_delivery_filters_exclude_retained_requests(self):
        """Each drill-down has the same active copy count as the delivery report."""

        for _ in range(3):
            self.assertEqual(self.client.post(self.url, self.direct_payload()).status_code, 200)
        active_failed, active_pending, retained_failed = list(
            ProviderLead.objects.order_by("pk")
        )
        now = timezone.now()
        ProviderLead.objects.filter(pk__in=(active_failed.pk, retained_failed.pk)).update(
            notification_state=ProviderLead.NotificationState.FAILED,
            notified_at=None,
            notification_failed_at=now,
        )
        ProviderLead.objects.filter(pk=active_pending.pk).update(
            notification_state=ProviderLead.NotificationState.PENDING,
            notified_at=None,
            notification_failed_at=None,
        )
        ProviderLead.objects.filter(pk=retained_failed.pk).update(retention_applied_at=now)
        self.assertEqual(audit_request_delivery()["provider"], {"failed": 1, "pending": 1})

        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_providerlead"),
            Permission.objects.get(codename="view_provider_lead_insights"),
        )
        self.client.force_login(self.reviewer)
        lead_list = reverse("admin:services_providerlead_changelist")
        for state, expected_pk in (("failed", active_failed.pk), ("pending", active_pending.pk)):
            response = self.client.get(f"{lead_list}?provider_delivery={state}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(list(response.context["cl"].queryset.values_list("pk", flat=True)), [expected_pk])

        report = self.client.get(reverse("admin:services_providerlead_delivery"))
        self.assertContains(report, "?provider_delivery=failed")
        self.assertContains(report, "?provider_delivery=pending")
        self.assertNotContains(report, active_failed.customer_email)

    def test_pilot_report_separates_preview_supply_from_public_supply(self):
        """Demo profiles and ONRC listings never count as launch-ready providers."""

        self.client.post(self.url, self.valid_payload)
        report = pilot_readiness(county="Iași", category="constructii")
        self.assertFalse(report.source_public)
        self.assertEqual(report.public_providers, 0)
        self.assertEqual(report.preview_providers, 1)
        self.assertEqual(report.projects, 1)
        self.assertEqual(report.quoted_projects, 0)
        self.assertEqual(report.awarded_projects, 0)
        self.assertIsNone(report.first_quote_hours)
        self.assertEqual(report.unanswered_areas, 1)
        self.assertEqual(report.areas[0].siruta_code, "95079")
        self.assertEqual(report.areas[0].preview_providers, 1)

        other_service = pilot_readiness(county="Iași", category="instalatii")
        self.assertEqual(other_service.projects, 0)
        self.assertEqual(other_service.preview_providers, 0)

    def test_pilot_admin_is_get_only_permissioned_and_identity_free(self):
        """Only authorized staff see aggregates; filters cannot escape known scopes."""

        self.client.post(self.url, self.valid_payload)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="view_providerlead"))
        self.client.force_login(self.reviewer)
        url = reverse("admin:services_providerlead_pilot")
        self.assertEqual(self.client.get(url).status_code, 403)

        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="view_provider_lead_insights")
        )
        response = self.client.get(url, {"county": "Iași", "category": "constructii"})
        self.assertContains(response, "Pregătirea lansării locale")
        self.assertContains(response, "Ce se întâmplă după trimitere")
        self.assertContains(response, "Nu este pregătit pentru lansare publică")
        self.assertNotContains(response, "maria@example.test")
        self.assertNotContains(response, "Maria Popescu")
        self.assertEqual(self.client.post(url).status_code, 405)

        invalid = self.client.get(url, {"county": "inventat", "category": "inventat"})
        self.assertEqual(invalid.context["pilot"].county, "Iași")
        self.assertEqual(invalid.context["pilot"].category, "constructii")

    def test_intake_rejects_honeypot_and_limits_one_session(self):
        """Basic automated abuse controls do not create extra private records."""

        spam = {**self.valid_payload, "website": "https://spam.example"}
        response = self.client.post(self.url, spam)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProviderLead.objects.count(), 0)

        for index in range(3):
            payload = self.direct_payload(customer_email=f"maria{index}@example.test")
            self.client.post(self.url, payload)
        limited = self.client.post(self.url, self.direct_payload())
        self.assertContains(limited, "Reîncearcă mâine")
        self.assertEqual(ProviderLead.objects.count(), 3)

    def test_wrong_service_or_locality_cannot_target_the_snapshot(self):
        """Tampered search context fails closed before collecting customer data."""

        wrong_query = urlencode(
            {"county": "Iași", "locality": "95079", "category": "instalatii"}
        )
        wrong_url = (
            reverse("services:provider_lead_create", args=(self.profile.public_id,))
            + "?"
            + wrong_query
        )
        response = self.client.post(wrong_url, self.valid_payload)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ProviderLead.objects.count(), 0)

    def test_only_the_owner_can_read_customer_identity(self):
        """Anonymous users and a second provider cannot read the private inbox."""

        self.client.post(self.url, self.valid_payload)
        inbox_url = reverse("services:provider_leads")
        anonymous = self.client.get(inbox_url)
        self.assertEqual(anonymous.status_code, 302)

        stranger = get_user_model().objects.create_user(
            username="stranger-provider", email="stranger@example.test"
        )
        self.client.force_login(stranger)
        forbidden = self.client.get(inbox_url)
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.owner)
        owned = self.client.get(inbox_url)
        self.assertEqual(owned.status_code, 200)
        self.assertEqual(owned.context["dashboard_section"], "requests")
        self.assertContains(owned, "Activitatea firmei")
        self.assertContains(owned, "Solicitări primite")
        self.assertContains(owned, 'href="?view=requests" aria-current="page"')
        self.assertContains(owned, '<details class="provider-lead-workspace">')
        self.assertContains(owned, "Maria Popescu")
        self.assertContains(owned, "maria@example.test")

        performance = self.client.get(
            inbox_url, {"view": "performance", "period": "7"}
        )
        self.assertEqual(performance.context["dashboard_section"], "performance")
        self.assertContains(performance, "Performanța profilului")
        self.assertNotContains(performance, "Maria Popescu")

    def test_owner_command_prepares_quote_without_sending_it(self):
        """A parsed instruction is a private, editable draft, never a quote mutation."""

        self.client.post(self.url, self.valid_payload)
        self.client.force_login(self.owner)
        notifications_before = len(mail.outbox)
        response = self.client.post(
            reverse("services:provider_leads"),
            {
                "action": "prepare_quote",
                "command": "Creează ofertă pentru dna Popescu: montare 3 aparate AC și accesorii, 7.500 lei",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ciorna a fost completată")
        self.assertContains(response, 'value="7500"')
        self.assertContains(response, "montare 3 aparate AC și accesorii")
        self.assertEqual(ProviderQuote.objects.count(), 0)
        self.assertEqual(len(mail.outbox), notifications_before)

    def test_owner_command_amount_formats_and_fail_closed_syntax(self):
        """Romanian and English prices parse, while ambiguous prose is not acted on."""

        for command in (
            "Creează ofertă pentru dl. Ionescu: montare 3 aparate AC și accesorii, 7.500 lei",
            "Create offer for Mr. Ionescu: install 3 AC units and accessories, 7,500 lei",
        ):
            self.assertEqual(parse_quote_command(command).amount_ron, 7500)
        with self.assertRaises(ValueError):
            parse_quote_command("Trimite factura către Ionescu și marchează-o plătită")
        self.assertEqual(owner_command_kind("Cine nu mi-a plătit?"), "outstanding")
        self.assertEqual(owner_command_kind("Who hasn't paid me?"), "outstanding")
        self.assertEqual(owner_command_kind("Marchează totul plătit"), "quote")

    def test_owner_command_english_surface_shows_supported_syntax(self):
        """The English dashboard exposes an English instruction the parser accepts."""

        self.client.force_login(self.owner)
        with translation.override("en"):
            response = self.client.get(reverse("services:provider_leads"))
        self.assertContains(response, "Company assistant")
        self.assertContains(response, "Create offer for Mr. Ionescu")

    def test_work_register_empty_state_and_invalid_filter(self):
        """A fresh owner sees no invented job and unknown filters fall back safely."""

        self.client.force_login(self.owner)
        response = self.client.get(
            f'{reverse("services:provider_leads")}?view=work&work=unknown&work_page=oops'
        )
        self.assertContains(response, "Nu există încă lucrări acceptate")
        self.assertEqual(response.context["work_filter"], "all")
        self.assertEqual(response.context["work_counts"]["total"], 0)
        calendar = self.client.get(
            f'{reverse("services:provider_leads")}?view=work&display=calendar&week=bad-date'
        )
        self.assertContains(calendar, "Nicio lucrare programată", count=7)
        self.assertEqual(len(calendar.context["calendar_days"]), 7)
        self.assertEqual(calendar.context["calendar_page"].paginator.count, 0)
        with translation.override("en"):
            english = self.client.get(f'{reverse("services:provider_leads")}?view=work')
        self.assertContains(english, "Company jobs")
        self.assertContains(english, "No accepted jobs yet")

    def test_future_work_schedule_can_be_cancelled_without_losing_the_job(self):
        """Only the owner may undo a future slot; accepted work remains auditable."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        quote = send_provider_quote(
            user=self.owner, lead_id=lead.pk, amount_ron="7500.00",
            summary="Montarea a trei aparate de aer condiționat și accesorii.",
            estimated_duration="O zi",
            valid_until=timezone.localdate() + timedelta(days=14),
        )
        respond_to_provider_quote(
            lead=lead, quote_id=quote.pk, decision=ProviderQuote.Status.ACCEPTED,
        )
        start = (timezone.now() + timedelta(days=2)).replace(second=0, microsecond=0)
        end = start + timedelta(hours=2)
        order = schedule_provider_work_order(
            user=self.owner, lead_id=lead.pk, expected_revision=0,
            starts_at=start, ends_at=end,
        )
        self.client.force_login(self.owner)
        requests_url = reverse("services:provider_leads")
        page = self.client.get(requests_url)
        self.assertContains(page, "Anulează această programare")
        self.assertContains(page, "Oferta acceptată și lucrarea rămân active")
        with translation.override("en"):
            self.assertContains(self.client.get(reverse("services:provider_leads")), "Cancel this booking")
        self.assertEqual(
            self.client.post(requests_url, {
                "lead_id": lead.pk, "action": "work_cancel",
                f"cancel-{lead.pk}-expected_revision": order.revision,
            }).status_code, 200,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, ProviderWorkOrder.Status.SCHEDULED)
        with self.assertRaises(PermissionError):
            cancel_provider_work_schedule(
                user=self.reviewer, lead_id=lead.pk, expected_revision=order.revision,
            )
        notifications_before = len(mail.outbox)
        cancelled = self.client.post(requests_url, {
            "lead_id": lead.pk, "action": "work_cancel",
            f"cancel-{lead.pk}-expected_revision": order.revision,
            f"cancel-{lead.pk}-confirmed": "on",
        })
        self.assertEqual(cancelled.status_code, 302)
        order.refresh_from_db()
        lead.refresh_from_db()
        quote.refresh_from_db()
        self.assertEqual(order.status, ProviderWorkOrder.Status.AWAITING_SCHEDULE)
        self.assertIsNone(order.scheduled_start)
        self.assertIsNone(order.scheduled_end)
        self.assertEqual(order.revision, 2)
        self.assertEqual(lead.status, ProviderLead.Status.WON)
        self.assertEqual(quote.status, ProviderQuote.Status.ACCEPTED)
        event = order.events.get(revision=2)
        self.assertEqual(event.previous_start, start)
        self.assertEqual(event.previous_end, end)
        self.assertIsNone(event.new_start)
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(len(mail.outbox), notifications_before + 1)
        self.assertNotContains(self.client.get(requests_url), "Anulează această programare")
        work_url = f"{requests_url}?view=work"
        self.assertContains(self.client.get(f"{work_url}&work=awaiting_schedule"), lead.customer_name)
        self.assertNotContains(self.client.get(f"{work_url}&work=scheduled"), lead.customer_name)
        with self.assertRaisesMessage(ValueError, "modificată"):
            cancel_provider_work_schedule(
                user=self.owner, lead_id=lead.pk, expected_revision=1,
            )
        rescheduled = schedule_provider_work_order(
            user=self.owner, lead_id=lead.pk, expected_revision=order.revision,
            starts_at=start + timedelta(days=1),
        )
        with patch("services.provider_leads.timezone.now", return_value=rescheduled.scheduled_start):
            with self.assertRaisesMessage(ValueError, "începută"):
                cancel_provider_work_schedule(
                    user=self.owner, lead_id=lead.pk, expected_revision=rescheduled.revision,
                )

    def test_accepted_work_order_is_scheduled_and_completed_explicitly(self):
        """Execution is a revisioned workflow, not an owner-editable lead label."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        quote = send_provider_quote(
            user=self.owner, lead_id=lead.pk, amount_ron="7500.00",
            summary="Montarea a trei aparate de aer condiționat și accesorii.",
            estimated_duration="O zi",
            valid_until=timezone.localdate() + timedelta(days=14),
        )
        respond_to_provider_quote(
            lead=lead, quote_id=quote.pk, decision=ProviderQuote.Status.ACCEPTED,
        )
        lead.refresh_from_db()
        order = ProviderWorkOrder.objects.get(lead=lead)
        work_url = f'{reverse("services:provider_leads")}?view=work'
        self.client.force_login(self.owner)
        awaiting_page = self.client.get(f"{work_url}&work=awaiting_schedule")
        self.assertContains(awaiting_page, "Programează lucrarea")
        self.assertContains(awaiting_page, lead.customer_name)
        self.assertContains(awaiting_page, f"?view=requests&amp;focus={lead.public_id}")
        self.assertNotContains(self.client.get(f"{work_url}&work=scheduled"), lead.customer_name)
        with self.assertRaisesMessage(ValueError, "schimbare de stare"):
            update_provider_lead_for_owner(
                user=self.owner, lead_id=lead.pk, expected_revision=lead.revision,
                new_status=ProviderLead.Status.COMPLETED, owner_notes="",
            )

        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(hours=2)
        with self.assertRaisesMessage(ValueError, "Ora de încheiere"):
            schedule_provider_work_order(
                user=self.owner, lead_id=lead.pk, expected_revision=0,
                starts_at=start, ends_at=start - timedelta(minutes=1),
            )
        scheduled = self.client.post(
            reverse("services:provider_leads"),
            {
                "lead_id": lead.pk, "action": "work_schedule",
                f"work-{lead.pk}-expected_revision": order.revision,
                f"work-{lead.pk}-starts_at": timezone.localtime(start).strftime("%Y-%m-%dT%H:%M"),
                f"work-{lead.pk}-ends_at": timezone.localtime(end).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(scheduled.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, ProviderWorkOrder.Status.SCHEDULED)
        self.assertEqual(order.revision, 1)
        self.assertEqual(order.scheduled_end, end.replace(second=0, microsecond=0))
        self.assertEqual(order.events.get().new_end, order.scheduled_end)
        self.assertContains(self.client.get(f"{work_url}&work=scheduled"), "Deschide programarea")
        calendar_week = timezone.localtime(order.scheduled_start).date().isoformat()
        calendar_url = f"{work_url}&display=calendar&week={calendar_week}"
        self.assertContains(self.client.get(calendar_url), "Deschide lucrarea")
        self.assertContains(self.client.get(calendar_url), "–")
        self.assertContains(self.client.get(reverse("services:provider_leads")), "încheiere estimată de firmă")
        self.assertContains(self.client.get(calendar_url), lead.customer_name)
        self.assertNotContains(
            self.client.get(f"{work_url}&display=calendar&week={(timezone.localtime(start).date() + timedelta(days=14)).isoformat()}"),
            lead.customer_name,
        )
        self.assertNotContains(self.client.get(f"{work_url}&work=awaiting_schedule"), lead.customer_name)
        self.assertEqual(ProviderWorkOrderEvent.objects.get(work_order=order).new_status, "scheduled")
        self.assertContains(self.client.get(reverse("services:provider_leads")), "Data planificată de firmă")
        with self.assertRaisesMessage(ValueError, "modificată"):
            schedule_provider_work_order(
                user=self.owner, lead_id=lead.pk, expected_revision=0,
                starts_at=start + timedelta(days=1),
            )
        with self.assertRaisesMessage(ValueError, "înainte de data programată"):
            complete_provider_work_order(user=self.owner, lead_id=lead.pk, expected_revision=1)
        with patch("services.provider_leads.timezone.now", return_value=start + timedelta(hours=2)):
            completed = self.client.post(
                reverse("services:provider_leads"),
                {
                    "lead_id": lead.pk, "action": "work_complete",
                    f"complete-{lead.pk}-expected_revision": 1,
                    f"complete-{lead.pk}-confirmed": "on",
                },
            )
        self.assertEqual(completed.status_code, 302)
        order.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(order.status, ProviderWorkOrder.Status.COMPLETED)
        self.assertNotContains(self.client.get(calendar_url), lead.customer_name)
        self.assertContains(self.client.get(f"{work_url}&work=completed"), "Vezi lucrarea")
        self.assertNotContains(self.client.get(f"{work_url}&work=scheduled"), lead.customer_name)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(work_url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(lead.status, ProviderLead.Status.COMPLETED)
        self.assertEqual(order.events.count(), 2)
        self.assertEqual(lead.events.latest("pk").new_status, ProviderLead.Status.COMPLETED)
        billing_url = f'{reverse("services:provider_leads")}?view=billing'
        billing_before = self.client.get(billing_url)
        self.assertEqual(billing_before.status_code, 200)
        self.assertContains(billing_before, "Facturare și încasări interne")
        self.assertContains(billing_before, "Pregătește ciorna internă")
        self.assertContains(billing_before, "?view=requests&amp;focus=")
        self.assertNotContains(billing_before, "factură emisă pentru client")
        self.assertContains(
            self.client.get(f"{billing_url}&billing=pending"), "Pregătește ciorna internă"
        )
        with self.assertRaisesMessage(ValueError, "modificată"):
            complete_provider_work_order(user=self.owner, lead_id=lead.pk, expected_revision=1)

        notification_count = len(mail.outbox)
        draft_response = self.client.post(
            reverse("services:provider_leads"),
            {
                "lead_id": lead.pk, "action": "invoice_draft",
                f"invoice-{lead.pk}-expected_revision": 0,
                f"invoice-{lead.pk}-amount_ron": "7500.00",
                f"invoice-{lead.pk}-description": "Montare trei aparate de aer condiționat.",
            },
        )
        self.assertEqual(draft_response.status_code, 302)
        draft = ProviderInvoiceDraft.objects.get(work_order=order)
        self.assertEqual(draft.amount_ron, 7500)
        self.assertEqual(draft.revision, 1)
        self.assertContains(self.client.get(reverse("services:provider_leads")), "Ciornă internă salvată")
        billing_after = self.client.get(f"{billing_url}&billing=ready")
        self.assertContains(billing_after, "Ciornă internă")
        self.assertContains(billing_after, "7500")
        self.assertNotContains(
            self.client.get(f"{billing_url}&billing=pending"), "Montarea a trei aparate"
        )
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(billing_url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(len(mail.outbox), notification_count)
        with self.assertRaisesMessage(ValueError, "Ciorna s-a modificat"):
            save_provider_invoice_draft(
                user=self.owner, lead_id=lead.pk, expected_revision=0,
                amount_ron="7800.00", description="Montare trei aparate de aer condiționat.",
            )
        updated, changed = save_provider_invoice_draft(
            user=self.owner, lead_id=lead.pk, expected_revision=1,
            amount_ron="7800.00", description="Montare trei aparate de aer condiționat.",
        )
        self.assertTrue(changed)
        self.assertEqual(updated.revision, 2)
        unchanged, changed = save_provider_invoice_draft(
            user=self.owner, lead_id=lead.pk, expected_revision=2,
            amount_ron="7800.00", description="Montare trei aparate de aer condiționat.",
        )
        self.assertFalse(changed)
        self.assertEqual(unchanged.revision, 2)
        completion_date = timezone.localtime(order.completed_at).date()
        receivable = open_provider_receivable(
            user=self.owner, lead_id=lead.pk,
            due_date=completion_date + timedelta(days=14),
            reference="Comanda internă 42",
        )
        self.assertEqual(receivable.amount_ron, 7800)
        outstanding_command = self.client.post(
            reverse("services:provider_leads"), {
                "action": "prepare_quote", "command": "Cine nu mi-a plătit?",
            },
        )
        self.assertContains(outstanding_command, "Un sold restant")
        self.assertContains(outstanding_command, "7800")
        self.assertContains(outstanding_command, "?view=billing&amp;billing=outstanding")
        self.assertContains(self.client.get(f"{billing_url}&billing=outstanding"), "Sold intern în curs")
        with self.assertRaisesMessage(ValueError, "blocată"):
            save_provider_invoice_draft(
                user=self.owner, lead_id=lead.pk, expected_revision=2,
                amount_ron="7900.00", description="Montare trei aparate de aer condiționat.",
            )
        with patch("services.provider_receivables.timezone.localdate", return_value=completion_date):
            payment = record_provider_manual_payment(
                user=self.owner, lead_id=lead.pk, amount_ron="3000.00",
                received_on=completion_date, reference="Transfer declarat",
            )
        self.assertEqual(provider_receivable_totals(receivable), (3000, 4800))
        with patch("services.provider_receivables.timezone.localdate", return_value=completion_date):
            with self.assertRaisesMessage(ValueError, "soldul"):
                record_provider_manual_payment(
                    user=self.owner, lead_id=lead.pk, amount_ron="5000.00",
                    received_on=completion_date, reference="",
                )
        void_provider_manual_payment(
            user=self.owner, lead_id=lead.pk, payment_id=payment.pk,
            reason="Înregistrare introdusă din greșeală.",
        )
        payment.refresh_from_db()
        self.assertEqual(payment.state, ProviderManualPayment.State.VOID)
        self.assertEqual(provider_receivable_totals(receivable), (0, 7800))
        today = timezone.localdate()
        reminder_response = self.client.post(
            reverse("services:provider_leads"), {
                "lead_id": lead.pk, "action": "receivable_follow_up",
                f"follow-up-{lead.pk}-expected_revision": 0,
                f"follow-up-{lead.pk}-follow_up_on": today.isoformat(),
            },
        )
        self.assertEqual(reminder_response.status_code, 302)
        receivable.refresh_from_db()
        reminder = receivable
        self.assertEqual(reminder.follow_up_revision, 1)
        self.assertContains(self.client.get(f"{billing_url}&billing=followup"), "De urmărit azi")
        completed_reminder_response = self.client.post(
            reverse("services:provider_leads"), {
                "lead_id": lead.pk, "action": "receivable_follow_up_complete",
                f"follow-up-complete-{lead.pk}-expected_revision": 1,
            },
        )
        self.assertEqual(completed_reminder_response.status_code, 302)
        receivable.refresh_from_db()
        reminder = receivable
        self.assertIsNone(reminder.follow_up_on)
        with self.assertRaisesMessage(ValueError, "pauza de 7 zile"):
            schedule_provider_receivable_follow_up(
                user=self.owner, lead_id=lead.pk, expected_revision=2,
                follow_up_on=today,
            )
        reminder = schedule_provider_receivable_follow_up(
            user=self.owner, lead_id=lead.pk, expected_revision=2,
            follow_up_on=today + timedelta(days=7),
        )
        self.assertEqual(reminder.follow_up_revision, 3)
        with patch("services.provider_receivables.timezone.localdate", return_value=completion_date):
            settled_payment = record_provider_manual_payment(
                user=self.owner, lead_id=lead.pk, amount_ron="7800.00",
                received_on=completion_date, reference="Încasare integrală declarată",
            )
        self.assertEqual(settled_payment.state, ProviderManualPayment.State.ACTIVE)
        receivable.refresh_from_db()
        self.assertIsNone(receivable.follow_up_on)
        self.assertEqual(receivable.follow_up_revision, 4)
        self.assertEqual(
            receivable.follow_up_events.latest("revision").action,
            ProviderReceivableFollowUpEvent.Action.CLEARED_AFTER_PAYMENT,
        )
        settled_page = self.client.get(f"{billing_url}&billing=settled")
        self.assertContains(settled_page, "Încasat integral conform înregistrărilor manuale")
        self.assertContains(settled_page, "nu sunt verificate de bancă")
        settled_command = self.client.post(
            reverse("services:provider_leads"), {
                "action": "prepare_quote", "command": "Cine nu mi-a plătit?",
            },
        )
        self.assertContains(settled_command, "0 solduri restante")
        with self.assertRaises(PermissionError):
            save_provider_invoice_draft(
                user=self.reviewer, lead_id=lead.pk, expected_revision=2,
                amount_ron="7800.00", description="Montare trei aparate de aer condiționat.",
            )

    def test_work_order_rejects_unscheduled_completion_and_bad_date(self):
        """A missing or inaccurate execution schedule never becomes completed work."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        quote = send_provider_quote(
            user=self.owner, lead_id=lead.pk, amount_ron="7500.00",
            summary="Montarea a trei aparate de aer condiționat și accesorii.",
            estimated_duration="O zi",
            valid_until=timezone.localdate() + timedelta(days=14),
        )
        respond_to_provider_quote(
            lead=lead, quote_id=quote.pk, decision=ProviderQuote.Status.ACCEPTED,
        )
        with self.assertRaisesMessage(ValueError, "Programează lucrarea"):
            complete_provider_work_order(user=self.owner, lead_id=lead.pk, expected_revision=0)
        with self.assertRaisesMessage(ValueError, "5 minute"):
            schedule_provider_work_order(
                user=self.owner, lead_id=lead.pk, expected_revision=0,
                starts_at=timezone.now() - timedelta(days=1),
            )
        future_start = timezone.now() + timedelta(days=1)
        with self.assertRaisesMessage(ValueError, "14 zile"):
            schedule_provider_work_order(
                user=self.owner, lead_id=lead.pk, expected_revision=0,
                starts_at=future_start, ends_at=future_start + timedelta(days=15),
            )
        self.assertEqual(ProviderWorkOrderEvent.objects.count(), 0)
        with self.assertRaisesMessage(ValueError, "Finalizează lucrarea"):
            save_provider_invoice_draft(
                user=self.owner, lead_id=lead.pk, expected_revision=0,
                amount_ron="7500.00", description="Montare trei aparate de aer condiționat.",
            )
        self.assertFalse(ProviderInvoiceDraft.objects.exists())

    def test_calendar_flags_only_overlapping_known_intervals(self):
        """Only complete half-open intervals produce an owner-only advisory."""

        leads = []
        for index in range(2):
            response = self.client.post(
                self.url,
                self.direct_payload(
                    customer_name=f"Client Calendar {index}",
                    customer_email=f"calendar{index}@example.test",
                ),
            )
            self.assertContains(response, "Solicitarea a fost trimisă")
            lead = ProviderLead.objects.order_by("-pk").first()
            quote = send_provider_quote(
                user=self.owner, lead_id=lead.pk, amount_ron="2500.00",
                summary="Montaj și verificare la client.",
                estimated_duration="Două ore",
                valid_until=timezone.localdate() + timedelta(days=14),
            )
            respond_to_provider_quote(
                lead=lead, quote_id=quote.pk, decision=ProviderQuote.Status.ACCEPTED,
            )
            leads.append(lead)

        start = (timezone.now() + timedelta(days=2)).replace(second=0, microsecond=0)
        first = schedule_provider_work_order(
            user=self.owner, lead_id=leads[0].pk, expected_revision=0,
            starts_at=start, ends_at=start + timedelta(hours=3),
        )
        second = schedule_provider_work_order(
            user=self.owner, lead_id=leads[1].pk, expected_revision=0,
            starts_at=start + timedelta(hours=1), ends_at=start + timedelta(hours=2),
        )
        self.client.force_login(self.owner)
        calendar_url = (
            f'{reverse("services:provider_leads")}?view=work&display=calendar'
            f'&week={timezone.localtime(start).date().isoformat()}'
        )
        page = self.client.get(calendar_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Interval suprapus cu altă lucrare", count=2)

        second = schedule_provider_work_order(
            user=self.owner, lead_id=leads[1].pk, expected_revision=second.revision,
            starts_at=start + timedelta(hours=3), ends_at=start + timedelta(hours=4),
        )
        self.assertNotContains(self.client.get(calendar_url), "Interval suprapus cu altă lucrare")
        first = schedule_provider_work_order(
            user=self.owner, lead_id=leads[0].pk, expected_revision=first.revision,
            starts_at=start, ends_at=None,
        )
        self.assertNotContains(self.client.get(calendar_url), "Interval suprapus cu altă lucrare")

        next_monday = timezone.localdate() + timedelta(days=14 - timezone.localdate().weekday())
        monday_start = timezone.make_aware(datetime.combine(next_monday, time.min))
        schedule_provider_work_order(
            user=self.owner, lead_id=leads[0].pk, expected_revision=first.revision,
            starts_at=monday_start - timedelta(hours=1),
            ends_at=monday_start + timedelta(hours=1),
        )
        schedule_provider_work_order(
            user=self.owner, lead_id=leads[1].pk, expected_revision=second.revision,
            starts_at=monday_start + timedelta(minutes=30),
            ends_at=monday_start + timedelta(hours=2),
        )
        adjacent_week = f'{reverse("services:provider_leads")}?view=work&display=calendar&week={next_monday.isoformat()}'
        page = self.client.get(adjacent_week)
        self.assertContains(page, "Interval suprapus cu altă lucrare", count=1)
        self.assertContains(page, "Client Calendar 1")
        self.assertNotContains(page, "Client Calendar 0")

    def test_other_user_cannot_schedule_provider_work_order(self):
        """A valid lead identifier grants no access outside its owner membership."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        quote = send_provider_quote(
            user=self.owner, lead_id=lead.pk, amount_ron="7500.00",
            summary="Montarea a trei aparate de aer condiționat și accesorii.",
            estimated_duration="O zi",
            valid_until=timezone.localdate() + timedelta(days=14),
        )
        respond_to_provider_quote(
            lead=lead, quote_id=quote.pk, decision=ProviderQuote.Status.ACCEPTED,
        )
        with self.assertRaises(PermissionError):
            schedule_provider_work_order(
                user=self.reviewer, lead_id=lead.pk, expected_revision=0,
                starts_at=timezone.now() + timedelta(days=1),
            )
        self.assertEqual(ProviderWorkOrder.objects.get(lead=lead).revision, 0)
        self.assertFalse(ProviderWorkOrderEvent.objects.exists())

    def test_owner_command_rejects_unknown_and_ambiguous_clients(self):
        """A name hint must not silently choose another person's private request."""

        self.client.post(self.url, self.valid_payload)
        ProviderLead.objects.create(
            submission=self.submission,
            category="constructii",
            county="Iași",
            siruta_code="95079",
            customer_name="Ioana Popescu",
            customer_email="ioana@example.test",
            customer_phone="0700 000 001",
            description="Altă cerere, care nu poate fi selectată implicit.",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            visitor_session_digest=uuid4().hex,
            privacy_notice_version="2026-08-31",
            customer_access_digest=uuid4().hex,
            customer_access_expires_at=timezone.now() + timedelta(days=7),
        )
        self.client.force_login(self.owner)
        for name in ("Popescu", "Ionescu"):
            response = self.client.post(
                reverse("services:provider_leads"),
                {
                    "action": "prepare_quote",
                    "command": f"Creează ofertă pentru dl. {name}: montare 3 aparate AC și accesorii, 7.500 lei",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Nu am găsit un singur client activ")
            self.assertNotContains(response, "Ciorna a fost completată")
        self.assertEqual(ProviderQuote.objects.count(), 0)

    def test_owner_inbox_filters_and_paginates_without_leaking_other_profiles(self):
        """Fixed status filters keep a growing owner inbox bounded and navigable."""

        self.client.post(self.url, self.valid_payload)
        statuses = (
            ProviderLead.Status.CONTACTED,
            ProviderLead.Status.VISIT_SCHEDULED,
            ProviderLead.Status.QUOTE_SENT,
            ProviderLead.Status.WON,
            ProviderLead.Status.COMPLETED,
            ProviderLead.Status.DECLINED,
            ProviderLead.Status.NEW,
        )
        for index, status in enumerate(statuses, start=1):
            ProviderLead.objects.create(
                submission=self.submission,
                category="constructii",
                county="Iași",
                siruta_code="95079",
                customer_name=f"Client filtru {index}",
                customer_email=f"filtru-{index}@example.test",
                customer_phone=f"0700 000 0{index:02d}",
                description="Solicitare creată pentru verificarea inboxului furnizorului.",
                desired_start=ProviderLead.DesiredStart.FLEXIBLE,
                status=status,
                visitor_session_digest=uuid4().hex,
                privacy_notice_version="2026-08-31",
                customer_access_digest=uuid4().hex,
                customer_access_expires_at=timezone.now() + timedelta(days=7),
            )

        self.client.force_login(self.owner)
        inbox_url = reverse("services:provider_leads")
        first_page = self.client.get(inbox_url)
        self.assertEqual(len(first_page.context["lead_cards"]), 6)
        self.assertEqual(first_page.context["lead_page"].paginator.count, 8)
        self.assertContains(first_page, "Pagina 1 din 2")

        second_page = self.client.get(inbox_url, {"view": "requests", "page": "2"})
        self.assertEqual(len(second_page.context["lead_cards"]), 2)
        self.assertContains(second_page, "Pagina 2 din 2")
        oldest = ProviderLead.objects.get(customer_name="Maria Popescu")
        focused = self.client.get(inbox_url, {
            "focus": str(oldest.public_id), "view": "performance", "status": "new", "page": "1",
        })
        target = f"{inbox_url}?view=requests&page=2#lead-{oldest.public_id}"
        self.assertRedirects(focused, target)
        focused_page = self.client.get(target)
        self.assertEqual(focused_page.context["lead_page"].number, 2)
        self.assertEqual(focused_page.context["lead_filter"], "all")
        self.assertEqual(focused_page.context["dashboard_section"], "requests")
        self.assertContains(focused_page, f'id="lead-{oldest.public_id}"')
        self.assertEqual(self.client.get(inbox_url, {"focus": "invalid"}).status_code, 404)
        self.assertEqual(self.client.get(inbox_url, {"focus": str(uuid4())}).status_code, 404)

        active = self.client.get(
            inbox_url, {"view": "requests", "status": "active"}
        )
        self.assertEqual(active.context["lead_filter"], "active")
        self.assertEqual(active.context["lead_page"].paginator.count, 3)
        self.assertContains(active, "Client filtru 1")
        self.assertContains(active, "Client filtru 3")
        self.assertNotContains(active, "Client filtru 4")
        self.assertContains(active, 'status=active" aria-current="page"')

        with translation.override("en"):
            english_url = reverse("services:provider_leads")
        english = self.client.get(
            english_url, {"view": "requests", "status": "active"}
        )
        self.assertContains(english, "Filter requests")
        self.assertContains(english, "In progress")
        self.assertContains(english, "3 requests in this category.")

        invalid = self.client.get(
            inbox_url,
            {"view": "requests", "status": "not-a-status", "page": "9" * 100},
        )
        self.assertEqual(invalid.context["lead_filter"], "all")
        self.assertEqual(invalid.context["lead_page"].number, 1)
        self.assertEqual(invalid.context["lead_page"].paginator.count, 8)

    def test_inbox_update_returns_to_the_validated_filter_and_page(self):
        """POST navigation accepts only the server-owned filter and numeric page state."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("services:provider_leads"),
            {
                "lead_id": lead.pk,
                "action": "update",
                "lead_filter": "new",
                "lead_page": "1",
                f"lead-{lead.pk}-expected_revision": lead.revision,
                f"lead-{lead.pk}-status": ProviderLead.Status.CONTACTED,
                f"lead-{lead.pk}-owner_notes": "Am contactat clientul.",
            },
        )

        self.assertRedirects(response, reverse("services:provider_leads") + "?status=new")
        lead.refresh_from_db()
        self.assertEqual(lead.status, ProviderLead.Status.CONTACTED)

    def test_owner_transition_is_optimistic_and_audited(self):
        """A valid state change advances revision once and appends an event."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()

        updated = update_provider_lead_for_owner(
            user=self.owner,
            lead_id=lead.pk,
            expected_revision=0,
            new_status=ProviderLead.Status.CONTACTED,
            owner_notes="  Am discutat   telefonic. ",
        )

        self.assertEqual(updated.status, ProviderLead.Status.CONTACTED)
        self.assertEqual(updated.revision, 1)
        self.assertEqual(updated.owner_notes, "Am discutat telefonic.")
        event = ProviderLeadEvent.objects.get()
        self.assertEqual(event.previous_status, ProviderLead.Status.NEW)
        self.assertEqual(event.new_status, ProviderLead.Status.CONTACTED)
        self.assertEqual(event.actor, self.owner)
        with self.assertRaisesMessage(ValueError, "modificată"):
            update_provider_lead_for_owner(
                user=self.owner,
                lead_id=lead.pk,
                expected_revision=0,
                new_status=ProviderLead.Status.DECLINED,
                owner_notes="",
            )

    def test_visit_requires_customer_confirmation_and_rejects_repeat_reply(self):
        """A provider proposal is not a booking until the private customer accepts."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        access_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body).group(0)
        access_path = access_url.removeprefix("http://testserver")
        self.client.force_login(self.owner)
        visit_time = timezone.localtime(timezone.now() + timedelta(days=2)).replace(second=0, microsecond=0)
        response = self.client.post(reverse("services:provider_leads"), {
            "lead_id": lead.pk, "action": "visit",
            f"visit-{lead.pk}-starts_at": visit_time.strftime("%Y-%m-%dT%H:%M"),
            f"visit-{lead.pk}-note": "Pentru măsurători",
        })
        self.assertEqual(response.status_code, 302)
        lead.refresh_from_db()
        self.assertEqual(lead.status, ProviderLead.Status.CONTACTED)
        proposal = ProviderVisitProposal.objects.get(lead=lead)
        self.assertEqual(proposal.status, ProviderVisitProposal.Status.PROPOSED)
        with self.assertRaisesMessage(ValueError, "confirmarea"):
            update_provider_lead_for_owner(
                user=self.owner, lead_id=lead.pk, expected_revision=lead.revision,
                new_status=ProviderLead.Status.VISIT_SCHEDULED, owner_notes="",
            )
        self.client.logout()
        self.assertContains(self.client.get(access_path), "Confirmă vizita")
        english_path = access_path.replace("/solicitari/", "/en/solicitari/", 1)
        self.assertContains(self.client.get(english_path), "Confirm visit")
        accepted = self.client.post(access_path, {
            "action": "visit_accepted", "proposal_id": proposal.pk,
        })
        self.assertEqual(accepted.status_code, 302)
        lead.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(lead.status, ProviderLead.Status.VISIT_SCHEDULED)
        self.assertEqual(proposal.status, ProviderVisitProposal.Status.ACCEPTED)
        self.assertEqual(lead.events.last().actor_role, ProviderLeadMessage.SenderRole.CUSTOMER)
        repeated = self.client.post(access_path, {
            "action": "visit_accepted", "proposal_id": proposal.pk,
        })
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(ProviderVisitProposal.objects.filter(lead=lead).count(), 1)

    def test_declined_or_elapsed_visit_can_be_reproposed(self):
        """Only one live proposal exists, while a declined or expired slot frees it."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        slot = timezone.now() + timedelta(days=2)
        first = propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Test")
        with self.assertRaisesMessage(ValueError, "deja"):
            propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Duplicat")
        respond_to_provider_visit(
            lead=lead, proposal_id=first.pk, decision=ProviderVisitProposal.Status.DECLINED,
        )
        second = propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Din nou")
        ProviderVisitProposal.objects.filter(pk=second.pk).update(starts_at=timezone.now() - timedelta(minutes=1))
        third = propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Nouă dată")
        second.refresh_from_db()
        self.assertEqual(second.status, ProviderVisitProposal.Status.EXPIRED)
        self.assertEqual(third.status, ProviderVisitProposal.Status.PROPOSED)

    def test_customer_cancels_confirmed_visit_and_provider_can_repropose(self):
        """A cancellation reopens scheduling without changing the customer's project."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        access_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body).group(0)
        access_path = access_url.removeprefix("http://testserver")
        slot = timezone.now() + timedelta(days=2)
        first = propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Măsurători")
        respond_to_provider_visit(
            lead=lead, proposal_id=first.pk, decision=ProviderVisitProposal.Status.ACCEPTED,
        )
        with self.assertRaisesMessage(ValueError, "Anulează vizita"):
            propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Conflict")
        self.assertContains(self.client.get(access_path), "Anulează vizita")
        response = self.client.post(access_path, {"action": "visit_cancel", "proposal_id": first.pk})
        self.assertRedirects(response, access_path)
        first.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(first.status, ProviderVisitProposal.Status.CANCELLED)
        self.assertEqual(first.cancelled_by, ProviderVisitProposal.CancelledBy.CUSTOMER)
        self.assertIsNotNone(first.cancelled_at)
        self.assertEqual(lead.status, ProviderLead.Status.CONTACTED)
        self.assertEqual(lead.events.last().actor_role, ProviderLeadMessage.SenderRole.CUSTOMER)
        repeated = self.client.post(access_path, {"action": "visit_cancel", "proposal_id": first.pk})
        self.assertEqual(repeated.status_code, 200)
        second = propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="Altă oră")
        self.assertEqual(second.status, ProviderVisitProposal.Status.PROPOSED)

    def test_provider_withdraws_pending_visit_without_customer_confirmation(self):
        """A provider can withdraw an unanswered slot and immediately propose another."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        first = propose_provider_visit(
            user=self.owner, lead_id=lead.pk,
            starts_at=timezone.now() + timedelta(days=2), note="Vizită inițială",
        )
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("services:provider_leads")), "Retrage propunerea")
        response = self.client.post(reverse("services:provider_leads"), {
            "lead_id": lead.pk, "action": "visit_cancel", "proposal_id": first.pk,
        })
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(first.status, ProviderVisitProposal.Status.CANCELLED)
        self.assertEqual(first.cancelled_by, ProviderVisitProposal.CancelledBy.PROVIDER)
        self.assertEqual(lead.status, ProviderLead.Status.CONTACTED)
        self.assertEqual(lead.events.count(), 1)
        second = propose_provider_visit(
            user=self.owner, lead_id=lead.pk,
            starts_at=timezone.now() + timedelta(days=3), note="Noua propunere",
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_cancelling_visit_after_quote_keeps_quote_funnel_state(self):
        """A visit is independent of an already sent commercial offer."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        slot = timezone.now() + timedelta(days=2)
        visit = propose_provider_visit(user=self.owner, lead_id=lead.pk, starts_at=slot, note="După ofertă")
        send_provider_quote(
            user=self.owner, lead_id=lead.pk, amount_ron=1200,
            summary="Verificăm lucrarea și estimăm materialele la fața locului.",
            estimated_duration="Două zile", valid_until=timezone.localdate() + timedelta(days=10),
        )
        respond_to_provider_visit(
            lead=lead, proposal_id=visit.pk, decision=ProviderVisitProposal.Status.ACCEPTED,
        )
        cancelled = cancel_provider_visit_for_owner(
            user=self.owner, lead_id=lead.pk, proposal_id=visit.pk,
        )
        lead.refresh_from_db()
        self.assertEqual(cancelled.status, ProviderVisitProposal.Status.CANCELLED)
        self.assertEqual(lead.status, ProviderLead.Status.QUOTE_SENT)
        self.assertTrue(lead.quotes.exists())
        new_visit = propose_provider_visit(
            user=self.owner, lead_id=lead.pk,
            starts_at=timezone.now() + timedelta(days=4), note="Reprogramată",
        )
        self.assertEqual(new_visit.status, ProviderVisitProposal.Status.PROPOSED)

    def test_private_customer_link_quote_and_acceptance_complete_the_offer_flow(self):
        """Only the emailed capability can view and accept the immutable offer."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        access_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body).group(0)
        access_path = access_url.removeprefix("http://testserver")

        private_page = self.client.get(access_path)
        self.assertEqual(private_page.status_code, 200)
        self.assertIn("no-store", private_page.headers["Cache-Control"])
        self.assertEqual(private_page.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            self.client.get(
                reverse(
                    "services:provider_lead_customer",
                    args=(lead.public_id, "token-incorect"),
                )
            ).status_code,
            404,
        )

        self.client.force_login(self.owner)
        quote_payload = {
            "lead_id": lead.pk,
            "action": "quote",
            f"quote-{lead.pk}-amount_ron": "24500.00",
            f"quote-{lead.pk}-item_1_description": "Manoperă pentru renovare",
            f"quote-{lead.pk}-item_1_quantity": "1",
            f"quote-{lead.pk}-item_1_unit": "lucrare",
            f"quote-{lead.pk}-item_1_unit_price_ron": "24500.00",
            f"quote-{lead.pk}-estimated_duration": "4 săptămâni",
            f"quote-{lead.pk}-valid_until": (
                timezone.localdate() + timedelta(days=14)
            ).isoformat(),
            f"quote-{lead.pk}-summary": (
                "Manoperă completă pentru renovare, cu pregătirea suprafețelor inclusă."
            ),
        }
        response = self.client.post(reverse("services:provider_leads"), quote_payload)
        self.assertRedirects(response, reverse("services:provider_leads"))
        quote = ProviderQuote.objects.get()
        lead.refresh_from_db()
        self.assertEqual(quote.revision, 1)
        self.assertEqual(quote.lines.count(), 1)
        self.assertEqual(quote.lines.get().description, "Manoperă pentru renovare")
        self.assertEqual(lead.status, ProviderLead.Status.QUOTE_SENT)
        with self.assertRaisesMessage(ValueError, "acceptarea ofertei"):
            update_provider_lead_for_owner(
                user=self.owner, lead_id=lead.pk, expected_revision=lead.revision,
                new_status=ProviderLead.Status.WON, owner_notes="",
            )
        self.assertIn("Folosește linkul privat", mail.outbox[-1].body)
        self.assertNotIn(access_url, mail.outbox[-1].body)
        self.assertNotIn("24500", mail.outbox[-1].body)

        self.client.logout()
        page = self.client.get(access_path)
        self.assertContains(page, "24500,00")
        accepted = self.client.post(
            access_path,
            {"action": ProviderQuote.Status.ACCEPTED, "quote_id": quote.pk},
        )
        self.assertRedirects(accepted, access_path)
        quote.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(quote.status, ProviderQuote.Status.ACCEPTED)
        self.assertEqual(lead.status, ProviderLead.Status.WON)
        order = ProviderWorkOrder.objects.get(lead=lead)
        self.assertEqual(order.accepted_quote, quote)
        self.assertEqual(order.status, ProviderWorkOrder.Status.AWAITING_SCHEDULE)
        self.assertContains(self.client.get(access_path), "Lucrarea a fost deschisă")
        self.assertEqual(
            self.client.post(
                access_path, {"action": ProviderQuote.Status.ACCEPTED, "quote_id": quote.pk},
            ).status_code, 200,
        )
        self.assertEqual(ProviderWorkOrder.objects.filter(lead=lead).count(), 1)

        self.assertEqual(lead.events.latest("pk").actor_role, "customer")

        review_page = self.client.get(access_path)
        self.assertContains(review_page, "Spune cum a fost colaborarea")
        review_body = (
            "Comunicarea a fost clară, oferta a fost respectată, iar lucrarea "
            "a fost finalizată atent și la termen."
        )
        submitted_review = self.client.post(
            access_path,
            {
                "action": "review",
                "customer-review-rating": "5",
                "customer-review-body": review_body,
                "customer-review-consent": "on",
            },
        )
        self.assertRedirects(submitted_review, access_path)
        review = ProviderCustomerReview.objects.get(lead=lead)
        self.assertEqual(review.status, ProviderCustomerReview.Status.PENDING)
        self.assertEqual(review.reviewer_display_name, "Maria P.")
        self.assertContains(self.client.get(access_path), "Recenzia ta")

        public_url = (
            reverse("services:provider_public_detail", args=(self.profile.public_id,))
            + "?"
            + self.query
        )
        self.assertNotContains(self.client.get(public_url), review_body)

        self.client.force_login(self.reviewer)
        moderation_url = reverse(
            "admin:services_providercustomerreview_moderate", args=(review.pk,)
        )
        moderation = self.client.post(
            moderation_url,
            {
                "decision": ProviderCustomerReview.Status.APPROVED,
                "internal_note": "Solicitarea și conținutul recenziei au fost verificate.",
                "acknowledgement": "on",
            },
        )
        self.assertRedirects(
            moderation,
            reverse("admin:services_providercustomerreview_change", args=(review.pk,)),
        )
        review.refresh_from_db()
        self.assertEqual(review.status, ProviderCustomerReview.Status.APPROVED)
        self.assertEqual(ProviderCustomerReviewEvent.objects.count(), 1)
        public_page = self.client.get(public_url)
        self.assertContains(public_page, review_body)
        self.assertContains(public_page, "Maria P.")
        self.assertContains(public_page, "5/5")

        self.client.force_login(self.owner)
        reply_body = "Vă mulțumim pentru încredere și pentru colaborarea foarte bună."
        reply_response = self.client.post(
            reverse("services:provider_review_reply", args=(review.pk,)),
            {f"reply-{review.pk}-body": reply_body},
        )
        self.assertRedirects(
            reply_response, reverse("services:provider_leads") + "?view=reviews"
        )
        reply = ProviderCustomerReviewReply.objects.get(review=review)
        self.assertEqual(reply.status, ProviderCustomerReviewReply.Status.PENDING)
        self.assertNotContains(self.client.get(public_url), reply_body)

        self.client.force_login(self.reviewer)
        reply_moderation_url = reverse(
            "admin:services_providercustomerreviewreply_moderate", args=(reply.pk,)
        )
        self.client.post(
            reply_moderation_url,
            {
                "decision": "approved",
                "internal_note": "Răspuns profesional, fără date personale.",
                "acknowledgement": "on",
            },
        )
        reply.refresh_from_db()
        self.assertEqual(reply.status, ProviderCustomerReviewReply.Status.APPROVED)
        self.assertContains(self.client.get(public_url), reply_body)

    def test_quote_total_is_derived_from_complete_immutable_lines(self):
        """The browser may preview a total, but only server-side line math is authoritative."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        access_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body).group(0)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("services:provider_leads"), {
            "lead_id": lead.pk,
            "action": "quote",
            f"quote-{lead.pk}-amount_ron": "1.00",
            f"quote-{lead.pk}-item_1_description": "Montaj aparate de aer condiționat",
            f"quote-{lead.pk}-item_1_quantity": "3",
            f"quote-{lead.pk}-item_1_unit": "buc",
            f"quote-{lead.pk}-item_1_unit_price_ron": "2400.00",
            f"quote-{lead.pk}-item_2_description": "Kituri de instalare",
            f"quote-{lead.pk}-item_2_quantity": "3",
            f"quote-{lead.pk}-item_2_unit": "set",
            f"quote-{lead.pk}-item_2_unit_price_ron": "100.00",
            f"quote-{lead.pk}-estimated_duration": "Două zile",
            f"quote-{lead.pk}-valid_until": (
                timezone.localdate() + timedelta(days=14)
            ).isoformat(),
            f"quote-{lead.pk}-summary": "Montaj complet pentru cele trei aparate descrise de client.",
        })

        self.assertRedirects(response, reverse("services:provider_leads"))
        quote = ProviderQuote.objects.get()
        self.assertEqual(quote.amount_ron, 7500)
        self.assertEqual(
            list(quote.lines.values_list("position", "description")),
            [(1, "Montaj aparate de aer condiționat"), (2, "Kituri de instalare")],
        )
        customer_page = self.client.get(access_url.removeprefix("http://testserver"))
        self.assertContains(customer_page, "Detaliile ofertei")
        self.assertContains(customer_page, "Kituri de instalare")

    def test_quote_rejects_a_partially_completed_line(self):
        """An incomplete position remains reviewable and never creates an offer."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        self.client.force_login(self.owner)
        response = self.client.post(reverse("services:provider_leads"), {
            "lead_id": lead.pk,
            "action": "quote",
            f"quote-{lead.pk}-item_1_description": "Montaj incomplet",
            f"quote-{lead.pk}-estimated_duration": "Două zile",
            f"quote-{lead.pk}-valid_until": (
                timezone.localdate() + timedelta(days=14)
            ).isoformat(),
            f"quote-{lead.pk}-summary": "Descriere suficientă pentru o ofertă încă incompletă.",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Completează această poziție.")
        self.assertFalse(ProviderQuote.objects.exists())

    def test_customer_cannot_review_before_accepting_an_offer(self):
        """Possession of the private link alone does not make a review eligible."""

        self.client.post(self.url, self.valid_payload)
        access_url = re.search(
            r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body
        ).group(0)
        access_path = access_url.removeprefix("http://testserver")

        response = self.client.post(
            access_path,
            {
                "action": "review",
                "customer-review-rating": "5",
                "customer-review-body": (
                    "Această recenzie are suficient text, dar oferta nu a fost acceptată."
                ),
                "customer-review-consent": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "după acceptarea unei oferte")
        self.assertFalse(ProviderCustomerReview.objects.exists())

    def test_customer_and_provider_can_exchange_private_messages(self):
        """Conversation is append-only and each participant sees the same thread."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        access_url = re.search(r"https?://[^\s]+/solicitari/[^\s]+", mail.outbox[1].body).group(0)
        access_path = access_url.removeprefix("http://testserver")
        response = self.client.post(
            access_path,
            {"action": "message", "customer-message-body": "Puteți include și evacuarea molozului?"},
        )
        self.assertRedirects(response, access_path)
        self.assertIn(f"focus={lead.public_id}", mail.outbox[-1].body)
        self.assertNotIn("evacuarea molozului", mail.outbox[-1].body)

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("services:provider_leads"),
            {
                "lead_id": lead.pk,
                "action": "message",
                f"message-{lead.pk}-body": "Da, evacuarea este inclusă în estimare.",
            },
        )
        self.assertRedirects(response, reverse("services:provider_leads"))
        self.assertEqual(
            list(ProviderLeadMessage.objects.values_list("sender_role", flat=True)),
            ["customer", "provider"],
        )

    def test_owner_manages_private_customer_register_without_creating_account_or_email(self):
        """Manual CRM contacts stay provider-private and require explicit transitions."""

        self.client.force_login(self.owner)
        url = reverse("services:provider_leads")
        sent_before = len(mail.outbox)
        accounts_before = CustomerAccount.objects.count()
        create_response = self.client.post(url, {
            "action": "customer_save",
            "customer-expected_revision": "0",
            "customer-name": "  Dan   Ionescu ",
            "customer-email": "DAN@EXAMPLE.TEST",
            "customer-phone": "",
            "customer-address": "Copou, Iași",
            "customer-notes": "Preferă programări dimineața.",
            "customer-lawful_use_confirmed": "on",
        })
        self.assertRedirects(create_response, url + "?view=customers")
        customer = ProviderCRMCustomer.objects.get()
        self.assertEqual(customer.profile, self.profile)
        self.assertEqual(customer.name, "Dan Ionescu")
        self.assertEqual(customer.email, "dan@example.test")
        self.assertEqual(customer.revision, 1)
        self.assertEqual(customer.events.get().action, ProviderCRMCustomerEvent.Action.CREATED)
        self.assertEqual(CustomerAccount.objects.count(), accounts_before)
        self.assertEqual(len(mail.outbox), sent_before)

        page = self.client.get(url + f"?view=customers&edit={customer.pk}")
        self.assertContains(page, "Dan Ionescu")
        self.assertContains(page, "Editează clientul")
        update_response = self.client.post(url, {
            "action": "customer_save",
            "customer-expected_revision": "1",
            "customer-customer_id": str(customer.pk),
            "customer-name": "Dan Ionescu",
            "customer-email": "dan@example.test",
            "customer-phone": "0712 345 678",
            "customer-address": "Copou, Iași",
            "customer-notes": "Disponibil după ora 09:00.",
            "customer-lawful_use_confirmed": "on",
        })
        self.assertRedirects(update_response, url + "?view=customers")
        customer.refresh_from_db()
        self.assertEqual(customer.revision, 2)
        self.assertEqual(customer.phone, "0712 345 678")

        archive_response = self.client.post(url, {
            "action": "customer_archive",
            "archive-customer-customer_id": str(customer.pk),
            "archive-customer-expected_revision": "2",
            "archive-customer-confirmed": "on",
        })
        self.assertRedirects(archive_response, url + "?view=customers")
        customer.refresh_from_db()
        self.assertEqual(customer.state, ProviderCRMCustomer.State.ARCHIVED)
        self.assertIsNotNone(customer.archived_at)
        self.assertEqual(customer.revision, 3)
        self.assertEqual(customer.events.count(), 3)

    def test_owner_explicitly_links_and_unlinks_private_customer_from_request(self):
        """The register picker links records without rewriting request contact data."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        customer = ProviderCRMCustomer.objects.create(
            profile=self.profile,
            name="Maria din registru",
            email="maria@example.test",
            phone="0712 000 111",
            created_by=self.owner,
            updated_by=self.owner,
        )
        original_contact = (lead.customer_name, lead.customer_email, lead.customer_phone)
        self.client.force_login(self.owner)
        picker = self.client.get(
            reverse("services:provider_leads")
            + f"?view=customers&link_lead={lead.public_id}"
        )
        self.assertContains(picker, "Alege fișa corectă")
        self.assertContains(picker, "Maria din registru")

        response = self.client.post(reverse("services:provider_leads"), {
            "action": "customer_link",
            "lead_id": str(lead.pk),
            "customer-link-lead_id": str(lead.pk),
            "customer-link-customer_id": str(customer.pk),
            "customer-link-expected_revision": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            reverse("services:provider_leads")
            + f"?view=requests&focus={lead.public_id}",
        )
        lead.refresh_from_db()
        self.assertEqual(lead.crm_customer, customer)
        self.assertEqual(lead.crm_customer_revision, 1)
        self.assertEqual(
            (lead.customer_name, lead.customer_email, lead.customer_phone),
            original_contact,
        )
        event = ProviderLeadCustomerLinkEvent.objects.get()
        self.assertIsNone(event.previous_customer)
        self.assertEqual(event.new_customer, customer)
        self.assertEqual(event.actor, self.owner)

        stale_response = self.client.post(reverse("services:provider_leads"), {
            "action": "customer_link",
            "lead_id": str(lead.pk),
            "customer-link-lead_id": str(lead.pk),
            "customer-link-customer_id": "",
            "customer-link-expected_revision": "0",
        })
        self.assertEqual(stale_response.status_code, 302)
        lead.refresh_from_db()
        self.assertEqual(lead.crm_customer, customer)

        self.client.post(reverse("services:provider_leads"), {
            "action": "customer_link",
            "lead_id": str(lead.pk),
            "customer-link-lead_id": str(lead.pk),
            "customer-link-customer_id": "",
            "customer-link-expected_revision": "1",
        })
        lead.refresh_from_db()
        self.assertIsNone(lead.crm_customer)
        self.assertEqual(lead.crm_customer_revision, 2)
        self.assertEqual(ProviderLeadCustomerLinkEvent.objects.count(), 2)

    def test_owner_creates_and_links_private_customer_from_request(self):
        """Reviewed request data can seed one contact without account or e-mail side effects."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        original_contact = (lead.customer_name, lead.customer_email, lead.customer_phone)
        accounts_before = CustomerAccount.objects.count()
        sent_before = len(mail.outbox)
        self.client.force_login(self.owner)
        create_page = self.client.get(
            reverse("services:provider_leads")
            + f"?view=customers&new_for_lead={lead.public_id}"
        )
        self.assertContains(create_page, "Creează fișa clientului")
        self.assertContains(create_page, f'value="{lead.customer_name}"')
        self.assertContains(create_page, f'value="{lead.customer_email}"')

        response = self.client.post(reverse("services:provider_leads"), {
            "action": "customer_create_from_lead",
            "lead_id": str(lead.pk),
            "customer-expected_revision": "0",
            "customer-lead_id": str(lead.pk),
            "customer-expected_link_revision": "0",
            "customer-name": lead.customer_name,
            "customer-email": lead.customer_email,
            "customer-phone": lead.customer_phone,
            "customer-address": lead.project_address,
            "customer-notes": "Preferă confirmarea telefonică.",
            "customer-lawful_use_confirmed": "on",
        })

        self.assertEqual(response.status_code, 302)
        customer = ProviderCRMCustomer.objects.get()
        lead.refresh_from_db()
        self.assertEqual(lead.crm_customer, customer)
        self.assertEqual(lead.crm_customer_revision, 1)
        self.assertEqual(
            (lead.customer_name, lead.customer_email, lead.customer_phone),
            original_contact,
        )
        self.assertEqual(customer.events.get().action, ProviderCRMCustomerEvent.Action.CREATED)
        self.assertEqual(ProviderLeadCustomerLinkEvent.objects.get().new_customer, customer)
        self.assertEqual(CustomerAccount.objects.count(), accounts_before)
        self.assertEqual(len(mail.outbox), sent_before)

    def test_customer_creation_from_request_rolls_back_after_stale_link(self):
        """A stale association revision cannot leave an unlinked contact behind."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        lead.crm_customer_revision = 1
        lead.save(update_fields=("crm_customer_revision",))
        self.client.force_login(self.owner)

        response = self.client.post(reverse("services:provider_leads"), {
            "action": "customer_create_from_lead",
            "lead_id": str(lead.pk),
            "customer-expected_revision": "0",
            "customer-lead_id": str(lead.pk),
            "customer-expected_link_revision": "0",
            "customer-name": lead.customer_name,
            "customer-email": lead.customer_email,
            "customer-phone": lead.customer_phone,
            "customer-address": "",
            "customer-notes": "",
            "customer-lawful_use_confirmed": "on",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProviderCRMCustomer.objects.exists())
        self.assertFalse(ProviderLeadCustomerLinkEvent.objects.exists())

    def test_linked_request_prepares_quote_without_persisting_or_sending(self):
        """A linked CRM record opens a reviewable form, never a sent offer."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        customer = ProviderCRMCustomer.objects.create(
            profile=self.profile,
            name="Maria din registru",
            email="registru@example.test",
            phone="0712 000 111",
            created_by=self.owner,
            updated_by=self.owner,
        )
        lead.crm_customer = customer
        lead.crm_customer_revision = 1
        lead.save(update_fields=("crm_customer", "crm_customer_revision"))
        sent_before = len(mail.outbox)
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("services:provider_leads")
            + f"?view=requests&offer_for={lead.public_id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ofertă pregătită din solicitarea asociată")
        self.assertContains(response, "Maria din registru")
        self.assertContains(response, lead.description)
        self.assertContains(response, lead.customer_email)
        self.assertContains(response, 'class="provider-lead-workspace" open')
        self.assertFalse(ProviderQuote.objects.exists())
        self.assertEqual(len(mail.outbox), sent_before)

        lead.crm_customer = None
        lead.save(update_fields=("crm_customer",))
        rejected = self.client.get(
            reverse("services:provider_leads")
            + f"?view=requests&offer_for={lead.public_id}"
        )
        self.assertEqual(rejected.status_code, 404)

    def test_customer_link_rejects_archived_contact_ids(self):
        """Only an active contact from the lead owner's register is linkable."""

        self.client.post(self.url, self.valid_payload)
        lead = ProviderLead.objects.get()
        customer = ProviderCRMCustomer.objects.create(
            profile=self.profile,
            name="Client arhivat",
            email="arhivat@example.test",
            state=ProviderCRMCustomer.State.ARCHIVED,
            archived_at=timezone.now(),
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("services:provider_leads"), {
            "action": "customer_link",
            "lead_id": str(lead.pk),
            "customer-link-lead_id": str(lead.pk),
            "customer-link-customer_id": str(customer.pk),
            "customer-link-expected_revision": "0",
        })
        self.assertEqual(response.status_code, 404)
        lead.refresh_from_db()
        self.assertIsNone(lead.crm_customer)
        self.assertFalse(ProviderLeadCustomerLinkEvent.objects.exists())

    def test_customer_register_rejects_duplicate_email_and_foreign_provider_access(self):
        """One provider cannot duplicate or read another provider's private contact."""

        ProviderCRMCustomer.objects.create(
            profile=self.profile,
            name="Ana Ionescu",
            email="ana@example.test",
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.client.force_login(self.owner)
        url = reverse("services:provider_leads")
        response = self.client.post(url, {
            "action": "customer_save",
            "customer-expected_revision": "0",
            "customer-name": "Altă Ana",
            "customer-email": "ANA@EXAMPLE.TEST",
            "customer-phone": "0712 000 000",
            "customer-address": "",
            "customer-notes": "",
            "customer-lawful_use_confirmed": "on",
        })
        self.assertRedirects(response, url + "?view=customers")
        self.assertEqual(ProviderCRMCustomer.objects.count(), 1)

        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(url + "?view=customers").status_code, 403)
