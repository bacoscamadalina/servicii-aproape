"""Aggregate audit and explicitly acknowledged minimization of expired private data."""

from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from .models import (
    AccountLoginThrottle,
    DataSubjectRequest,
    DataSubjectRequestEvent,
    ManagedSiteInquiry,
    ManagedSiteInquiryEvent,
    ProviderClaimRequest,
    ProviderEngagementEvent,
    ProviderLead,
    ProviderLeadCustomerLinkEvent,
    ProviderLeadBatch,
    ProviderLeadMessage,
    ProviderQuote,
    ProviderQuoteLine,
    ProviderVisitProposal,
    ProviderWorkOrder,
    ProviderRegistrationRequest,
    ProviderRepresentationEvidence,
    ProviderPasswordResetThrottle,
    PublicProviderReport,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
)
from .provider_analytics import ANALYTICS_PERIODS


POLICY_VERSION = "2026-09-21-v5"
APPLY_ACKNOWLEDGEMENT = "APPLY_CONFIGURED_DATA_RETENTION"
TECHNICAL_THROTTLE_RETENTION = timedelta(hours=24)
REDACTED_CLAIM_TEXT = "Eliminat conform politicii de retenție."
REDACTED_REPORT_TEXT = "Conținut eliminat conform politicii de retenție."
REDACTED_DATA_REQUEST_TEXT = "Eliminat conform politicii de retenție."
REDACTED_LEAD_TEXT = "Date eliminate conform politicii de retenție."
REDACTED_MANAGED_SITE_TEXT = "Conținut eliminat conform politicii de retenție."


def _cutoffs(now):
    """Return the environment-owned cutoffs used by both audit and mutation."""

    return {
        "unverified_claim": now
        - timedelta(days=settings.RETENTION_UNVERIFIED_CLAIM_DAYS),
        "rejected_claim": now
        - timedelta(days=settings.RETENTION_REJECTED_CLAIM_DAYS),
        "closed_report": now
        - timedelta(days=settings.RETENTION_CLOSED_REPORT_DAYS),
        "closed_data_request": now
        - timedelta(days=settings.RETENTION_CLOSED_DATA_REQUEST_DAYS),
        "closed_provider_lead": now
        - timedelta(days=settings.RETENTION_CLOSED_PROVIDER_LEAD_DAYS),
        "managed_site_inquiry": now
        - timedelta(days=settings.RETENTION_MANAGED_SITE_INQUIRY_DAYS),
        "technical_throttle": now - TECHNICAL_THROTTLE_RETENTION,
        # Keep exactly the dates used by the longest provider dashboard window.
        "provider_engagement": timezone.localdate(now)
        - timedelta(days=max(ANALYTICS_PERIODS) - 1),
    }


def _eligible_unverified_claims(now, cutoffs):
    """Select expired unverified claims; active review never enters this set."""

    return ProviderClaimRequest.objects.filter(
        status__in=(
            ProviderClaimRequest.Status.EMAIL_PENDING,
            ProviderClaimRequest.Status.SUPERSEDED,
        ),
        created_at__lt=cutoffs["unverified_claim"],
        token_expires_at__lt=now,
        retention_applied_at__isnull=True,
    )


def _eligible_rejected_claims(cutoffs):
    """Select only completed rejections older than the configured policy."""

    return ProviderClaimRequest.objects.filter(
        status=ProviderClaimRequest.Status.REJECTED,
        reviewed_at__lt=cutoffs["rejected_claim"],
        retention_applied_at__isnull=True,
    )


def _eligible_unverified_registrations(now, cutoffs):
    """Select expired unverified company-registration intake."""

    return ProviderRegistrationRequest.objects.filter(
        status__in=(
            ProviderRegistrationRequest.Status.EMAIL_PENDING,
            ProviderRegistrationRequest.Status.SUPERSEDED,
        ),
        created_at__lt=cutoffs["unverified_claim"],
        token_expires_at__lt=now,
        retention_applied_at__isnull=True,
    )


def _eligible_rejected_registrations(cutoffs):
    """Select completed rejected registrations after the configured period."""

    return ProviderRegistrationRequest.objects.filter(
        status=ProviderRegistrationRequest.Status.REJECTED,
        reviewed_at__lt=cutoffs["rejected_claim"],
        retention_applied_at__isnull=True,
    )


