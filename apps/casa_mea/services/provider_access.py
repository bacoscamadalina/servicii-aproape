"""Audited provider approval, invitation, activation and membership access."""

from datetime import timedelta
import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    AccountLoginThrottle,
    BusinessIdentity,
    ProviderAccountInvitation,
    ProviderClaimRequest,
    ProviderMembership,
    ProviderPasswordResetThrottle,
    ProviderProfile,
    ProviderRepresentationEvidence,
    ProviderPublicationScope,
)
from .representation_evidence import representation_evidence_is_valid


APPROVAL_POLICY_VERSION = "2026-08-25-v1"
INVITATION_LIFETIME = timedelta(hours=24)
PASSWORD_RESET_SEND_LIMIT = 3
PASSWORD_RESET_WINDOW = timedelta(minutes=15)
PASSWORD_RESET_THROTTLE_RETENTION = timedelta(hours=24)
PASSWORD_RESET_THROTTLE_CLEANUP_BATCH = 100
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
LOGIN_THROTTLE_RETENTION = timedelta(hours=24)
LOGIN_THROTTLE_CLEANUP_BATCH = 100
REVIEW_ACKNOWLEDGEMENT = "VERIFIED_REPRESENTATION_SEPARATE_FROM_ONRC"
security_logger = logging.getLogger("services.security")


