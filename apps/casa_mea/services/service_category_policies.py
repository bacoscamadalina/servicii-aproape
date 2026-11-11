"""Audited operational controls for the fixed public service taxonomy."""

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from .catalog import CATEGORIES
from .models import ServiceCategoryPolicy, ServiceCategoryPolicyEvent


CATEGORY_POLICY_ACKNOWLEDGEMENT = "OPERATIONAL_POLICY_WITHOUT_LEGAL_DATA_MUTATION"
CATEGORY_CATALOGUE = {
    slug: (label, description) for slug, label, description in CATEGORIES
}


@dataclass(frozen=True)
class ServiceCategoryRecord:
    """One presentation-ready category joined to its operational policy."""

    slug: str
    label: object
    description: object
    state: str
    display_order: int
    revision: int

    @property
    def accepts_new_providers(self) -> bool:
        return self.state == ServiceCategoryPolicy.State.ACTIVE

    @property
    def is_publicly_discoverable(self) -> bool:
        return self.state != ServiceCategoryPolicy.State.HIDDEN


def service_category_records() -> tuple[ServiceCategoryRecord, ...]:
    """Return the complete ordered policy projection and reject taxonomy drift."""

    if getattr(settings, "READ_ONLY_PREVIEW", False):
        # The immutable preview has no operational database by contract.
        return tuple(
            ServiceCategoryRecord(
                slug=slug,
                label=label,
                description=description,
                state=ServiceCategoryPolicy.State.ACTIVE,
                display_order=index * 10,
                revision=0,
            )
            for index, (slug, label, description) in enumerate(CATEGORIES, start=1)
        )
    policies = tuple(ServiceCategoryPolicy.objects.all())
    policy_slugs = {policy.category for policy in policies}
    catalogue_slugs = set(CATEGORY_CATALOGUE)
    if policy_slugs != catalogue_slugs:
        raise RuntimeError(
            "Politicile categoriilor nu corespund taxonomiei aplicației. "
            "Rulează migrările înainte de a porni serviciul."
        )
    return tuple(
        ServiceCategoryRecord(
            slug=policy.category,
            label=CATEGORY_CATALOGUE[policy.category][0],
            description=CATEGORY_CATALOGUE[policy.category][1],
            state=policy.state,
            display_order=policy.display_order,
            revision=policy.revision,
        )
        for policy in policies
    )


def publicly_discoverable_service_categories() -> tuple[ServiceCategoryRecord, ...]:
    """Keep paused categories discoverable while hiding explicitly removed ones."""

    return tuple(
        record for record in service_category_records()
        if record.is_publicly_discoverable
    )


def new_provider_service_categories() -> tuple[ServiceCategoryRecord, ...]:
    """Return only categories accepting a new provider declaration."""

    return tuple(
        record for record in service_category_records()
        if record.accepts_new_providers
    )


def editable_provider_service_slugs(
    *, authorized_categories, current_services
) -> frozenset[str]:
    """Allow active authorized choices while preserving valid existing selections."""

    known_categories = frozenset(CATEGORY_CATALOGUE)
    active_categories = frozenset(
        record.slug for record in new_provider_service_categories()
    )
    return (
        frozenset(authorized_categories) & active_categories
    ) | (frozenset(current_services) & known_categories)


@transaction.atomic
def update_service_category_policy(
    *,
    category: str,
    state: str,
    display_order: int,
    expected_revision: int,
    reason: str,
    actor,
    acknowledgement: str,
) -> tuple[ServiceCategoryPolicy, bool]:
    """Lock, compare and append one authorized operational policy revision."""

    if not (
        actor.is_active
        and actor.is_staff
        and actor.has_perm("services.manage_service_category_policy")
    ):
        raise PermissionError("Nu ai permisiunea de a administra categoriile.")
    if acknowledgement != CATEGORY_POLICY_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea limitei operaționale este obligatorie.")
    if category not in CATEGORY_CATALOGUE:
        raise ValueError("Categoria nu aparține taxonomiei aplicației.")
    if state not in ServiceCategoryPolicy.State.values:
        raise ValueError("Starea categoriei nu este validă.")
    normalized_reason = " ".join(reason.split())
    if not 8 <= len(normalized_reason) <= 500:
        raise ValueError("Motivul trebuie să aibă între 8 și 500 de caractere.")
    if not 1 <= display_order <= 99:
        raise ValueError("Poziția trebuie să fie între 1 și 99.")

    policy = ServiceCategoryPolicy.objects.select_for_update().get(category=category)
    if policy.revision != expected_revision:
        raise ValueError("Categoria a fost modificată între timp. Reîncarcă pagina.")
    if policy.state == state and policy.display_order == display_order:
        return policy, False

    previous_state = policy.state
    previous_order = policy.display_order
    policy.state = state
    policy.display_order = display_order
    policy.revision += 1
    policy.updated_by = actor
    policy.save(
        update_fields=("state", "display_order", "revision", "updated_by", "updated_at")
    )
    ServiceCategoryPolicyEvent.objects.create(
        policy=policy,
        revision=policy.revision,
        previous_state=previous_state,
        new_state=state,
        previous_order=previous_order,
        new_order=display_order,
        reason=normalized_reason,
        actor=actor,
    )
    return policy, True