def _eligible_closed_reports(cutoffs):
    """Select aged closed reports, including legacy retained notes needing cleanup."""

    unredacted_note = PublicProviderReportTriageEvent.objects.filter(
        case__report_id=OuterRef("pk")
    ).exclude(internal_note=REDACTED_REPORT_TEXT)
    return PublicProviderReport.objects.filter(
        triage_case__state=PublicProviderReportCase.State.CLOSED,
        triage_case__updated_at__lt=cutoffs["closed_report"],
    ).annotate(has_unredacted_note=Exists(unredacted_note)).filter(
        Q(retention_applied_at__isnull=True) | Q(has_unredacted_note=True)
    )


def _eligible_closed_data_requests(cutoffs):
    """Select only completed rights requests older than the operator policy."""

    return DataSubjectRequest.objects.filter(
        status__in=(
            DataSubjectRequest.Status.FULFILLED,
            DataSubjectRequest.Status.REFUSED,
        ),
        closed_at__lt=cutoffs["closed_data_request"],
        retention_applied_at__isnull=True,
    )


def _eligible_closed_provider_leads(cutoffs):
    """Select conclusively closed customer requests after the declared period."""

    return ProviderLead.objects.filter(
        status__in=(ProviderLead.Status.COMPLETED, ProviderLead.Status.DECLINED),
        updated_at__lt=cutoffs["closed_provider_lead"],
        retention_applied_at__isnull=True,
    )


def _eligible_retained_lead_batches(cutoffs):
    """Select parents whose every child is retained or eligible in this run."""

    children = ProviderLead.objects.filter(batch_id=OuterRef("pk"))
    unfinished = children.filter(retention_applied_at__isnull=True).exclude(
        status__in=(ProviderLead.Status.COMPLETED, ProviderLead.Status.DECLINED),
        updated_at__lt=cutoffs["closed_provider_lead"],
    )
    return ProviderLeadBatch.objects.filter(
        retention_applied_at__isnull=True
    ).annotate(
        has_children=Exists(children), has_unfinished=Exists(unfinished)
    ).filter(has_children=True, has_unfinished=False)


def _eligible_managed_site_inquiries(cutoffs):
    """Select aged commercial briefs without inferring an external sales status."""

    return ManagedSiteInquiry.objects.filter(
        created_at__lt=cutoffs["managed_site_inquiry"],
        retention_applied_at__isnull=True,
    )


def data_retention_snapshot(*, now=None):
    """Return a read-only, identity-free inventory for operator review."""

    effective_now = now or timezone.now()
    cutoffs = _cutoffs(effective_now)
    return {
        "policy_version": POLICY_VERSION,
        "generated_at": effective_now.isoformat(),
        "configured_days": {
            "unverified_claims": settings.RETENTION_UNVERIFIED_CLAIM_DAYS,
            "rejected_claims": settings.RETENTION_REJECTED_CLAIM_DAYS,
            "closed_reports": settings.RETENTION_CLOSED_REPORT_DAYS,
            "closed_data_requests": settings.RETENTION_CLOSED_DATA_REQUEST_DAYS,
            "closed_provider_leads": settings.RETENTION_CLOSED_PROVIDER_LEAD_DAYS,
            "managed_site_inquiries": settings.RETENTION_MANAGED_SITE_INQUIRY_DAYS,
            "provider_engagement": max(ANALYTICS_PERIODS),
        },
        "eligible": {
            "unverified_claims": _eligible_unverified_claims(
                effective_now, cutoffs
            ).count(),
            "rejected_claims": _eligible_rejected_claims(cutoffs).count(),
            "unverified_registrations": _eligible_unverified_registrations(
                effective_now, cutoffs
            ).count(),
            "rejected_registrations": _eligible_rejected_registrations(cutoffs).count(),
            "closed_reports": _eligible_closed_reports(cutoffs).count(),
            "closed_data_requests": _eligible_closed_data_requests(cutoffs).count(),
            "closed_provider_leads": _eligible_closed_provider_leads(cutoffs).count(),
            "retained_lead_batches": _eligible_retained_lead_batches(cutoffs).count(),
            "managed_site_inquiries": _eligible_managed_site_inquiries(cutoffs).count(),
            "provider_engagement_events": ProviderEngagementEvent.objects.filter(
                occurred_on__lt=cutoffs["provider_engagement"]
            ).count(),
            "password_reset_throttles": ProviderPasswordResetThrottle.objects.filter(
                window_started_at__lt=cutoffs["technical_throttle"]
            ).count(),
            "login_throttles": AccountLoginThrottle.objects.filter(
                window_started_at__lt=cutoffs["technical_throttle"]
            ).count(),
        },
        "manual_review": {
            "stale_claims_in_review": ProviderClaimRequest.objects.filter(
                status=ProviderClaimRequest.Status.REVIEW_PENDING,
                created_at__lt=cutoffs["rejected_claim"],
                retention_applied_at__isnull=True,
            ).count(),
            "stale_registrations_in_review": ProviderRegistrationRequest.objects.filter(
                status=ProviderRegistrationRequest.Status.REVIEW_PENDING,
                created_at__lt=cutoffs["rejected_claim"],
                retention_applied_at__isnull=True,
            ).count(),
        },
    }


