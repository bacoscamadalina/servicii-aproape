"""Privacy-bounded, in-memory exports for verified data-subject requests."""

from hashlib import sha256
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .locations import locality_name
from .models import (
    DataSubjectRequest,
    DataSubjectRequestEvent,
    CustomerAccount,
    ProviderClaimRequest,
    ProviderLead,
    ProviderMembership,
    ProviderCRMCustomer,
    ProviderProfile,
    ProviderRegistrationRequest,
    ProviderSubscription,
)


EXPORT_POLICY_VERSION = "2026-09-02-v1"
EXPORT_ACKNOWLEDGEMENT = (
    "Confirm că identitatea este verificată și că pachetul va fi transmis numai "
    "persoanei vizate printr-un canal adecvat."
)
EXPORT_FILENAME = "serviciiaproape-date-personale.json"


def _iso(value):
    """Serialize optional timestamps without losing timezone information."""

    return value.isoformat() if value else None


def _profile_payload(profile):
    """Project provider-owned facts while excluding audit, credentials and media bytes."""

    draft = getattr(profile, "service_area_draft", None)
    services = [] if draft is None else list(
        draft.services.order_by("category").values_list("category", flat=True)
    )
    coverage = [] if draft is None else [
        {
            "county": row.county,
            "siruta_code": row.siruta_code,
            "locality": locality_name(row.county, row.siruta_code),
        }
        for row in draft.coverage.order_by("county", "siruta_code")
    ]
    portfolio = [
        {"caption": item.caption, "position": item.position}
        for item in profile.portfolio_items.order_by("position", "pk")
    ]
    publications = []
    for submission in profile.publication_submissions.order_by("version"):
        publications.append(
            {
                "version": submission.version,
                "display_name": submission.display_name,
                "description": submission.description,
                "public_address": submission.public_address,
                "public_phone": submission.public_phone,
                "public_email": submission.public_email,
                "website": submission.website,
                "availability": submission.availability,
                "contact_preference": submission.contact_preference,
                "submitted_at": _iso(submission.submitted_at),
                "decision": submission.decision,
                "reviewed_at": _iso(submission.reviewed_at),
                "services": list(
                    submission.services.order_by("category").values_list(
                        "category", flat=True
                    )
                ),
                "coverage": [
                    {
                        "county": row.county,
                        "siruta_code": row.siruta_code,
                        "locality": locality_name(row.county, row.siruta_code),
                    }
                    for row in submission.coverage.order_by("county", "siruta_code")
                ],
                "portfolio": [
                    {"caption": item.caption, "position": item.position}
                    for item in submission.portfolio_items.order_by("position", "pk")
                ],
            }
        )
    try:
        subscription = profile.subscription
    except ProviderSubscription.DoesNotExist:
        subscription = None
    billing_identity = getattr(profile, "billing_identity", None)
    return {
        "display_name": profile.display_name,
        "description": profile.description,
        "public_address": profile.public_address,
        "public_phone": profile.public_phone,
        "public_email": profile.public_email,
        "website": profile.website,
        "availability": profile.availability,
        "contact_preference": profile.contact_preference,
        "state": profile.state,
        "created_at": _iso(profile.created_at),
        "updated_at": _iso(profile.updated_at),
        "service_declaration": None if draft is None else {
            "revision": draft.revision,
            "review_state": draft.review_state,
            "updated_at": _iso(draft.updated_at),
            "services": services,
            "coverage": coverage,
        },
        "portfolio": portfolio,
        "publication_submissions": publications,
        "billing_identity": None if billing_identity is None else {
            "legal_name": billing_identity.legal_name,
            "fiscal_identifier": billing_identity.fiscal_identifier,
            "registration_number": billing_identity.registration_number,
            "registered_address": billing_identity.registered_address,
            "revision": billing_identity.revision,
            "created_at": _iso(billing_identity.created_at),
            "updated_at": _iso(billing_identity.updated_at),
            "revisions": [
                {
                    "revision": event.revision,
                    "legal_name": event.legal_name,
                    "fiscal_identifier": event.fiscal_identifier,
                    "registration_number": event.registration_number,
                    "registered_address": event.registered_address,
                    "created_at": _iso(event.created_at),
                }
                for event in billing_identity.events.all()
            ],
        },
        "subscription": None if subscription is None else {
            "status": subscription.status,
            "period_started_at": _iso(subscription.period_started_at),
            "period_ends_at": _iso(subscription.period_ends_at),
            "revision": subscription.revision,
            "updated_at": _iso(subscription.updated_at),
            "events": [
                {
                    "action": event.action,
                    "previous_status": event.previous_status,
                    "new_status": event.new_status,
                    "previous_period_ends_at": _iso(event.previous_period_ends_at),
                    "new_period_ends_at": _iso(event.new_period_ends_at),
                    "revision": event.revision,
                    "created_at": _iso(event.created_at),
                }
                for event in subscription.events.order_by("created_at", "pk")
            ],
        },
    }


