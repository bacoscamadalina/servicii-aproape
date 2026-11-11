"""Read-only checks that retained records no longer expose private data."""

from dataclasses import dataclass
from hashlib import sha256

from django.db.models import Exists, OuterRef

from .data_retention import (
    REDACTED_CLAIM_TEXT,
    REDACTED_DATA_REQUEST_TEXT,
    REDACTED_LEAD_TEXT,
    REDACTED_MANAGED_SITE_TEXT,
    REDACTED_REPORT_TEXT,
)
from .models import (
    DataSubjectRequest,
    DataSubjectRequestEvent,
    ManagedSiteInquiry,
    ManagedSiteInquiryEvent,
    ProviderClaimRequest,
    ProviderLead,
    ProviderLeadBatch,
    ProviderLeadCustomerLinkEvent,
    ProviderLeadMessage,
    ProviderQuote,
    ProviderQuoteLine,
    ProviderRegistrationRequest,
    ProviderRepresentationEvidence,
    PublicProviderReport,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
)


ANOMALY_CODES = (
    "retained_claim_exposed",
    "retained_registration_exposed",
    "retained_report_exposed",
    "retained_data_request_exposed",
    "retained_managed_site_inquiry_exposed",
    "retained_lead_exposed",
    "retained_lead_messages_present",
    "retained_lead_quotes_exposed",
    "retained_lead_customer_links_present",
    "retained_batch_exposed",
    "retained_batch_has_live_lead",
)


@dataclass(frozen=True)
class RetentionIntegrityAudit:
    """Expose aggregate findings only; no customer or provider identifiers."""

    retained_claims: int
    retained_registrations: int
    retained_reports: int
    retained_data_requests: int
    retained_managed_site_inquiries: int
    retained_leads: int
    retained_batches: int
    anomaly_counts: tuple[tuple[str, int], ...]

    @property
    def is_valid(self) -> bool:
        """Return whether every retained record satisfies the privacy contract."""

        return not any(count for _code, count in self.anomaly_counts)

    def as_dict(self) -> dict:
        """Render a stable, identity-free monitoring payload."""

        return {
            "schema_version": 4,
            "valid": self.is_valid,
            "totals": {
                "retained_claims": self.retained_claims,
                "retained_registrations": self.retained_registrations,
                "retained_reports": self.retained_reports,
                "retained_data_requests": self.retained_data_requests,
                "retained_managed_site_inquiries": self.retained_managed_site_inquiries,
                "retained_leads": self.retained_leads,
                "retained_batches": self.retained_batches,
            },
            "anomalies": dict(self.anomaly_counts),
        }