def _anonymize_claim_batch(queryset, *, now, batch_size):
    """Lock and anonymize one bounded claim batch without erasing audit state."""

    claims = list(queryset.select_for_update().order_by("pk")[:batch_size])
    ProviderRepresentationEvidence.objects.filter(claim__in=claims).delete()
    for claim in claims:
        claim.legal_name_at_request = REDACTED_CLAIM_TEXT
        claim.contact_name = REDACTED_CLAIM_TEXT
        claim.role = REDACTED_CLAIM_TEXT
        claim.email = f"retained-claim-{claim.pk}@retention.invalid"
        claim.account_first_name = REDACTED_CLAIM_TEXT
        claim.account_last_name = REDACTED_CLAIM_TEXT
        claim.account_username = f"retained-claim-{claim.pk}"
        claim.password_hash = ""
        claim.token_digest = sha256(f"retained-claim:{claim.pk}".encode()).hexdigest()
        claim.review_note = REDACTED_CLAIM_TEXT if claim.review_note else ""
        claim.retention_applied_at = now
    ProviderClaimRequest.objects.bulk_update(
        claims,
        (
            "legal_name_at_request",
            "contact_name",
            "role",
            "email",
            "account_first_name",
            "account_last_name",
            "account_username",
            "password_hash",
            "token_digest",
            "review_note",
            "retention_applied_at",
        ),
    )
    return len(claims)


def _anonymize_report_batch(queryset, *, now, batch_size):
    """Lock and minimize one bounded closed-report batch."""

    reports = list(queryset.select_for_update().order_by("pk")[:batch_size])
    PublicProviderReportTriageEvent.objects.filter(
        case__report_id__in=(report.pk for report in reports)
    ).update(internal_note=REDACTED_REPORT_TEXT)
    for report in reports:
        report.details = REDACTED_REPORT_TEXT
        report.reporter_session_digest = sha256(
            f"retained-report:{report.pk}".encode()
        ).hexdigest()
        report.retention_applied_at = now
    PublicProviderReport.objects.bulk_update(
        reports,
        ("details", "reporter_session_digest", "retention_applied_at"),
    )
    return len(reports)


def _anonymize_registration_batch(queryset, *, now, batch_size):
    """Lock and minimize one bounded unlisted-company registration batch."""

    registrations = list(queryset.select_for_update().order_by("pk")[:batch_size])
    ProviderRepresentationEvidence.objects.filter(registration__in=registrations).delete()
    for registration in registrations:
        registration.legal_name = REDACTED_CLAIM_TEXT
        registration.cui = f"RET-{registration.pk}"
        registration.registration_number = f"retained-registration-{registration.pk}"
        registration.contact_name = REDACTED_CLAIM_TEXT
        registration.role = REDACTED_CLAIM_TEXT
        registration.email = f"retained-registration-{registration.pk}@retention.invalid"
        registration.account_first_name = REDACTED_CLAIM_TEXT
        registration.account_last_name = REDACTED_CLAIM_TEXT
        registration.account_username = f"retained-registration-{registration.pk}"
        registration.password_hash = ""
        registration.token_digest = sha256(
            f"retained-registration:{registration.pk}".encode()
        ).hexdigest()
        registration.review_note = REDACTED_CLAIM_TEXT if registration.review_note else ""
        registration.retention_applied_at = now
    ProviderRegistrationRequest.objects.bulk_update(
        registrations,
        (
            "legal_name",
            "cui",
            "registration_number",
            "contact_name",
            "role",
            "email",
            "account_first_name",
            "account_last_name",
            "account_username",
            "password_hash",
            "token_digest",
            "review_note",
            "retention_applied_at",
        ),
    )
    return len(registrations)