def _build_payload(item, generated_at):
    """Link records only by the verified exact e-mail and explicit ownership edges."""

    email = item.contact_email.strip().lower()
    users = list(
        get_user_model().objects.filter(email__iexact=email).order_by("pk")
    )
    customer_accounts = list(
        CustomerAccount.objects.filter(user__in=users).select_related("user").order_by("pk")
    )
    customer_leads = list(
        ProviderLead.objects.filter(customer_account__in=customer_accounts)
        .select_related(
            "submission", "work_order__accepted_quote", "work_order__invoice_draft",
            "work_order__receivable",
        )
        .prefetch_related(
            "quotes__lines", "visit_proposals", "work_order__events",
            "work_order__receivable__manual_payments",
            "work_order__receivable__follow_up_events",
        )
        .order_by("created_at", "pk")
    )
    memberships = list(
        ProviderMembership.objects.filter(user__in=users)
        .select_related("profile")
        .order_by("profile_id", "pk")
    )
    claims = list(
        ProviderClaimRequest.objects.filter(email__iexact=email).order_by(
            "created_at", "pk"
        )
    )
    registrations = list(
        ProviderRegistrationRequest.objects.filter(email__iexact=email).order_by(
            "created_at", "pk"
        )
    )
    provider_customer_records = list(
        ProviderCRMCustomer.objects.filter(email__iexact=email)
        .select_related("profile")
        .prefetch_related("events")
        .order_by("created_at", "pk")
    )
    profile_ids = {membership.profile_id for membership in memberships}
    profile_ids.update(
        ProviderProfile.objects.filter(approved_claim__in=claims).values_list(
            "pk", flat=True
        )
    )
    profiles = list(
        ProviderProfile.objects.filter(pk__in=profile_ids)
        .select_related("service_area_draft", "billing_identity")
        .prefetch_related("subscription__events", "billing_identity__events")
        .order_by("pk")
    )
    return {
        "schema_version": 12,
        "generated_at": _iso(generated_at),
        "request": {"kind": item.request_kind, "verified_contact_email": email},
        "accounts": [
            {
                "username": user.get_username(),
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "is_active": user.is_active,
                "date_joined": _iso(user.date_joined),
                "last_login": _iso(user.last_login),
            }
            for user in users
        ],
        "customer_accounts": [
            {
                "email": account.normalized_email,
                "privacy_notice_version": account.privacy_notice_version,
                "created_at": _iso(account.created_at),
            }
            for account in customer_accounts
        ],
        "customer_requests": [
            {
                "public_id": str(lead.public_id),
                "provider": lead.submission.display_name,
                "category": lead.category,
                "county": lead.county,
                "siruta_code": lead.siruta_code,
                "customer_name": lead.customer_name,
                "customer_email": lead.customer_email,
                "customer_phone": lead.customer_phone,
                "project_address": lead.project_address,
                "description": lead.description,
                "budget": lead.budget,
                "desired_start": lead.desired_start,
                "status": lead.status,
                "privacy_notice_version": lead.privacy_notice_version,
                "created_at": _iso(lead.created_at),
                "retention_applied_at": _iso(lead.retention_applied_at),
                "quotes": [
                    {
                        "revision": quote.revision,
                        "amount_ron": str(quote.amount_ron),
                        "summary": quote.summary,
                        "estimated_duration": quote.estimated_duration,
                        "valid_until": _iso(quote.valid_until),
                        "status": quote.status,
                        "sent_at": _iso(quote.sent_at),
                        "responded_at": _iso(quote.responded_at),
                        "lines": [
                            {
                                "position": line.position,
                                "description": line.description,
                                "quantity": str(line.quantity),
                                "unit": line.unit,
                                "unit_price_ron": str(line.unit_price_ron),
                                "total_ron": str(line.total_ron),
                            }
                            for line in quote.lines.all()
                        ],
                    }
                    for quote in lead.quotes.all()
                ],
                "work_order": (
                    {
                        "status": lead.work_order.status,
                        "revision": lead.work_order.revision,
                        "accepted_quote_revision": lead.work_order.accepted_quote.revision,
                        "scheduled_start": _iso(lead.work_order.scheduled_start),
                        "scheduled_end": _iso(lead.work_order.scheduled_end),
                        "started_at": _iso(lead.work_order.started_at),
                        "completed_at": _iso(lead.work_order.completed_at),
                        "created_at": _iso(lead.work_order.created_at),
                        "invoice_draft": (
                            {
                                "amount_ron": str(lead.work_order.invoice_draft.amount_ron),
                                "description": lead.work_order.invoice_draft.description,
                                "revision": lead.work_order.invoice_draft.revision,
                                "created_at": _iso(lead.work_order.invoice_draft.created_at),
                                "updated_at": _iso(lead.work_order.invoice_draft.updated_at),
                            }
                            if hasattr(lead.work_order, "invoice_draft") else None
                        ),
                        "receivable": (
                            {
                                "amount_ron": str(lead.work_order.receivable.amount_ron),
                                "due_date": _iso(lead.work_order.receivable.due_date),
                                "reference": lead.work_order.receivable.reference,
                                "created_at": _iso(lead.work_order.receivable.created_at),
                                "follow_up_on": _iso(lead.work_order.receivable.follow_up_on),
                                "follow_up_revision": lead.work_order.receivable.follow_up_revision,
                                "last_followed_up_at": _iso(lead.work_order.receivable.last_followed_up_at),
                                "manual_payments": [
                                    {
                                        "amount_ron": str(payment.amount_ron),
                                        "received_on": _iso(payment.received_on),
                                        "reference": payment.reference,
                                        "state": payment.state,
                                        "recorded_at": _iso(payment.recorded_at),
                                        "voided_at": _iso(payment.voided_at),
                                        "void_reason": payment.void_reason,
                                    }
                                    for payment in lead.work_order.receivable.manual_payments.all()
                                ],
                                "follow_up_events": [
                                    {
                                        "revision": event.revision,
                                        "action": event.action,
                                        "previous_on": _iso(event.previous_on),
                                        "new_on": _iso(event.new_on),
                                        "created_at": _iso(event.created_at),
                                    }
                                    for event in lead.work_order.receivable.follow_up_events.all()
                                ],
                            }
                            if hasattr(lead.work_order, "receivable") else None
                        ),
                        "events": [
                            {
                                "revision": event.revision,
                                "previous_status": event.previous_status,
                                "new_status": event.new_status,
                                "previous_start": _iso(event.previous_start),
                                "new_start": _iso(event.new_start),
                                "previous_end": _iso(event.previous_end),
                                "new_end": _iso(event.new_end),
                                "previous_started_at": _iso(event.previous_started_at),
                                "new_started_at": _iso(event.new_started_at),
                                "created_at": _iso(event.created_at),
                            }
                            for event in lead.work_order.events.all()
                        ],
                    }
                    if hasattr(lead, "work_order") else None
                ),
                "visit_proposals": [
                    {
                        "starts_at": _iso(visit.starts_at),
                        "note": visit.note,
                        "status": visit.status,
                        "proposed_at": _iso(visit.proposed_at),
                        "responded_at": _iso(visit.responded_at),
                        "cancelled_at": _iso(visit.cancelled_at),
                        "cancelled_by": visit.cancelled_by,
                    }
                    for visit in lead.visit_proposals.all()
                ],
            }
            for lead in customer_leads
        ],
        "provider_customer_records": [
            {
                "provider": customer.profile.display_name,
                "name": customer.name,
                "email": customer.email,
                "phone": customer.phone,
                "address": customer.address,
                "notes": customer.notes,
                "state": customer.state,
                "lawful_use_confirmed_at": _iso(customer.lawful_use_confirmed_at),
                "archived_at": _iso(customer.archived_at),
                "created_at": _iso(customer.created_at),
                "updated_at": _iso(customer.updated_at),
                "events": [
                    {
                        "revision": event.revision,
                        "action": event.action,
                        "created_at": _iso(event.created_at),
                    }
                    for event in customer.events.all()
                ],
            }
            for customer in provider_customer_records
        ],
        "provider_claims": [
            {
                "legal_name_at_request": claim.legal_name_at_request,
                "contact_name": claim.contact_name,
                "role": claim.role,
                "email": claim.email,
                "account_first_name": claim.account_first_name,
                "account_last_name": claim.account_last_name,
                "account_username": claim.account_username,
                "status": claim.status,
                "email_verified_at": _iso(claim.email_verified_at),
                "privacy_notice_version": claim.privacy_notice_version,
                "consented_at": _iso(claim.consented_at),
                "reviewed_at": _iso(claim.reviewed_at),
                "created_at": _iso(claim.created_at),
            }
            for claim in claims
        ],
        "provider_registration_requests": [
            {
                "legal_name": registration.legal_name,
                "cui": registration.cui,
                "registration_number": registration.registration_number,
                "requested_category": registration.requested_category,
                "registered_county": registration.registered_county,
                "registered_office_siruta": registration.registered_office_siruta,
                "contact_name": registration.contact_name,
                "role": registration.role,
                "email": registration.email,
                "account_first_name": registration.account_first_name,
                "account_last_name": registration.account_last_name,
                "account_username": registration.account_username,
                "status": registration.status,
                "email_verified_at": _iso(registration.email_verified_at),
                "privacy_notice_version": registration.privacy_notice_version,
                "consented_at": _iso(registration.consented_at),
                "reviewed_at": _iso(registration.reviewed_at),
                "created_at": _iso(registration.created_at),
            }
            for registration in registrations
        ],
        "provider_memberships": [
            {
                "state": membership.state,
                "invited_at": _iso(membership.invited_at),
                "activated_at": _iso(membership.activated_at),
                "revoked_at": _iso(membership.revoked_at),
                "profile_display_name": membership.profile.display_name,
            }
            for membership in memberships
        ],
        "provider_profiles": [_profile_payload(profile) for profile in profiles],
        "manual_review_notice": (
            "Fișierele binare din portofoliu și conținutul operațional intern nu sunt "
            "incluse automat; operatorul le analizează separat pentru a proteja datele "
            "altor persoane și informațiile de securitate."
        ),
    }


