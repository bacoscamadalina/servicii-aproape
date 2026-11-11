"""Side-effecting provider-claim lifecycle with hashed, expiring e-mail tokens."""

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
    ProviderRepresentationEvidence,
)
from .representation_evidence import representation_evidence_values


# Consent records must identify the exact public notice shown at submission.
PRIVACY_NOTICE_VERSION = settings.LEGAL_POLICY_VERSION
TOKEN_LIFETIME = timedelta(hours=24)
RATE_LIMIT_WINDOW = timedelta(minutes=15)
RATE_LIMIT_COUNT = 3
security_logger = logging.getLogger("services.security")


def _token_digest(token: str) -> str:
    """Hash a bearer token so the database never stores it in reusable form."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@transaction.atomic
def create_provider_claim_request(
    *,
    business: BusinessIdentity,
    legal_name: str,
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
) -> ProviderClaimRequest:
    """Create a review-pending request while retaining only a password hash."""

    evidence_values = representation_evidence_values(
        evidence_type=evidence_type,
        upload=evidence_document,
        declaration=representation_declaration,
    )
    now = timezone.now()
    BusinessIdentity.objects.select_for_update().get(pk=business.pk)
    recent_count = ProviderClaimRequest.objects.filter(
        business=business,
        email=email,
        created_at__gte=now - RATE_LIMIT_WINDOW,
    ).count()
    if recent_count >= RATE_LIMIT_COUNT:
        security_logger.warning(
            "Provider claim creation budget exhausted.",
            extra={"event": "provider_claim_creation_throttled", "scope": "provider"},
        )
        raise ValueError(
            _("Au fost trimise prea multe cereri. Reîncearcă peste 15 minute.")
        )
    ProviderClaimRequest.objects.filter(
        business=business,
        email=email,
        status=ProviderClaimRequest.Status.EMAIL_PENDING,
    ).update(status=ProviderClaimRequest.Status.SUPERSEDED)
    claim = ProviderClaimRequest.objects.create(
        business=business,
        legal_name_at_request=legal_name,
        contact_name=contact_name,
        role=role,
        email=email,
        account_first_name=first_name,
        account_last_name=last_name,
        account_username=username,
        password_hash=make_password(password),
        credentials_supplied_at=now,
        status=ProviderClaimRequest.Status.REVIEW_PENDING,
        token_digest=_token_digest(secrets.token_urlsafe(32)),
        token_expires_at=now,
        privacy_notice_version=PRIVACY_NOTICE_VERSION,
        consented_at=now,
    )
    ProviderRepresentationEvidence.objects.create(claim=claim, **evidence_values)
    return claim


def deliver_provider_claim_email(
    *, claim: ProviderClaimRequest, confirmation_url: str
) -> bool:
    """Send the verification link and persist delivery outcome without leaking it."""

    try:
        send_mail(
            subject=(
                f"Confirmă revendicarea / Confirm your claim: "
                f"{claim.legal_name_at_request}"
            ),
            message=(
                f"Bună, {claim.contact_name},\n\n"
                f"Ai cerut revendicarea firmei {claim.legal_name_at_request} pe "
                "ServiciiAproape. Confirmă adresa de e-mail accesând linkul de mai jos "
                "în următoarele 24 de ore:\n\n"
                f"{confirmation_url}\n\n"
                "Confirmarea e-mailului nu aprobă automat reprezentarea firmei. "
                "Cererea va intra într-o verificare administrativă separată.\n\n"
                "Dacă nu ai făcut această solicitare, ignoră mesajul.\n\n"
                "--- English ---\n\n"
                f"Hello, {claim.contact_name},\n\n"
                f"You requested to claim {claim.legal_name_at_request} on "
                "ServiciiAproape. Confirm your email address using the link below "
                "within the next 24 hours:\n\n"
                f"{confirmation_url}\n\n"
                "Email confirmation does not automatically approve your right to "
                "represent the company. The request will enter a separate "
                "administrative review.\n\n"
                "If you did not make this request, ignore this message."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[claim.email],
            fail_silently=False,
        )
    except Exception as error:
        ProviderClaimRequest.objects.filter(pk=claim.pk).update(
            email_delivery_state=ProviderClaimRequest.DeliveryState.FAILED
        )
        security_logger.error(
            "Provider claim e-mail delivery failed.",
            extra={
                "event": "provider_claim_delivery_failed",
                "exception_type": type(error).__name__,
            },
        )
        return False
    ProviderClaimRequest.objects.filter(pk=claim.pk).update(
        email_delivery_state=ProviderClaimRequest.DeliveryState.SENT
    )
    return True


def provider_claim_for_token(token: str) -> ProviderClaimRequest | None:
    """Resolve a valid token for its confirmation landing page without mutation."""

    if not token or len(token) > 128:
        return None
    return (
        ProviderClaimRequest.objects.select_related("business")
        .filter(
            token_digest=_token_digest(token),
            status__in=(
                ProviderClaimRequest.Status.EMAIL_PENDING,
                ProviderClaimRequest.Status.REVIEW_PENDING,
            ),
            token_expires_at__gt=timezone.now(),
        )
        .first()
    )


@transaction.atomic
def verify_provider_claim_email(token: str) -> ProviderClaimRequest:
    """Move one valid token to administrative review exactly once."""

    claim = ProviderClaimRequest.objects.select_for_update().filter(
        token_digest=_token_digest(token)
    ).first()
    if not claim or claim.token_expires_at <= timezone.now():
        raise ValueError(_("Linkul de confirmare este invalid sau a expirat."))
    if claim.status == ProviderClaimRequest.Status.REVIEW_PENDING:
        return claim
    if claim.status != ProviderClaimRequest.Status.EMAIL_PENDING:
        raise ValueError(_("Linkul de confirmare nu mai este activ."))
    claim.status = ProviderClaimRequest.Status.REVIEW_PENDING
    claim.email_verified_at = timezone.now()
    claim.save(update_fields=("status", "email_verified_at"))
    return claim
