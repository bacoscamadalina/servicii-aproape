"""Fail-safe data-retention audit and controlled minimization contracts."""

from datetime import timedelta
from io import StringIO
import json

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from .data_retention import (
    APPLY_ACKNOWLEDGEMENT,
    REDACTED_CLAIM_TEXT,
    REDACTED_LEAD_TEXT,
    REDACTED_MANAGED_SITE_TEXT,
    REDACTED_REPORT_TEXT,
    apply_data_retention,
    data_retention_snapshot,
)
from .locations import SIRUTA_CATALOGUE_VERSION, siruta_catalogue_sha256
from .models import (
    AccountLoginThrottle,
    CustomerAccount,
    DataSubjectRequest,
    DataSubjectRequestEvent,
    ProviderClaimRequest,
    ProviderEngagementEvent,
    ManagedSiteInquiry,
    ManagedSiteInquiryEvent,
    ProviderLead,
    ProviderLeadCustomerLinkEvent,
    ProviderCRMCustomer,
    ProviderLeadBatch,
    ProviderLeadMessage,
    ProviderPasswordResetThrottle,
    ProviderPublicationSubmission,
    ProviderQuote,
    ProviderQuoteLine,
    ProviderVisitProposal,
    ProviderWorkOrder,
    ProviderInvoiceDraft,
    ProviderRegistrationRequest,
    PublicProviderReport,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
)
from .provider_offerings import (
    REVIEW_ACKNOWLEDGEMENT,
    replace_provider_services_and_coverage_for_owner,
    review_provider_service_area_submission,
    submit_provider_service_area_for_review,
)
from .provider_leads import (
    _batch_access_digest,
    provider_lead_batch_for_customer,
    provider_lead_batch_for_customer_account,
)
from .retention_integrity import audit_retention_integrity
from .test_provider_offerings import ProviderOfferingFixtureMixin
from .test_representation_evidence import create_representation_evidence