@transaction.atomic
def generate_data_subject_export(
    *, request_id, actor, expected_revision, acknowledgement, now=None
):
    """Generate one JSON package in memory and append its content digest to the audit."""

    item = DataSubjectRequest.objects.select_for_update().get(pk=request_id)
    if not (
        actor.is_active
        and actor.is_staff
        and actor.has_perm("services.process_data_subject_request")
    ):
        raise PermissionError("Nu ai permisiunea de a genera acest pachet.")
    if item.revision != expected_revision:
        raise ValueError(
            "Cererea a fost modificată de alt administrator. Reîncarcă pagina."
        )
    if item.request_kind not in (
        DataSubjectRequest.Kind.ACCESS,
        DataSubjectRequest.Kind.PORTABILITY,
    ):
        raise ValueError(
            "Pachetul automat este disponibil numai pentru acces sau portabilitate."
        )
    if (
        item.status != DataSubjectRequest.Status.IN_REVIEW
        or item.identity_verified_at is None
    ):
        raise ValueError("Identitatea trebuie confirmată înainte de generarea pachetului.")
    if acknowledgement != EXPORT_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea transmiterii controlate este obligatorie.")

    generated_at = now or timezone.now()
    content = json.dumps(
        _build_payload(item, generated_at),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    digest = sha256(content).hexdigest()
    revision = item.revision + 1
    DataSubjectRequestEvent.objects.create(
        request=item,
        action=DataSubjectRequestEvent.Action.EXPORT_GENERATED,
        previous_status=item.status,
        new_status=item.status,
        revision=revision,
        internal_note=f"Pachet JSON generat în memorie; SHA-256 {digest}.",
        policy_version=EXPORT_POLICY_VERSION,
        acknowledgement=EXPORT_ACKNOWLEDGEMENT,
        actor=actor,
    )
    item.revision = revision
    item.save(update_fields=("revision", "updated_at"))
    return content