def _token_digest(token: str) -> str:
    """Return the irreversible lookup digest for a bearer credential."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_reviewer(reviewer) -> None:
    """Fail closed unless the actor has the dedicated staff permission."""

    if not reviewer.is_active or not reviewer.is_staff or not reviewer.has_perm(
        "services.review_provider_claim"
    ):
        raise PermissionError("Nu ai permisiunea de a decide revendicări.")


@transaction.atomic
def approve_provider_claim(
    *,
    claim_id: int,
    reviewer,
    review_note: str,
    acknowledgement: str,
) -> tuple[ProviderProfile, ProviderAccountInvitation | None, str | None]:
    """Approve one claim and create either its ready account or a legacy invitation."""

    _require_reviewer(reviewer)
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea administrativă nu este validă.")
    note = " ".join(review_note.split())
    if len(note) < 8:
        raise ValueError("Baza deciziei trebuie documentată.")

    claim = (
        ProviderClaimRequest.objects.select_for_update()
        .select_related("business")
        .get(pk=claim_id)
    )
    BusinessIdentity.objects.select_for_update().get(pk=claim.business_id)
    if claim.status != ProviderClaimRequest.Status.REVIEW_PENDING:
        raise ValueError("Numai o cerere aflată în verificare poate fi aprobată.")
    if not claim.email_verified_at and not claim.credentials_supplied_at:
        raise ValueError("Adresa de e-mail nu este confirmată.")
    try:
        evidence = claim.representation_evidence
    except ProviderRepresentationEvidence.DoesNotExist:
        evidence = None
    if not representation_evidence_is_valid(evidence):
        raise ValueError(
            "Dovada dreptului de reprezentare lipsește sau nu mai este intactă."
        )
    email = claim.email.strip().lower()
    reviewer_email = (reviewer.email or "").strip().lower()
    if reviewer_email and reviewer_email == email:
        raise ValueError("Evaluatorul nu își poate aproba propria revendicare.")

    User = get_user_model()
    username = claim.account_username or email
    if User.objects.filter(
        Q(username__iexact=username) | Q(email__iexact=email)
    ).exists():
        raise ValueError("Există deja un cont asociat acestei adrese de e-mail.")

    user = User(
        username=(
            username
            if claim.credentials_supplied_at
            else f"provider-{claim.pk}-{secrets.token_hex(8)}"
        ),
        email=email,
        first_name=(claim.account_first_name or claim.contact_name)[:150],
        last_name=claim.account_last_name[:150],
        is_active=bool(claim.credentials_supplied_at),
    )
    if claim.credentials_supplied_at:
        if not claim.password_hash:
            raise ValueError("Datele de autentificare ale cererii nu mai sunt disponibile.")
        user.password = claim.password_hash
    else:
        user.set_unusable_password()
    user.save()
    now = timezone.now()
    profile = ProviderProfile.objects.create(
        business=claim.business,
        approved_claim=claim,
        display_name=claim.legal_name_at_request[:160],
    )
    ProviderPublicationScope.objects.create(profile=profile)
    membership = ProviderMembership.objects.create(
        profile=profile,
        user=user,
        state=(
            ProviderMembership.State.ACTIVE
            if claim.credentials_supplied_at
            else ProviderMembership.State.INVITED
        ),
        invited_at=now,
        activated_at=now if claim.credentials_supplied_at else None,
    )
    token = None if claim.credentials_supplied_at else secrets.token_urlsafe(32)
    invitation = (
        None
        if token is None
        else ProviderAccountInvitation.objects.create(
            membership=membership,
            token_digest=_token_digest(token),
            expires_at=now + INVITATION_LIFETIME,
        )
    )
    claim.status = ProviderClaimRequest.Status.APPROVED
    claim.reviewed_at = now
    claim.reviewed_by = reviewer
    claim.review_note = note
    claim.approval_policy_version = APPROVAL_POLICY_VERSION
    claim.password_hash = ""
    claim.save(
        update_fields=(
            "status",
            "reviewed_at",
            "reviewed_by",
            "review_note",
            "approval_policy_version",
            "password_hash",
        )
    )
    return profile, invitation, token


@transaction.atomic
def reject_provider_claim(
    *,
    claim_id: int,
    reviewer,
    review_note: str,
    acknowledgement: str,
) -> ProviderClaimRequest:
    """Reject one verified claim without creating marketplace identity records."""

    _require_reviewer(reviewer)
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea administrativă nu este validă.")
    note = " ".join(review_note.split())
    if len(note) < 8:
        raise ValueError("Baza deciziei trebuie documentată.")
    claim = ProviderClaimRequest.objects.select_for_update().get(pk=claim_id)
    if claim.status != ProviderClaimRequest.Status.REVIEW_PENDING:
        raise ValueError("Numai o cerere aflată în verificare poate fi respinsă.")
    now = timezone.now()
    claim.status = ProviderClaimRequest.Status.REJECTED
    claim.reviewed_at = now
    claim.reviewed_by = reviewer
    claim.review_note = note
    claim.approval_policy_version = APPROVAL_POLICY_VERSION
    claim.password_hash = ""
    claim.save(
        update_fields=(
            "status",
            "reviewed_at",
            "reviewed_by",
            "review_note",
            "approval_policy_version",
            "password_hash",
        )
    )
    return claim


def deliver_provider_invitation_email(
    *, invitation: ProviderAccountInvitation, activation_url: str
) -> bool:
    """Deliver an activation link and persist only its outcome, never its token."""

    membership = invitation.membership
    try:
        send_mail(
            subject=(
                "Activează profilul / Activate your profile: "
                f"{membership.profile.display_name}"
            ),
            message=(
                f"Bună, {membership.user.first_name},\n\n"
                "Revendicarea a fost aprobată administrativ. Activează contul "
                "ServiciiAproape și setează parola în următoarele 24 de ore:\n\n"
                f"{activation_url}\n\n"
                "Profilul rămâne ciornă și nu este publicat automat. Dacă nu ai "
                "solicitat accesul, nu folosi linkul și contactează administratorul.\n\n"
                "--- English ---\n\n"
                f"Hello, {membership.user.first_name},\n\n"
                "Your claim was approved by an administrator. Activate your "
                "ServiciiAproape account and set your password within the next "
                "24 hours:\n\n"
                f"{activation_url}\n\n"
                "The profile remains a draft and is not published automatically. "
                "If you did not request access, do not use the link and contact "
                "the administrator."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[membership.user.email],
            fail_silently=False,
        )
    except Exception as error:
        ProviderAccountInvitation.objects.filter(pk=invitation.pk).update(
            delivery_state=ProviderAccountInvitation.DeliveryState.FAILED
        )
        security_logger.error(
            "Provider invitation e-mail delivery failed.",
            extra={
                "event": "provider_invitation_delivery_failed",
                "exception_type": type(error).__name__,
            },
        )
        return False
    ProviderAccountInvitation.objects.filter(pk=invitation.pk).update(
        delivery_state=ProviderAccountInvitation.DeliveryState.SENT
    )
    return True


@transaction.atomic
def rotate_provider_invitation(
    *, claim_id: int, reviewer, acknowledgement: str
) -> tuple[ProviderAccountInvitation, str]:
    """Rotate an unused activation token without duplicating account records."""

    _require_reviewer(reviewer)
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea administrativă nu este validă.")
    claim = ProviderClaimRequest.objects.select_for_update().get(pk=claim_id)
    if claim.status != ProviderClaimRequest.Status.APPROVED:
        raise ValueError("Numai o revendicare aprobată poate primi o invitație nouă.")
    profile = ProviderProfile.objects.select_for_update().get(approved_claim=claim)
    membership = ProviderMembership.objects.select_for_update().get(profile=profile)
    invitation = ProviderAccountInvitation.objects.select_for_update().get(
        membership=membership
    )
    if (
        membership.state != ProviderMembership.State.INVITED
        or membership.user.is_active
        or invitation.accepted_at is not None
    ):
        raise ValueError("Contul a fost deja activat sau accesul nu mai este eligibil.")
    token = secrets.token_urlsafe(32)
    invitation.token_digest = _token_digest(token)
    invitation.expires_at = timezone.now() + INVITATION_LIFETIME
    invitation.delivery_state = ProviderAccountInvitation.DeliveryState.PENDING
    invitation.save(update_fields=("token_digest", "expires_at", "delivery_state"))
    return invitation, token


def provider_invitation_for_token(token: str) -> ProviderAccountInvitation | None:
    """Resolve a usable invitation for a read-only landing page."""

    if not token or len(token) > 128:
        return None
    return (
        ProviderAccountInvitation.objects.select_related(
            "membership__user", "membership__profile"
        )
        .filter(
            token_digest=_token_digest(token),
            accepted_at__isnull=True,
            expires_at__gt=timezone.now(),
            delivery_state=ProviderAccountInvitation.DeliveryState.SENT,
            membership__state=ProviderMembership.State.INVITED,
            membership__user__is_active=False,
        )
        .first()
    )


@transaction.atomic
def activate_provider_invitation(
    *, token: str, new_password: str
) -> ProviderMembership:
    """Consume one invitation and activate its user and membership atomically."""

    invitation = (
        ProviderAccountInvitation.objects.select_for_update()
        .select_related("membership__user", "membership__profile")
        .filter(token_digest=_token_digest(token))
        .first()
    )
    now = timezone.now()
    if (
        not invitation
        or invitation.accepted_at is not None
        or invitation.expires_at <= now
        or invitation.delivery_state != ProviderAccountInvitation.DeliveryState.SENT
    ):
        raise ValueError(_("Invitația este invalidă, expirată sau deja folosită."))
    membership = ProviderMembership.objects.select_for_update().get(
        pk=invitation.membership_id
    )
    user = get_user_model().objects.select_for_update().get(pk=membership.user_id)
    if membership.state != ProviderMembership.State.INVITED or user.is_active:
        raise ValueError(_("Invitația nu mai poate fi folosită."))
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.is_active = True
    user.save(update_fields=("password", "is_active"))
    membership.state = ProviderMembership.State.ACTIVE
    membership.activated_at = now
    membership.save(update_fields=("state", "activated_at"))
    invitation.accepted_at = now
    invitation.save(update_fields=("accepted_at",))
    return membership


def active_provider_membership(user) -> ProviderMembership | None:
    """Return the caller's one active membership or fail closed on ambiguity."""

    if not user.is_authenticated or not user.is_active:
        return None
    memberships = list(
        ProviderMembership.objects.select_related("profile", "profile__business")
        .filter(
            user=user,
            state=ProviderMembership.State.ACTIVE,
            profile__state=ProviderProfile.State.DRAFT,
        )
        .order_by("pk")[:2]
    )
    return memberships[0] if len(memberships) == 1 else None