def _anonymize_data_request_batch(queryset, *, now, batch_size):
    """Minimize closed-request intake and notes while preserving the decision trail."""

    requests = list(queryset.select_for_update().order_by("pk")[:batch_size])
    for item in requests:
        item.requester_name = REDACTED_DATA_REQUEST_TEXT
        item.contact_email = f"retained-request-{item.pk}@retention.invalid"
        item.details = REDACTED_DATA_REQUEST_TEXT
        item.retention_applied_at = now
    DataSubjectRequest.objects.bulk_update(
        requests,
        ("requester_name", "contact_email", "details", "retention_applied_at"),
    )
    DataSubjectRequestEvent.objects.filter(
        request_id__in=(item.pk for item in requests)
    ).update(internal_note=REDACTED_DATA_REQUEST_TEXT)
    return len(requests)


def _anonymize_provider_lead_batch(queryset, *, now, batch_size):
    """Remove customer identity and project text while preserving funnel totals."""

    leads = list(queryset.select_for_update().order_by("pk")[:batch_size])
    for lead in leads:
        lead.customer_name = REDACTED_LEAD_TEXT
        lead.customer_email = f"retained-lead-{lead.pk}@retention.invalid"
        lead.customer_phone = REDACTED_LEAD_TEXT
        lead.project_address = ""
        lead.description = REDACTED_LEAD_TEXT
        lead.owner_notes = ""
        lead.visitor_session_digest = sha256(
            f"retained-lead:{lead.pk}".encode()
        ).hexdigest()
        lead.customer_access_digest = None
        lead.customer_access_expires_at = None
        lead.customer_account = None
        lead.crm_customer = None
        lead.retention_applied_at = now
    lead_ids = [lead.pk for lead in leads]
    ProviderLeadMessage.objects.filter(lead_id__in=lead_ids).delete()
    ProviderLeadCustomerLinkEvent.objects.filter(lead_id__in=lead_ids).delete()
    ProviderVisitProposal.objects.filter(lead_id__in=lead_ids).delete()
    # Execution records here have no fiscal fields; future issued invoices have
    # their own legal retention boundary and must not be cascaded with a lead.
    ProviderWorkOrder.objects.filter(lead_id__in=lead_ids).delete()
    ProviderQuote.objects.filter(lead_id__in=lead_ids).update(
        summary=REDACTED_LEAD_TEXT,
        estimated_duration=REDACTED_LEAD_TEXT,
    )
    ProviderQuoteLine.objects.filter(quote__lead_id__in=lead_ids).update(
        description=REDACTED_LEAD_TEXT,
    )
    ProviderLead.objects.bulk_update(
        leads,
        (
            "customer_name",
            "customer_email",
            "customer_phone",
            "project_address",
            "description",
            "owner_notes",
            "visitor_session_digest",
            "customer_access_digest",
            "customer_access_expires_at",
            "customer_account",
            "crm_customer",
            "retention_applied_at",
        ),
    )
    return len(leads)


def _anonymize_retained_lead_parent_batch(queryset, *, now, batch_size):
    """Detach a fully retained comparison from its account and old capability."""

    batches = list(queryset.select_for_update().order_by("pk")[:batch_size])
    for batch in batches:
        batch.visitor_session_digest = sha256(
            f"retained-batch:{batch.pk}".encode()
        ).hexdigest()
        batch.customer_access_digest = sha256(
            f"retained-batch-access:{batch.pk}".encode()
        ).hexdigest()
        batch.customer_access_expires_at = now
        batch.customer_account = None
        batch.retention_applied_at = now
    ProviderLeadBatch.objects.bulk_update(
        batches,
        (
            "visitor_session_digest",
            "customer_access_digest",
            "customer_access_expires_at",
            "customer_account",
            "retention_applied_at",
        ),
    )
    return len(batches)


