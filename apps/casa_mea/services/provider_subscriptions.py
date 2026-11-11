"""Audited, administrator-managed provider subscription entitlements."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import ProviderMembership, ProviderProfile, ProviderSubscription, ProviderSubscriptionEvent


SUBSCRIPTION_POLICY_VERSION = "test-subscription-v1"
SUBSCRIPTION_ACKNOWLEDGEMENT = (
    "Confirm activarea manuală a abonamentului de test pentru acest profil."
)
SUBSCRIPTION_PERIOD = timedelta(days=30)
SIMULATED_CHECKOUT_POLICY_VERSION = "simulated-v1"
SIMULATED_CHECKOUT_ACKNOWLEDGEMENT = (
    "Confirm simularea fără date de plată, tranzacție sau factură."
)


@dataclass(frozen=True)
class ProviderSubscriptionState:
    """Current effective entitlement without mutating an absent or expired record."""

    code: str
    label: str
    period_ends_at: datetime | None
    revision: int

    @property
    def is_active(self) -> bool:
        return self.code == "active"


def _require_manager(actor) -> None:
    if (
        not actor.is_active
        or not actor.is_staff
        or not actor.has_perm("services.manage_provider_subscription")
    ):
        raise PermissionError("Nu ai permisiunea de administrare a abonamentelor.")


def _require_active_owner(profile: ProviderProfile) -> None:
    if profile.state != ProviderProfile.State.DRAFT or not ProviderMembership.objects.filter(
        profile=profile,
        state=ProviderMembership.State.ACTIVE,
        user__is_active=True,
    ).exists():
        raise ValueError("Profilul nu are un proprietar activ.")


def provider_subscription_state(
    profile: ProviderProfile,
    *,
    at=None,
    lock: bool = False,
) -> ProviderSubscriptionState:
    """Project inactive, expired, or active entitlement state for one profile."""

    subscription = (
        profile._state.fields_cache.get("subscription")
        if not lock and "subscription" in profile._state.fields_cache
        else (
            ProviderSubscription.objects.select_for_update()
            if lock
            else ProviderSubscription.objects
        ).filter(profile=profile).first()
    )
    if subscription is None:
        return ProviderSubscriptionState("inactive", _("Inactiv"), None, 0)
    if subscription.status == ProviderSubscription.Status.INACTIVE:
        return ProviderSubscriptionState(
            "inactive", _("Inactiv"), None, subscription.revision
        )
    instant = at or timezone.now()
    if subscription.period_ends_at <= instant:
        return ProviderSubscriptionState(
            "expired", _("Expirat"), subscription.period_ends_at, subscription.revision
        )
    return ProviderSubscriptionState(
        "active", _("Activ"), subscription.period_ends_at, subscription.revision
    )


def require_active_provider_subscription(
    profile: ProviderProfile,
    *,
    lock: bool = False,
) -> ProviderSubscription:
    """Return the active entitlement or fail closed at the publication boundary."""

    query = ProviderSubscription.objects
    if lock:
        query = query.select_for_update()
    subscription = query.filter(profile=profile).first()
    if (
        subscription is None
        or subscription.status != ProviderSubscription.Status.ACTIVE
        or subscription.period_ends_at <= timezone.now()
    ):
        raise ValueError("Profilul necesită un abonament activ înainte de publicare.")
    return subscription


@transaction.atomic
def activate_or_extend_provider_subscription(
    *,
    profile_id: int,
    actor,
    expected_revision: int,
    internal_note: str,
    acknowledgement: str,
) -> ProviderSubscription:
    """Activate or extend a fixed 30-day test entitlement under a profile lock."""

    _require_manager(actor)
    if acknowledgement != SUBSCRIPTION_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea abonamentului de test lipsește.")
    note = " ".join(internal_note.split())
    if len(note) < 8:
        raise ValueError("Nota internă trebuie să documenteze activarea.")

    profile = ProviderProfile.objects.select_for_update().get(pk=profile_id)
    _require_active_owner(profile)
    subscription, _created = ProviderSubscription.objects.select_for_update().get_or_create(
        profile=profile
    )
    if subscription.revision != expected_revision:
        raise ValueError("Abonamentul s-a modificat între timp; reîncarcă pagina.")

    instant = timezone.now()
    was_effectively_active = (
        subscription.status == ProviderSubscription.Status.ACTIVE
        and subscription.period_ends_at > instant
    )
    previous_status = subscription.status
    previous_end = subscription.period_ends_at
    subscription.status = ProviderSubscription.Status.ACTIVE
    subscription.period_started_at = (
        subscription.period_started_at if was_effectively_active else instant
    )
    subscription.period_ends_at = (
        subscription.period_ends_at + SUBSCRIPTION_PERIOD
        if was_effectively_active
        else instant + SUBSCRIPTION_PERIOD
    )
    subscription.revision += 1
    subscription.save(
        update_fields=(
            "status",
            "period_started_at",
            "period_ends_at",
            "revision",
            "updated_at",
        )
    )
    ProviderSubscriptionEvent.objects.create(
        subscription=subscription,
        action=(
            ProviderSubscriptionEvent.Action.EXTEND
            if was_effectively_active
            else ProviderSubscriptionEvent.Action.ACTIVATE
        ),
        previous_status=previous_status,
        new_status=subscription.status,
        previous_period_ends_at=previous_end,
        new_period_ends_at=subscription.period_ends_at,
        revision=subscription.revision,
        internal_note=note,
        policy_version=SUBSCRIPTION_POLICY_VERSION,
        acknowledgement=acknowledgement,
        actor=actor,
    )
    return subscription


@transaction.atomic
def activate_provider_subscription_from_simulated_checkout(
    *,
    profile_id: int,
    actor,
    expected_revision: int,
    acknowledgement: str,
) -> tuple[ProviderSubscription, bool]:
    """Grant one idempotent 30-day entitlement from the explicit demo checkout."""

    if not getattr(settings, "SIMULATED_CHECKOUT_ENABLED", False):
        raise PermissionError("Fluxul demonstrativ de abonare nu este disponibil.")
    if acknowledgement != SIMULATED_CHECKOUT_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea simulării lipsește.")
    if not actor.is_active:
        raise PermissionError("Contul furnizorului nu este activ.")

    profile = ProviderProfile.objects.select_for_update().get(pk=profile_id)
    if not ProviderMembership.objects.filter(
        profile=profile,
        user=actor,
        state=ProviderMembership.State.ACTIVE,
    ).exists():
        raise PermissionError("Nu ai acces la abonamentul acestui profil.")
    _require_active_owner(profile)

    subscription, _created = ProviderSubscription.objects.select_for_update().get_or_create(
        profile=profile
    )
    instant = timezone.now()
    if (
        subscription.status == ProviderSubscription.Status.ACTIVE
        and subscription.period_ends_at > instant
    ):
        return subscription, False
    if subscription.revision != expected_revision:
        raise ValueError("Abonamentul s-a modificat între timp; reîncarcă pagina.")

    previous_status = subscription.status
    previous_end = subscription.period_ends_at
    subscription.status = ProviderSubscription.Status.ACTIVE
    subscription.period_started_at = instant
    subscription.period_ends_at = instant + SUBSCRIPTION_PERIOD
    subscription.revision += 1
    subscription.save(
        update_fields=(
            "status",
            "period_started_at",
            "period_ends_at",
            "revision",
            "updated_at",
        )
    )
    ProviderSubscriptionEvent.objects.create(
        subscription=subscription,
        action=(
            ProviderSubscriptionEvent.Action.EXTEND
            if previous_status == ProviderSubscription.Status.ACTIVE
            else ProviderSubscriptionEvent.Action.ACTIVATE
        ),
        previous_status=previous_status,
        new_status=ProviderSubscription.Status.ACTIVE,
        previous_period_ends_at=previous_end,
        new_period_ends_at=subscription.period_ends_at,
        revision=subscription.revision,
        internal_note="Activare prin checkout demonstrativ; nicio plată procesată.",
        policy_version=SIMULATED_CHECKOUT_POLICY_VERSION,
        acknowledgement=acknowledgement,
        actor=actor,
    )
    return subscription, True


@transaction.atomic
def deactivate_provider_subscription(
    *,
    profile_id: int,
    actor,
    expected_revision: int,
    internal_note: str,
    acknowledgement: str,
) -> ProviderSubscription:
    """Deactivate an existing entitlement without changing publication history."""

    _require_manager(actor)
    if acknowledgement != SUBSCRIPTION_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea abonamentului de test lipsește.")
    note = " ".join(internal_note.split())
    if len(note) < 8:
        raise ValueError("Nota internă trebuie să documenteze dezactivarea.")

    profile = ProviderProfile.objects.select_for_update().get(pk=profile_id)
    subscription = ProviderSubscription.objects.select_for_update().filter(
        profile=profile
    ).first()
    current_revision = subscription.revision if subscription else 0
    if current_revision != expected_revision:
        raise ValueError("Abonamentul s-a modificat între timp; reîncarcă pagina.")
    if subscription is None or subscription.status == ProviderSubscription.Status.INACTIVE:
        raise ValueError("Abonamentul este deja inactiv.")

    previous_end = subscription.period_ends_at
    subscription.status = ProviderSubscription.Status.INACTIVE
    subscription.period_started_at = None
    subscription.period_ends_at = None
    subscription.revision += 1
    subscription.save(
        update_fields=(
            "status",
            "period_started_at",
            "period_ends_at",
            "revision",
            "updated_at",
        )
    )
    ProviderSubscriptionEvent.objects.create(
        subscription=subscription,
        action=ProviderSubscriptionEvent.Action.DEACTIVATE,
        previous_status=ProviderSubscription.Status.ACTIVE,
        new_status=ProviderSubscription.Status.INACTIVE,
        previous_period_ends_at=previous_end,
        new_period_ends_at=None,
        revision=subscription.revision,
        internal_note=note,
        policy_version=SUBSCRIPTION_POLICY_VERSION,
        acknowledgement=acknowledgement,
        actor=actor,
    )
    return subscription