def audit_retention_integrity() -> RetentionIntegrityAudit:
    """Stream retained rows and check evidence, text, links and parent state."""

    anomalies = dict.fromkeys(ANOMALY_CODES, 0)
    retained_claims = 0
    claim_evidence = ProviderRepresentationEvidence.objects.filter(claim_id=OuterRef("pk"))
    claims = ProviderClaimRequest.objects.filter(retention_applied_at__isnull=False).annotate(
        has_evidence=Exists(claim_evidence)
    ).values(
        "pk", "status", "legal_name_at_request", "contact_name", "role", "email",
        "account_first_name", "account_last_name", "account_username", "password_hash",
        "token_digest", "review_note", "has_evidence",
    )
    for claim in claims.iterator(chunk_size=500):
        retained_claims += 1
        if (
            claim["status"] not in (
                ProviderClaimRequest.Status.EMAIL_PENDING,
                ProviderClaimRequest.Status.SUPERSEDED,
                ProviderClaimRequest.Status.REJECTED,
            )
            or claim["legal_name_at_request"] != REDACTED_CLAIM_TEXT
            or claim["contact_name"] != REDACTED_CLAIM_TEXT
            or claim["role"] != REDACTED_CLAIM_TEXT
            or claim["email"] != f"retained-claim-{claim['pk']}@retention.invalid"
            or claim["account_first_name"] != REDACTED_CLAIM_TEXT
            or claim["account_last_name"] != REDACTED_CLAIM_TEXT
            or claim["account_username"] != f"retained-claim-{claim['pk']}"
            or claim["password_hash"]
            or claim["token_digest"] != sha256(
                f"retained-claim:{claim['pk']}".encode()
            ).hexdigest()
            or claim["review_note"] not in ("", REDACTED_CLAIM_TEXT)
            or claim["has_evidence"]
        ):
            anomalies["retained_claim_exposed"] += 1

    retained_registrations = 0
    registration_evidence = ProviderRepresentationEvidence.objects.filter(
        registration_id=OuterRef("pk")
    )
    registrations = ProviderRegistrationRequest.objects.filter(
        retention_applied_at__isnull=False
    ).annotate(has_evidence=Exists(registration_evidence)).values(
        "pk", "status", "legal_name", "cui", "registration_number", "contact_name",
        "role", "email", "account_first_name", "account_last_name",
        "account_username", "password_hash", "token_digest", "review_note",
        "has_evidence",
    )
    for registration in registrations.iterator(chunk_size=500):
        retained_registrations += 1
        if (
            registration["status"] not in (
                ProviderRegistrationRequest.Status.EMAIL_PENDING,
                ProviderRegistrationRequest.Status.SUPERSEDED,
                ProviderRegistrationRequest.Status.REJECTED,
            )
            or registration["legal_name"] != REDACTED_CLAIM_TEXT
            or registration["cui"] != f"RET-{registration['pk']}"
            or registration["registration_number"] != f"retained-registration-{registration['pk']}"
            or registration["contact_name"] != REDACTED_CLAIM_TEXT
            or registration["role"] != REDACTED_CLAIM_TEXT
            or registration["email"] != f"retained-registration-{registration['pk']}@retention.invalid"
            or registration["account_first_name"] != REDACTED_CLAIM_TEXT
            or registration["account_last_name"] != REDACTED_CLAIM_TEXT
            or registration["account_username"] != f"retained-registration-{registration['pk']}"
            or registration["password_hash"]
            or registration["token_digest"] != sha256(
                f"retained-registration:{registration['pk']}".encode()
            ).hexdigest()
            or registration["review_note"] not in ("", REDACTED_CLAIM_TEXT)
            or registration["has_evidence"]
        ):
            anomalies["retained_registration_exposed"] += 1

    retained_reports = 0
    report_note = PublicProviderReportTriageEvent.objects.filter(
        case__report_id=OuterRef("pk")
    ).exclude(internal_note=REDACTED_REPORT_TEXT)
    reports = PublicProviderReport.objects.filter(retention_applied_at__isnull=False).annotate(
        has_exposed_note=Exists(report_note)
    ).values(
        "pk", "details", "reporter_session_digest", "triage_case__state",
        "has_exposed_note",
    )
    for report in reports.iterator(chunk_size=500):
        retained_reports += 1
        if (
            report["details"] != REDACTED_REPORT_TEXT
            or report["reporter_session_digest"] != sha256(
                f"retained-report:{report['pk']}".encode()
            ).hexdigest()
            or report["triage_case__state"] != PublicProviderReportCase.State.CLOSED
            or report["has_exposed_note"]
        ):
            anomalies["retained_report_exposed"] += 1

    retained_data_requests = 0
    request_note = DataSubjectRequestEvent.objects.filter(
        request_id=OuterRef("pk")
    ).exclude(internal_note=REDACTED_DATA_REQUEST_TEXT)
    requests = DataSubjectRequest.objects.filter(retention_applied_at__isnull=False).annotate(
        has_exposed_note=Exists(request_note)
    ).values(
        "pk", "status", "requester_name", "contact_email", "details",
        "has_exposed_note",
    )
    for request in requests.iterator(chunk_size=500):
        retained_data_requests += 1
        if (
            request["status"] not in (
                DataSubjectRequest.Status.FULFILLED,
                DataSubjectRequest.Status.REFUSED,
            )
            or request["requester_name"] != REDACTED_DATA_REQUEST_TEXT
            or request["contact_email"] != f"retained-request-{request['pk']}@retention.invalid"
            or request["details"] != REDACTED_DATA_REQUEST_TEXT
            or request["has_exposed_note"]
        ):
            anomalies["retained_data_request_exposed"] += 1

    retained_managed_site_inquiries = 0
    inquiry_note = ManagedSiteInquiryEvent.objects.filter(
        inquiry_id=OuterRef("pk")
    ).exclude(internal_note=REDACTED_MANAGED_SITE_TEXT)
    inquiries = ManagedSiteInquiry.objects.filter(retention_applied_at__isnull=False).annotate(
        has_exposed_note=Exists(inquiry_note)
    ).values("current_website", "brief", "has_exposed_note")
    for inquiry in inquiries.iterator(chunk_size=500):
        retained_managed_site_inquiries += 1
        if (
            inquiry["current_website"]
            or inquiry["brief"] != REDACTED_MANAGED_SITE_TEXT
            or inquiry["has_exposed_note"]
        ):
            anomalies["retained_managed_site_inquiry_exposed"] += 1

    retained_leads = 0
    message = ProviderLeadMessage.objects.filter(lead_id=OuterRef("pk"))
    exposed_quote = ProviderQuote.objects.filter(lead_id=OuterRef("pk")).exclude(
        summary=REDACTED_LEAD_TEXT,
        estimated_duration=REDACTED_LEAD_TEXT,
    )
    exposed_quote_line = ProviderQuoteLine.objects.filter(
        quote__lead_id=OuterRef("pk")
    ).exclude(description=REDACTED_LEAD_TEXT)
    customer_link = ProviderLeadCustomerLinkEvent.objects.filter(lead_id=OuterRef("pk"))
    leads = ProviderLead.objects.filter(retention_applied_at__isnull=False).annotate(
        has_message=Exists(message), has_exposed_quote=Exists(exposed_quote),
        has_exposed_quote_line=Exists(exposed_quote_line),
        has_customer_link=Exists(customer_link),
    ).values(
        "pk", "status", "customer_name", "customer_email", "customer_phone",
        "customer_account_id", "project_address", "description", "owner_notes",
        "visitor_session_digest", "customer_access_digest",
        "customer_access_expires_at", "has_message", "has_exposed_quote",
        "has_exposed_quote_line",
        "crm_customer_id", "has_customer_link",
    )
    for lead in leads.iterator(chunk_size=500):
        retained_leads += 1
        expected_digest = sha256(f"retained-lead:{lead['pk']}".encode()).hexdigest()
        if (
            lead["status"] not in (ProviderLead.Status.COMPLETED, ProviderLead.Status.DECLINED)
            or lead["customer_name"] != REDACTED_LEAD_TEXT
            or lead["customer_email"] != f"retained-lead-{lead['pk']}@retention.invalid"
            or lead["customer_phone"] != REDACTED_LEAD_TEXT
            or lead["description"] != REDACTED_LEAD_TEXT
            or lead["project_address"]
            or lead["owner_notes"]
            or lead["customer_account_id"] is not None
            or lead["crm_customer_id"] is not None
            or lead["visitor_session_digest"] != expected_digest
            or lead["customer_access_digest"] is not None
            or lead["customer_access_expires_at"] is not None
        ):
            anomalies["retained_lead_exposed"] += 1
        if lead["has_message"]:
            anomalies["retained_lead_messages_present"] += 1
        if lead["has_exposed_quote"] or lead["has_exposed_quote_line"]:
            anomalies["retained_lead_quotes_exposed"] += 1
        if lead["has_customer_link"]:
            anomalies["retained_lead_customer_links_present"] += 1

    retained_batches = 0
    children = ProviderLead.objects.filter(batch_id=OuterRef("pk"))
    batches = ProviderLeadBatch.objects.filter(retention_applied_at__isnull=False).annotate(
        has_child=Exists(children),
        has_live_child=Exists(children.filter(retention_applied_at__isnull=True)),
    ).values(
        "pk", "visitor_session_digest", "customer_access_digest",
        "customer_access_expires_at", "customer_account_id", "retention_applied_at",
        "has_child", "has_live_child",
    )
    for batch in batches.iterator(chunk_size=500):
        retained_batches += 1
        if (
            batch["customer_account_id"] is not None
            or batch["visitor_session_digest"] != sha256(
                f"retained-batch:{batch['pk']}".encode()
            ).hexdigest()
            or batch["customer_access_digest"] != sha256(
                f"retained-batch-access:{batch['pk']}".encode()
            ).hexdigest()
            or batch["customer_access_expires_at"] > batch["retention_applied_at"]
        ):
            anomalies["retained_batch_exposed"] += 1
        if not batch["has_child"] or batch["has_live_child"]:
            anomalies["retained_batch_has_live_lead"] += 1

    return RetentionIntegrityAudit(
        retained_claims=retained_claims,
        retained_registrations=retained_registrations,
        retained_reports=retained_reports,
        retained_data_requests=retained_data_requests,
        retained_managed_site_inquiries=retained_managed_site_inquiries,
        retained_leads=retained_leads,
        retained_batches=retained_batches,
        anomaly_counts=tuple((code, anomalies[code]) for code in ANOMALY_CODES),
    )