def _anonymize_managed_site_inquiry_batch(queryset, *, now, batch_size):
    """Remove provider and operator free text after the declared period."""

    inquiries = list(queryset.select_for_update().order_by("pk")[:batch_size])
    ManagedSiteInquiryEvent.objects.filter(
        inquiry_id__in=(inquiry.pk for inquiry in inquiries)
    ).update(internal_note=REDACTED_MANAGED_SITE_TEXT)
    for inquiry in inquiries:
        inquiry.current_website = ""
        inquiry.brief = REDACTED_MANAGED_SITE_TEXT
        inquiry.retention_applied_at = now
    ManagedSiteInquiry.objects.bulk_update(
        inquiries, ("current_website", "brief", "retention_applied_at")
    )
    return len(inquiries)


def apply_data_retention(*, acknowledgement, batch_size=250, now=None):
    """Apply configured minimization only after an exact operator acknowledgement."""

    if acknowledgement != APPLY_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea exactă pentru aplicarea retenției lipsește.")
    if not 1 <= batch_size <= 1000:
        raise ValueError("Dimensiunea lotului trebuie să fie între 1 și 1000.")

    effective_now = now or timezone.now()
    cutoffs = _cutoffs(effective_now)
    applied = {
        "unverified_claims": 0,
        "rejected_claims": 0,
        "unverified_registrations": 0,
        "rejected_registrations": 0,
        "closed_reports": 0,
        "closed_data_requests": 0,
        "closed_provider_leads": 0,
        "retained_lead_batches": 0,
        "managed_site_inquiries": 0,
        "provider_engagement_events": 0,
        "password_reset_throttles": 0,
        "login_throttles": 0,
    }
    with transaction.atomic():
        for key, queryset in (
            ("unverified_claims", _eligible_unverified_claims(effective_now, cutoffs)),
            ("rejected_claims", _eligible_rejected_claims(cutoffs)),
        ):
            while count := _anonymize_claim_batch(
                queryset, now=effective_now, batch_size=batch_size
            ):
                applied[key] += count
        for key, queryset in (
            (
                "unverified_registrations",
                _eligible_unverified_registrations(effective_now, cutoffs),
            ),
            ("rejected_registrations", _eligible_rejected_registrations(cutoffs)),
        ):
            while count := _anonymize_registration_batch(
                queryset, now=effective_now, batch_size=batch_size
            ):
                applied[key] += count
        while count := _anonymize_report_batch(
            _eligible_closed_reports(cutoffs),
            now=effective_now,
            batch_size=batch_size,
        ):
            applied["closed_reports"] += count
        while count := _anonymize_data_request_batch(
            _eligible_closed_data_requests(cutoffs),
            now=effective_now,
            batch_size=batch_size,
        ):
            applied["closed_data_requests"] += count
        while count := _anonymize_provider_lead_batch(
            _eligible_closed_provider_leads(cutoffs),
            now=effective_now,
            batch_size=batch_size,
        ):
            applied["closed_provider_leads"] += count
        while count := _anonymize_retained_lead_parent_batch(
            _eligible_retained_lead_batches(cutoffs),
            now=effective_now,
            batch_size=batch_size,
        ):
            applied["retained_lead_batches"] += count
        while count := _anonymize_managed_site_inquiry_batch(
            _eligible_managed_site_inquiries(cutoffs),
            now=effective_now,
            batch_size=batch_size,
        ):
            applied["managed_site_inquiries"] += count
        # Old daily digests serve no dashboard window; delete in bounded batches.
        while event_ids := list(
            ProviderEngagementEvent.objects.filter(
                occurred_on__lt=cutoffs["provider_engagement"]
            ).order_by("occurred_on", "pk").values_list("pk", flat=True)[:batch_size]
        ):
            deleted, _ = ProviderEngagementEvent.objects.filter(pk__in=event_ids).delete()
            applied["provider_engagement_events"] += deleted
        applied["password_reset_throttles"], _ = (
            ProviderPasswordResetThrottle.objects.filter(
                window_started_at__lt=cutoffs["technical_throttle"]
            ).delete()
        )
        applied["login_throttles"], _ = AccountLoginThrottle.objects.filter(
            window_started_at__lt=cutoffs["technical_throttle"]
        ).delete()
    return {
        "policy_version": POLICY_VERSION,
        "applied_at": effective_now.isoformat(),
        "applied": applied,
    }
