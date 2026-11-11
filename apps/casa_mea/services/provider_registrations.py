"""Audited onboarding for companies that are not yet present in the catalogue."""

from datetime import timedelta
import hashlib
import logging
import secrets

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    BusinessIdentity,
    ProviderClaimRequest,
    ProviderRegistrationRequest,
    ProviderRepresentationEvidence,
)
from .service_category_policies import new_provider_service_categories
from .provider_claims import PRIVACY_NOTICE_VERSION
from .representation_evidence import representation_evidence_values


TOKEN_LIFETIME = timedelta(hours=24)
RATE_LIMIT_WINDOW = timedelta(minutes=15)
RATE_LIMIT_COUNT = 3
REVIEW_POLICY_VERSION = "2026-09-04-v1"
REVIEW_ACKNOWLEDGEMENT = "VERIFIED_LEGAL_IDENTITY_WITHOUT_PUBLICATION"
security_logger = logging.getLogger("services.security")


def _token_digest(token: str) -> str:
    """Hash a bearer token so a database read cannot recover it."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@transaction.atomic
def create_provider_registration_request(
    *,
    legal_name: str,
    cui: str,
    registration_number: str,
    requested_category: str,
    registered_county: str,
    registered_office_siruta: str,
    contact_name: str,
    first_name: str,
    last_name: str,
    username: str,
    password: str,
    role: str,
    email: str,
    evidence_type: str,
    evidence_document,
    representation_declaration: bool,
) -> ProviderRegistrationRequest:
    """Create a review-pending intake while retaining only a password hash."""

    if requested_category not in {
        record.slug for record in new_provider_service_categories()
    }:
        raise ValueError(_("Alege serviciul principal prestat."))
    evidence_values = representation_evidence_values(
        evidence_type=evidence_type,
        upload=evidence_document,
        declaration=representation_declaration,
    )
    now = timezone.now()
    recent_count = ProviderRegistrationRequest.objects.filter(
        cui=cui,
        email=email,
        created_at__gte=now - RATE_LIMIT_WINDOW,
    ).count()
    if recent_count >= RATE_LIMIT_COUNT:
        security_logger.warning(
            "Provider registration creation budget exhausted.",
            extra={
                "event": "provider_registration_creation_throttled",
                "scope": "provider",
            },
        )
        raise ValueError(
            _("Au fost trimise prea multe cereri. Reîncearcă peste 15 minute.")
        )
    ProviderRegistrationRequest.objects.filter(
        cui=cui,
        email=email,
        status=ProviderRegistrationRequest.Status.EMAIL_PENDING,
    ).update(status=ProviderRegistrationRequest.Status.SUPERSEDED)
    registration = ProviderRegistrationRequest.objects.create(
        legal_name=legal_name,
        cui=cui,
        registration_number=registration_number,
        requested_category=requested_category,
        registered_county=registered_county,
        registered_office_siruta=registered_office_siruta,
        contact_name=contact_name,
        role=role,
        email=email,
        account_first_name=first_name,
        account_last_name=last_name,
        account_username=username,
        password_hash=make_password(password),
        credentials_supplied_at=now,
        status=ProviderRegistrationRequest.Status.REVIEW_PENDING,
        token_digest=_token_digest(secrets.token_urlsafe(32)),
        token_expires_at=now,
        privacy_notice_version=PRIVACY_NOTICE_VERSION,
        consented_at=now,
    )
    ProviderRepresentationEvidence.objects.create(
        registration=registration, **evidence_values
    )
    return registration


def deliver_provider_registration_email(
    *, registration: ProviderRegistrationRequest, confirmation_url: str
) -> bool:
    """Send the address-verification link and persist the delivery outcome."""

    try:
        send_mail(
            subject=(
                "Confirmă înscrierea / Confirm your registration: "
                f"{registration.legal_name}"
            ),
            message=(
                f"Bună, {registration.contact_name},\n\n"
                f"Ai cerut înscrierea firmei {registration.legal_name} pe "
                "ServiciiAproape. Confirmă adresa de e-mail în următoarele 24 de "
                f"ore:\n\n{confirmation_url}\n\n"
                "Confirmarea nu creează un cont și nu publică firma. Datele juridice "
                "vor fi verificate administrativ înainte ca solicitarea să continue."
                "\n\nDacă nu ai făcut această solicitare, ignoră mesajul."
                "\n\n--- English ---\n\n"
                f"Hello, {registration.contact_name},\n\n"
                f"You requested to register {registration.legal_name} on "
                "ServiciiAproape. Confirm your email address within the next 24 "
                f"hours:\n\n{confirmation_url}\n\n"
                "Confirmation does not create an account or publish the company. "
                "The legal details will be reviewed before the request continues."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[registration.email],
            fail_silently=False,
        )
    except Exception as error:
        ProviderRegistrationRequest.objects.filter(pk=registration.pk).update(
            email_delivery_state=ProviderRegistrationRequest.DeliveryState.FAILED
        )
        security_logger.error(
            "Provider registration e-mail delivery failed.",
            extra={
                "event": "provider_registration_delivery_failed",
                "exception_type": type(error).__name__,
            },
        )
        return False
    ProviderRegistrationRequest.objects.filter(pk=registration.pk).update(
        email_delivery_state=ProviderRegistrationRequest.DeliveryState.SENT
    )
    return True


def provider_registration_for_token(
    token: str,
) -> ProviderRegistrationRequest | None:
    """Resolve a valid confirmation token without changing application state."""

    if not token or len(token) > 128:
        return None
    return ProviderRegistrationRequest.objects.filter(
        token_digest=_token_digest(token),
        status__in=(
            ProviderRegistrationRequest.Status.EMAIL_PENDING,
            ProviderRegistrationRequest.Status.REVIEW_PENDING,
        ),
        token_expires_at__gt=timezone.now(),
    ).first()


@transaction.atomic
def verify_provider_registration_email(token: str) -> ProviderRegistrationRequest:
    """Move one valid registration to administrative review exactly once."""

    registration = ProviderRegistrationRequest.objects.select_for_update().filter(
        token_digest=_token_digest(token)
    ).first()
    if not registration or registration.token_expires_at <= timezone.now():
        raise ValueError(_("Linkul de confirmare este invalid sau a expirat."))
    if registration.status == ProviderRegistrationRequest.Status.REVIEW_PENDING:
        return registration
    if registration.status != ProviderRegistrationRequest.Status.EMAIL_PENDING:
        raise ValueError(_("Linkul de confirmare nu mai este activ."))
    registration.status = ProviderRegistrationRequest.Status.REVIEW_PENDING
    registration.email_verified_at = timezone.now()
    registration.save(update_fields=("status", "email_verified_at"))
    return registration


def _require_reviewer(reviewer) -> None:
    """Fail closed unless the actor can review unlisted-company registrations."""

    if not reviewer.is_active or not reviewer.is_staff or not reviewer.has_perm(
        "services.review_provider_registration"
    ):
        raise PermissionError("Nu ai permisiunea de a verifica înscrieri de firme.")


@transaction.atomic
def convert_provider_registration_to_claim(
    *,
    registration_id: int,
    reviewer,
    verified_registration_number: str,
    review_note: str,
    acknowledgement: str,
) -> ProviderClaimRequest:
    """Link a verified legal identity and continue through the existing claim review."""

    _require_reviewer(reviewer)
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea administrativă nu este validă.")
    note = " ".join(review_note.split())
    registration_number = " ".join(verified_registration_number.upper().split())
    if len(note) < 8 or not registration_number:
        raise ValueError("Identitatea verificată și baza deciziei sunt obligatorii.")
    registration = ProviderRegistrationRequest.objects.select_for_update().get(
        pk=registration_id
    )
    if registration.status != ProviderRegistrationRequest.Status.REVIEW_PENDING:
        raise ValueError("Numai o înscriere aflată în verificare poate continua.")
    business, _created = BusinessIdentity.objects.get_or_create(
        registration_number=registration_number
    )
    now = timezone.now()
    claim = ProviderClaimRequest.objects.create(
        business=business,
        legal_name_at_request=registration.legal_name,
        contact_name=registration.contact_name,
        role=registration.role,
        email=registration.email,
        account_first_name=registration.account_first_name,
        account_last_name=registration.account_last_name,
        account_username=registration.account_username,
        password_hash=registration.password_hash,
        credentials_supplied_at=registration.credentials_supplied_at,
        status=ProviderClaimRequest.Status.REVIEW_PENDING,
        token_digest=_token_digest(secrets.token_urlsafe(32)),
        token_expires_at=now,
        email_verified_at=registration.email_verified_at,
        email_delivery_state=ProviderClaimRequest.DeliveryState.SENT,
        privacy_notice_version=registration.privacy_notice_version,
        consented_at=registration.consented_at,
    )
    try:
        evidence = ProviderRepresentationEvidence.objects.select_for_update().get(
            registration=registration
        )
    except ProviderRepresentationEvidence.DoesNotExist as error:
        raise ValueError(
            "Înscrierea nu conține dovada dreptului de reprezentare."
        ) from error
    evidence.registration = None
    evidence.claim = claim
    evidence.save(update_fields=("registration", "claim"))
    registration.status = ProviderRegistrationRequest.Status.CONVERTED
    registration.linked_business = business
    registration.converted_claim = claim
    registration.reviewed_at = now
    registration.reviewed_by = reviewer
    registration.review_note = note
    registration.review_policy_version = REVIEW_POLICY_VERSION
    registration.password_hash = ""
    registration.save(
        update_fields=(
            "status",
            "linked_business",
            "converted_claim",
            "reviewed_at",
            "reviewed_by",
            "review_note",
            "review_policy_version",
            "password_hash",
        )
    )
    return claim


@transaction.atomic
def reject_provider_registration(
    *, registration_id: int, reviewer, review_note: str, acknowledgement: str
) -> ProviderRegistrationRequest:
    """Reject a reviewed intake without creating a legal identity."""

    _require_reviewer(reviewer)
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea administrativă nu este validă.")
    note = " ".join(review_note.split())
    if len(note) < 8:
        raise ValueError("Baza deciziei trebuie documentată.")
    registration = ProviderRegistrationRequest.objects.select_for_update().get(
        pk=registration_id
    )
    if registration.status != ProviderRegistrationRequest.Status.REVIEW_PENDING:
        raise ValueError("Numai o înscriere aflată în verificare poate fi respinsă.")
    registration.status = ProviderRegistrationRequest.Status.REJECTED
    registration.reviewed_at = timezone.now()
    registration.reviewed_by = reviewer
    registration.review_note = note
    registration.review_policy_version = REVIEW_POLICY_VERSION
    registration.password_hash = ""
    registration.save(
        update_fields=(
            "status",
            "reviewed_at",
            "reviewed_by",
            "review_note",
            "review_policy_version",
            "password_hash",
        )
    )
    return registration