def _account_login_key_digest(*, scope: str, identifier: str) -> str:
    """Return a secret-keyed digest so persisted login keys reveal no identity."""

    normalized_identifier = identifier.strip().casefold()
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"account-login:{scope}:{normalized_identifier}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def claim_account_login_attempt(*, scope: str, identifier: str) -> bool:
    """Atomically reserve one login attempt from the shared fifteen-minute budget."""

    digest = _account_login_key_digest(scope=scope, identifier=identifier)
    now = timezone.now()
    expired_ids = list(
        AccountLoginThrottle.objects.filter(
            window_started_at__lt=now - LOGIN_THROTTLE_RETENTION
        )
        .exclude(key_digest=digest)
        .order_by("window_started_at", "pk")
        .values_list("pk", flat=True)[:LOGIN_THROTTLE_CLEANUP_BATCH]
    )
    if expired_ids:
        AccountLoginThrottle.objects.filter(
            pk__in=expired_ids,
            window_started_at__lt=now - LOGIN_THROTTLE_RETENTION,
        ).delete()
    throttle, _created = AccountLoginThrottle.objects.select_for_update().get_or_create(
        key_digest=digest,
        defaults={"window_started_at": now, "attempt_count": 0},
    )
    if throttle.window_started_at <= now - LOGIN_ATTEMPT_WINDOW:
        throttle.window_started_at = now
        throttle.attempt_count = 0
    if throttle.attempt_count >= LOGIN_ATTEMPT_LIMIT:
        security_logger.warning(
            "Account login attempt budget exhausted.",
            extra={"event": "account_login_throttled", "scope": scope},
        )
        return False
    throttle.attempt_count += 1
    throttle.save(update_fields=("window_started_at", "attempt_count", "updated_at"))
    return True