@override_settings(
    RETENTION_UNVERIFIED_CLAIM_DAYS=30,
    RETENTION_REJECTED_CLAIM_DAYS=365,
    RETENTION_CLOSED_REPORT_DAYS=365,
    RETENTION_CLOSED_PROVIDER_LEAD_DAYS=365,
    RETENTION_MANAGED_SITE_INQUIRY_DAYS=365,
)
class DataRetentionTests(ProviderOfferingFixtureMixin, TestCase):
    """Prove retention is bounded, identity-free, idempotent and state-aware."""

    def setUp(self):
        self.create_fixture()
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_service_area")
        )
        self.now = timezone.now()
        self.old_managed_site_inquiry = ManagedSiteInquiry.objects.create(
            profile=self.profile,
            created_by=self.owner,
            goal=ManagedSiteInquiry.Goal.NEW_PRESENCE,
            desired_launch=ManagedSiteInquiry.DesiredLaunch.SIXTY_DAYS,
            current_website="https://vechi.example.test",
            brief="Brief privat care trebuie eliminat după perioada declarată.",
            privacy_notice_version="test",
            consented_at=self.now - timedelta(days=366),
        )
        ManagedSiteInquiry.objects.filter(pk=self.old_managed_site_inquiry.pk).update(
            created_at=self.now - timedelta(days=366)
        )
        self.old_managed_site_event = ManagedSiteInquiryEvent.objects.create(
            inquiry=self.old_managed_site_inquiry,
            previous_status=ManagedSiteInquiry.Status.RECEIVED,
            new_status=ManagedSiteInquiry.Status.CONTACTED,
            revision=1,
            internal_note="Notă operațională despre discuția cu furnizorul.",
            policy_version="test",
            acknowledgement="test",
            actor=self.reviewer,
        )
        self.old_unverified = self.create_claim(
            "email_pending", "unverified@example.test", "3", days_old=31
        )
        self.old_superseded = self.create_claim(
            "superseded", "superseded@example.test", "4", days_old=31
        )
        self.old_rejected = self.create_claim(
            "rejected", "rejected@example.test", "5", days_old=366
        )
        self.stale_review = self.create_claim(
            "review_pending", "review@example.test", "6", days_old=366
        )
        self.recent_unverified = self.create_claim(
            "email_pending", "recent@example.test", "7", days_old=2
        )
        for claim in (
            self.old_unverified,
            self.old_superseded,
            self.old_rejected,
            self.stale_review,
            self.recent_unverified,
        ):
            create_representation_evidence(claim=claim)
        self.closed_report = self.create_report(closed=True, days_old=366)
        self.expired_engagement = ProviderEngagementEvent.objects.create(
            submission=self.closed_report.submission,
            event_type=ProviderEngagementEvent.EventType.PROFILE_VIEW,
            visitor_session_digest="a" * 64,
            occurred_on=timezone.localdate(self.now) - timedelta(days=90),
        )
        self.window_edge_engagement = ProviderEngagementEvent.objects.create(
            submission=self.closed_report.submission,
            event_type=ProviderEngagementEvent.EventType.PROFILE_VIEW,
            visitor_session_digest="b" * 64,
            occurred_on=timezone.localdate(self.now) - timedelta(days=89),
        )
        self.open_report = self.create_report(
            closed=False,
            days_old=366,
            digest="9" * 64,
            submission=self.closed_report.submission,
        )
        self.closed_data_request = self.create_closed_data_request()
        self.closed_lead = ProviderLead.objects.create(
            submission=self.closed_report.submission,
            category="constructii",
            county="Iași",
            siruta_code="95079",
            customer_name="Client Retenție",
            customer_email="client@example.test",
            customer_phone="0712 111 222",
            project_address="Adresă privată",
            description="Descriere privată suficientă pentru solicitarea lucrării.",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            status=ProviderLead.Status.COMPLETED,
            owner_notes="Notă privată despre client.",
            visitor_session_digest="d" * 64,
            privacy_notice_version="test",
            customer_access_digest="e" * 64,
            customer_access_expires_at=self.now + timedelta(days=30),
        )
        self.closed_message = ProviderLeadMessage.objects.create(
            lead=self.closed_lead,
            sender_role=ProviderLeadMessage.SenderRole.CUSTOMER,
            body="Mesaj privat despre proiect.",
        )
        self.closed_quote = ProviderQuote.objects.create(
            lead=self.closed_lead,
            revision=1,
            amount_ron="12000.00",
            summary="Ofertă privată cu detalii despre proiect.",
            estimated_duration="Trei săptămâni",
            valid_until=self.now.date() + timedelta(days=14),
            sent_by=self.reviewer,
        )
        self.closed_quote_line = ProviderQuoteLine.objects.create(
            quote=self.closed_quote,
            position=1,
            description="Poziție privată cu materialele clientului.",
            quantity="1.00",
            unit="lucrare",
            unit_price_ron="12000.00",
        )
        ProviderLead.objects.filter(pk=self.closed_lead.pk).update(
            updated_at=self.now - timedelta(days=366)
        )
        ProviderPasswordResetThrottle.objects.create(
            key_digest="a" * 64,
            window_started_at=self.now - timedelta(hours=25),
            send_count=1,
        )
        ProviderPasswordResetThrottle.objects.create(
            key_digest="b" * 64,
            window_started_at=self.now - timedelta(hours=1),
            send_count=1,
        )
        AccountLoginThrottle.objects.create(
            key_digest="c" * 64,
            window_started_at=self.now - timedelta(hours=25),
            attempt_count=1,
        )

    def create_closed_data_request(self):
        """Create a closed request old enough for configured minimization."""

        received = self.now - timedelta(days=1130)
        item = DataSubjectRequest.objects.create(
            request_kind=DataSubjectRequest.Kind.ACCESS,
            channel=DataSubjectRequest.Channel.EMAIL,
            requester_name="Persoană GDPR Test",
            contact_email="gdpr@example.test",
            details="Solicită acces la datele sale personale.",
            status=DataSubjectRequest.Status.FULFILLED,
            revision=2,
            received_at=received,
            due_at=received + timedelta(days=30),
            identity_verified_at=received + timedelta(days=1),
            closed_at=self.now - timedelta(days=1096),
            recorded_by=self.reviewer,
        )
        DataSubjectRequestEvent.objects.create(
            request=item,
            action=DataSubjectRequestEvent.Action.STATUS_TRANSITION,
            previous_status=DataSubjectRequest.Status.RECEIVED,
            new_status=DataSubjectRequest.Status.IN_REVIEW,
            revision=1,
            internal_note="Identitate confirmată pentru test.",
            policy_version="test",
            acknowledgement="test",
            actor=self.reviewer,
        )
        DataSubjectRequestEvent.objects.create(
            request=item,
            action=DataSubjectRequestEvent.Action.STATUS_TRANSITION,
            previous_status=DataSubjectRequest.Status.IN_REVIEW,
            new_status=DataSubjectRequest.Status.FULFILLED,
            revision=2,
            internal_note="Cerere soluționată pentru test.",
            policy_version="test",
            acknowledgement="test",
            actor=self.reviewer,
        )
        return item

    def create_claim(self, status, email, token_character, *, days_old):
        """Create a constraint-valid claim and move its immutable clock for policy tests."""

        reviewed = status == ProviderClaimRequest.Status.REJECTED
        verified = reviewed or status == ProviderClaimRequest.Status.REVIEW_PENDING
        claim = ProviderClaimRequest.objects.create(
            business=self.business,
            legal_name_at_request="Date personale test SRL",
            contact_name="Persoană Test",
            role="administrator",
            email=email,
            status=status,
            token_digest=token_character * 64,
            token_expires_at=self.now - timedelta(days=days_old),
            email_verified_at=self.now if verified else None,
            privacy_notice_version="test",
            consented_at=self.now - timedelta(days=days_old),
            reviewed_at=self.now - timedelta(days=days_old) if reviewed else None,
            reviewed_by=self.reviewer if reviewed else None,
            review_note="Notă privată" if reviewed else "",
            approval_policy_version="test" if reviewed else "",
        )
        ProviderClaimRequest.objects.filter(pk=claim.pk).update(
            created_at=self.now - timedelta(days=days_old)
        )
        claim.refresh_from_db()
        return claim

    def create_report(
        self, *, closed, days_old, digest="8" * 64, submission=None
    ):
        """Create the smallest valid publication/report graph for retention."""

        if submission is None:
            replace_provider_services_and_coverage_for_owner(
                user=self.owner,
                expected_revision=0,
                categories=["constructii"],
                coverage_pairs=[("Iași", "95079")],
            )
            service_submission, _ = submit_provider_service_area_for_review(
                user=self.owner,
                expected_revision=self.profile.service_area_draft.revision,
            )
            review_provider_service_area_submission(
                submission_id=service_submission.pk,
                reviewer=self.reviewer,
                decision=service_submission.Decision.APPROVED,
                internal_note="Verificat pentru test.",
                provider_feedback="",
                acknowledgement=REVIEW_ACKNOWLEDGEMENT,
            )
            submission = ProviderPublicationSubmission.objects.create(
                profile=self.profile,
                version=1,
                profile_content_revision=self.profile.public_content_revision,
                display_name="Profil retenție",
                service_area_submission=service_submission,
                authorization_run=self.base,
                catalogue_run=self.current,
                siruta_catalogue_version=SIRUTA_CATALOGUE_VERSION,
                siruta_catalogue_sha256=siruta_catalogue_sha256(),
                contract_sha256="1" * 64,
                submitted_by=self.owner,
            )
        report = PublicProviderReport.objects.create(
            submission=submission,
            reason=PublicProviderReport.Reason.OTHER,
            details="Text liber cu date personale de test.",
            reporter_session_digest=digest,
        )
        case = PublicProviderReportCase.objects.create(
            report=report,
            state=(
                PublicProviderReportCase.State.CLOSED
                if closed
                else PublicProviderReportCase.State.NEW
            ),
            outcome=(
                PublicProviderReportCase.Outcome.INSUFFICIENT_INFORMATION
                if closed
                else ""
            ),
        )
        PublicProviderReportCase.objects.filter(pk=case.pk).update(
            updated_at=self.now - timedelta(days=days_old)
        )
        return report

    def test_snapshot_is_read_only_and_counts_only_eligible_states(self):
        snapshot = data_retention_snapshot(now=self.now)

        self.assertEqual(
            snapshot["eligible"],
            {
                "unverified_claims": 2,
                "rejected_claims": 1,
                "unverified_registrations": 0,
                "rejected_registrations": 0,
                "closed_reports": 1,
                "closed_data_requests": 1,
                "closed_provider_leads": 1,
                "retained_lead_batches": 0,
                "managed_site_inquiries": 1,
                "provider_engagement_events": 1,
                "password_reset_throttles": 1,
                "login_throttles": 1,
            },
        )
        self.assertEqual(snapshot["manual_review"]["stale_claims_in_review"], 1)
        self.assertEqual(snapshot["manual_review"]["stale_registrations_in_review"], 0)
        self.old_unverified.refresh_from_db()
        self.assertIsNone(self.old_unverified.retention_applied_at)

    def test_apply_requires_exact_acknowledgement_and_is_idempotent(self):
        private_customer = ProviderCRMCustomer.objects.create(
            profile=self.profile, name="Client privat", email="client@example.test",
            created_by=self.owner, updated_by=self.owner,
        )
        self.closed_lead.crm_customer = private_customer
        self.closed_lead.crm_customer_revision = 1
        self.closed_lead.save(update_fields=("crm_customer", "crm_customer_revision"))
        ProviderLeadCustomerLinkEvent.objects.create(
            lead=self.closed_lead, revision=1, new_customer=private_customer,
            actor=self.owner,
        )
        ProviderQuote.objects.filter(pk=self.closed_quote.pk).update(
            status=ProviderQuote.Status.ACCEPTED, responded_at=self.now - timedelta(days=365),
        )
        private_work_order = ProviderWorkOrder.objects.create(
            lead=self.closed_lead, accepted_quote=self.closed_quote,
        )
        private_invoice_draft = ProviderInvoiceDraft.objects.create(
            work_order=private_work_order, amount_ron="7500.00",
            description="Descriere privată pentru ciorna de facturare.", updated_by=self.owner,
        )
        private_visit = ProviderVisitProposal.objects.create(
            lead=self.closed_lead,
            starts_at=self.now - timedelta(days=365),
            note="Adresă privată pentru vizită",
        )
        with self.assertRaisesMessage(ValueError, "Confirmarea exactă"):
            apply_data_retention(acknowledgement="", now=self.now)

        result = apply_data_retention(
            acknowledgement=APPLY_ACKNOWLEDGEMENT,
            batch_size=1,
            now=self.now,
        )
        self.assertEqual(result["applied"]["unverified_claims"], 2)
        self.assertEqual(result["applied"]["rejected_claims"], 1)
        self.assertEqual(result["applied"]["unverified_registrations"], 0)
        self.assertEqual(result["applied"]["rejected_registrations"], 0)
        self.assertEqual(result["applied"]["closed_reports"], 1)
        self.assertEqual(result["applied"]["closed_data_requests"], 1)
        self.assertEqual(result["applied"]["closed_provider_leads"], 1)
        self.assertEqual(result["applied"]["retained_lead_batches"], 0)
        self.assertEqual(result["applied"]["managed_site_inquiries"], 1)
        self.assertEqual(result["applied"]["provider_engagement_events"], 1)
        self.assertFalse(
            ProviderEngagementEvent.objects.filter(pk=self.expired_engagement.pk).exists()
        )
        self.assertTrue(
            ProviderEngagementEvent.objects.filter(pk=self.window_edge_engagement.pk).exists()
        )
        for claim in (self.old_unverified, self.old_superseded, self.old_rejected):
            claim.refresh_from_db()
            self.assertEqual(claim.contact_name, REDACTED_CLAIM_TEXT)
            self.assertTrue(claim.email.endswith("@retention.invalid"))
            self.assertIsNotNone(claim.retention_applied_at)
            self.assertFalse(hasattr(claim, "representation_evidence"))
        for untouched in (self.stale_review, self.recent_unverified):
            untouched.refresh_from_db()
            self.assertEqual(untouched.contact_name, "Persoană Test")
            self.assertIsNone(untouched.retention_applied_at)
            self.assertTrue(hasattr(untouched, "representation_evidence"))
        self.profile.approved_claim.refresh_from_db()
        self.assertEqual(self.profile.approved_claim.email, "owner@example.test")

        self.closed_report.refresh_from_db()
        self.open_report.refresh_from_db()
        self.assertEqual(self.closed_report.details, REDACTED_REPORT_TEXT)
        self.assertEqual(self.open_report.details, "Text liber cu date personale de test.")
        self.assertEqual(ProviderPasswordResetThrottle.objects.count(), 1)
        self.assertFalse(AccountLoginThrottle.objects.exists())
        self.closed_data_request.refresh_from_db()
        self.assertEqual(
            self.closed_data_request.requester_name,
            "Eliminat conform politicii de retenție.",
        )
        self.assertEqual(
            self.closed_data_request.events.get(revision=1).internal_note,
            "Eliminat conform politicii de retenție.",
        )
        self.closed_lead.refresh_from_db()
        self.assertEqual(self.closed_lead.customer_name, REDACTED_LEAD_TEXT)
        self.assertEqual(self.closed_lead.description, REDACTED_LEAD_TEXT)
        self.assertEqual(self.closed_lead.owner_notes, "")
        self.assertIsNone(self.closed_lead.customer_access_digest)
        self.assertIsNone(self.closed_lead.customer_access_expires_at)
        self.assertIsNone(self.closed_lead.crm_customer)
        self.assertFalse(
            ProviderLeadCustomerLinkEvent.objects.filter(lead=self.closed_lead).exists()
        )
        self.assertFalse(ProviderLeadMessage.objects.filter(pk=self.closed_message.pk).exists())
        self.assertFalse(ProviderVisitProposal.objects.filter(pk=private_visit.pk).exists())
        self.assertFalse(ProviderWorkOrder.objects.filter(pk=private_work_order.pk).exists())
        self.assertFalse(ProviderInvoiceDraft.objects.filter(pk=private_invoice_draft.pk).exists())
        self.closed_quote.refresh_from_db()
        self.assertEqual(self.closed_quote.summary, REDACTED_LEAD_TEXT)
        self.assertEqual(self.closed_quote.estimated_duration, REDACTED_LEAD_TEXT)
        self.closed_quote_line.refresh_from_db()
        self.assertEqual(self.closed_quote_line.description, REDACTED_LEAD_TEXT)
        self.assertIsNotNone(self.closed_lead.retention_applied_at)
        self.old_managed_site_inquiry.refresh_from_db()
        self.assertEqual(
            self.old_managed_site_inquiry.brief, REDACTED_MANAGED_SITE_TEXT
        )
        self.assertEqual(self.old_managed_site_inquiry.current_website, "")
        self.old_managed_site_event.refresh_from_db()
        self.assertEqual(
            self.old_managed_site_event.internal_note, REDACTED_MANAGED_SITE_TEXT
        )
        self.assertIsNotNone(self.old_managed_site_inquiry.retention_applied_at)
        second = apply_data_retention(
            acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now
        )
        self.assertTrue(all(count == 0 for count in second["applied"].values()))
        self.assertTrue(audit_retention_integrity().is_valid)

    def test_closed_customer_projects_lose_account_and_batch_capability_links(self):
        """Retain a batch only after every recipient copy has aged out."""

        customer = get_user_model().objects.create_user(
            username="customer-retention", email="customer-retention@example.test"
        )
        account = CustomerAccount.objects.create(
            user=customer,
            normalized_email="customer-retention@example.test",
            privacy_notice_version="test",
        )
        self.closed_lead.customer_account = account
        self.closed_lead.save(update_fields=("customer_account",))
        old_token = "retention-link-token"
        old_digest = _batch_access_digest(old_token)
        batch = ProviderLeadBatch.objects.create(
            category="constructii",
            county="Iași",
            siruta_code="95079",
            visitor_session_digest="6" * 64,
            privacy_notice_version="test",
            customer_access_digest=old_digest,
            customer_access_expires_at=self.now + timedelta(days=30),
            customer_account=account,
        )
        closed_child = ProviderLead.objects.create(
            submission=self.closed_report.submission,
            batch=batch,
            customer_account=account,
            category="constructii",
            county="Iași",
            siruta_code="95079",
            customer_name="Client comparație",
            customer_email="customer-retention@example.test",
            customer_phone="0712 999 888",
            description="Descrierea unui proiect comparat închis.",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            status=ProviderLead.Status.DECLINED,
            visitor_session_digest="7" * 64,
            privacy_notice_version="test",
        )
        ProviderLead.objects.filter(pk=closed_child.pk).update(
            updated_at=self.now - timedelta(days=366)
        )
        active_batch = ProviderLeadBatch.objects.create(
            category="constructii",
            county="Iași",
            siruta_code="95079",
            visitor_session_digest="8" * 64,
            privacy_notice_version="test",
            customer_access_digest="9" * 64,
            customer_access_expires_at=self.now + timedelta(days=30),
            customer_account=account,
        )
        ProviderLead.objects.create(
            submission=self.closed_report.submission,
            batch=active_batch,
            customer_account=account,
            category="constructii",
            county="Iași",
            siruta_code="95079",
            customer_name="Client activ",
            customer_email="customer-retention@example.test",
            customer_phone="0712 999 888",
            description="Descrierea unei solicitări încă active.",
            desired_start=ProviderLead.DesiredStart.FLEXIBLE,
            visitor_session_digest="a" * 64,
            privacy_notice_version="test",
        )

        self.assertTrue(
            provider_lead_batch_for_customer(
                public_id=batch.public_id, token=old_token
            )
        )

        snapshot = data_retention_snapshot(now=self.now)
        self.assertEqual(snapshot["eligible"]["closed_provider_leads"], 2)
        self.assertEqual(snapshot["eligible"]["retained_lead_batches"], 1)
        applied = apply_data_retention(
            acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now, batch_size=1
        )
        self.assertEqual(applied["applied"]["retained_lead_batches"], 1)
        self.closed_lead.refresh_from_db()
        closed_child.refresh_from_db()
        batch.refresh_from_db()
        active_batch.refresh_from_db()
        self.assertIsNone(self.closed_lead.customer_account_id)
        self.assertIsNone(closed_child.customer_account_id)
        self.assertIsNone(batch.customer_account_id)
        self.assertNotEqual(batch.customer_access_digest, old_digest)
        self.assertIsNotNone(batch.retention_applied_at)
        self.assertEqual(active_batch.customer_account_id, account.pk)
        self.assertIsNone(active_batch.retention_applied_at)
        with self.assertRaises(ProviderLeadBatch.DoesNotExist):
            provider_lead_batch_for_customer_account(
                public_id=batch.public_id, customer_account=account
            )
        with self.assertRaises(ProviderLeadBatch.DoesNotExist):
            provider_lead_batch_for_customer(
                public_id=batch.public_id, token=old_token
            )
        self.assertTrue(
            provider_lead_batch_for_customer_account(
                public_id=active_batch.public_id, customer_account=account
            )
        )
        self.assertTrue(audit_retention_integrity().is_valid)
        ProviderLeadBatch.objects.filter(pk=batch.pk).update(
            visitor_session_digest="b" * 64
        )
        self.assertEqual(
            audit_retention_integrity().as_dict()["anomalies"]["retained_batch_exposed"],
            1,
        )
        ProviderLead.objects.filter(pk=closed_child.pk).update(retention_applied_at=None)
        self.assertEqual(
            audit_retention_integrity().as_dict()["anomalies"]["retained_batch_has_live_lead"],
            1,
        )

    def test_retention_integrity_audit_is_read_only_and_detects_exposed_text(self):
        """Detect drift without including project text in the report."""

        apply_data_retention(acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now)
        output = StringIO()
        call_command("audit_retention_integrity", stdout=output)
        self.assertEqual(json.loads(output.getvalue())["totals"]["retained_leads"], 1)
        ProviderLead.objects.filter(pk=self.closed_lead.pk).update(
            description="Text sensibil rămas în cerere"
        )
        report = audit_retention_integrity().as_dict()
        self.assertEqual(report["anomalies"]["retained_lead_exposed"], 1)
        self.assertNotIn("Text sensibil", json.dumps(report))
        ProviderLeadMessage.objects.create(
            lead=self.closed_lead,
            sender_role=ProviderLeadMessage.SenderRole.CUSTOMER,
            body="Mesaj rămas din conversație",
        )
        ProviderQuote.objects.filter(pk=self.closed_quote.pk).update(
            summary="Ofertă rămasă din conversație"
        )
        report = audit_retention_integrity().as_dict()
        self.assertEqual(report["anomalies"]["retained_lead_messages_present"], 1)
        self.assertEqual(report["anomalies"]["retained_lead_quotes_exposed"], 1)
        private_customer = ProviderCRMCustomer.objects.create(
            profile=self.profile, name="Legătură rămasă", email="link@example.test",
            created_by=self.owner, updated_by=self.owner,
        )
        ProviderLead.objects.filter(pk=self.closed_lead.pk).update(
            crm_customer=private_customer, crm_customer_revision=1,
        )
        ProviderLeadCustomerLinkEvent.objects.create(
            lead=self.closed_lead, revision=1, new_customer=private_customer,
            actor=self.owner,
        )
        report = audit_retention_integrity().as_dict()
        self.assertEqual(report["anomalies"]["retained_lead_exposed"], 1)
        self.assertEqual(report["anomalies"]["retained_lead_customer_links_present"], 1)
        with self.assertRaises(CommandError):
            call_command("audit_retention_integrity", stdout=StringIO())

    def test_retained_identity_requests_are_checked_for_documents_and_contact(self):
        """A retention marker cannot conceal a restored representation document."""

        registration = ProviderRegistrationRequest.objects.create(
            legal_name="Firma privată SRL",
            cui="RO12345678",
            registration_number="J22/1234/2026",
            registered_county="Iași",
            registered_office_siruta="95079",
            contact_name="Persoană Test",
            role="administrator",
            email="registration@example.test",
            token_digest="q" * 64,
            token_expires_at=self.now - timedelta(days=31),
            privacy_notice_version="test",
            consented_at=self.now - timedelta(days=31),
        )
        ProviderRegistrationRequest.objects.filter(pk=registration.pk).update(
            created_at=self.now - timedelta(days=31)
        )
        create_representation_evidence(registration=registration)

        apply_data_retention(acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now)
        audit = audit_retention_integrity()
        self.assertTrue(audit.is_valid)
        self.assertEqual(audit.retained_claims, 3)
        self.assertEqual(audit.retained_registrations, 1)

        create_representation_evidence(claim=self.old_unverified)
        ProviderRegistrationRequest.objects.filter(pk=registration.pk).update(
            email="registration@example.test"
        )
        anomalies = audit_retention_integrity().as_dict()["anomalies"]
        self.assertEqual(anomalies["retained_claim_exposed"], 1)
        self.assertEqual(anomalies["retained_registration_exposed"], 1)

    def test_retained_report_notes_are_minimized_and_legacy_drift_is_repairable(self):
        """A previously retained report can re-enter the guarded batch for old notes."""

        note = PublicProviderReportTriageEvent.objects.create(
            case=self.closed_report.triage_case,
            previous_state=PublicProviderReportCase.State.NEW,
            new_state=PublicProviderReportCase.State.IN_REVIEW,
            revision=1,
            internal_note="Notă internă cu date despre persoană.",
            policy_version="test",
            acknowledgement="test",
            actor=self.reviewer,
        )
        apply_data_retention(acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now)
        note.refresh_from_db()
        self.assertEqual(note.internal_note, REDACTED_REPORT_TEXT)
        self.assertTrue(audit_retention_integrity().is_valid)

        PublicProviderReportTriageEvent.objects.filter(pk=note.pk).update(
            internal_note="Notă istorică rămasă după vechea politică."
        )
        self.assertEqual(
            audit_retention_integrity().as_dict()["anomalies"]["retained_report_exposed"],
            1,
        )
        self.assertEqual(data_retention_snapshot(now=self.now)["eligible"]["closed_reports"], 1)
        reapplied = apply_data_retention(
            acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now
        )
        self.assertEqual(reapplied["applied"]["closed_reports"], 1)
        self.assertTrue(audit_retention_integrity().is_valid)

    def test_retained_rights_and_partner_notes_are_audited(self):
        """Audit related free text, not just the retained parent row."""

        apply_data_retention(acknowledgement=APPLY_ACKNOWLEDGEMENT, now=self.now)
        DataSubjectRequestEvent.objects.filter(request=self.closed_data_request).update(
            internal_note="Notă privată rămasă"
        )
        ManagedSiteInquiryEvent.objects.filter(inquiry=self.old_managed_site_inquiry).update(
            internal_note="Brief privat rămas"
        )
        anomalies = audit_retention_integrity().as_dict()["anomalies"]
        self.assertEqual(anomalies["retained_data_request_exposed"], 1)
        self.assertEqual(anomalies["retained_managed_site_inquiry_exposed"], 1)

    def test_command_defaults_to_identity_free_audit_and_apply_is_guarded(self):
        output = StringIO()
        call_command("apply_data_retention", stdout=output)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "audit_only")
        self.assertNotIn("Persoană Test", output.getvalue())
        self.assertNotIn("unverified@example.test", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("apply_data_retention", apply=True)