def clear_account_login_attempts(*, scope: str, identifier: str) -> None:
    """Delete the shared attempt budget after successful account authentication."""

    AccountLoginThrottle.objects.filter(
        key_digest=_account_login_key_digest(scope=scope, identifier=identifier)
    ).delete()


@transaction.atomic
def claim_password_reset_send_slot(*, email: str, client_address: str, scope: str = "provider") -> bool:
    """Atomically reserve one role-scoped reset send without storing request PII."""

    if scope not in {"provider", "customer"}:
        raise ValueError("Unsupported password-reset scope")

    normalized_email = email.strip().lower()
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{scope}-password-reset:{client_address}:{normalized_email}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    now = timezone.now()
    expired_ids = list(
        ProviderPasswordResetThrottle.objects.filter(
            window_started_at__lt=now - PASSWORD_RESET_THROTTLE_RETENTION
        )
        .exclude(key_digest=digest)
        .order_by("window_started_at", "pk")
        .values_list("pk", flat=True)[:PASSWORD_RESET_THROTTLE_CLEANUP_BATCH]
    )
    if expired_ids:
        ProviderPasswordResetThrottle.objects.filter(
            pk__in=expired_ids,
            window_started_at__lt=now - PASSWORD_RESET_THROTTLE_RETENTION,
        ).delete()
    throttle, _created = (
        ProviderPasswordResetThrottle.objects.select_for_update().get_or_create(
            key_digest=digest,
            defaults={"window_started_at": now, "send_count": 0},
        )
    )
    if throttle.window_started_at <= now - PASSWORD_RESET_WINDOW:
        throttle.window_started_at = now
        throttle.send_count = 0
    if throttle.send_count >= PASSWORD_RESET_SEND_LIMIT:
        security_logger.warning(
            "Password-reset send budget exhausted.",
            extra={"event": "password_reset_throttled", "scope": scope},
        )
        return False
    throttle.send_count += 1
    throttle.save(update_fields=("window_started_at", "send_count", "updated_at"))
    return True
