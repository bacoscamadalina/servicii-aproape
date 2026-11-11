"""Private provider-declared issuer details, without fiscal issuance authority."""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import ProviderBillingIdentity, ProviderBillingIdentityEvent
from .provider_publication import _lock_owner_profile


@transaction.atomic
def save_provider_billing_identity(*, user, expected_revision: int, values: dict[str, str]):
    """Save one owner-scoped revision; no ONRC fact or fiscal document is changed."""

    profile = _lock_owner_profile(user)
    normalized = {
        field: " ".join(values.get(field, "").split())
        for field in ("legal_name", "fiscal_identifier", "registration_number", "registered_address")
    }
    limits = {"legal_name": (2, 500), "fiscal_identifier": (2, 40),
              "registration_number": (3, 80), "registered_address": (10, 500)}
    if any(not low <= len(normalized[field]) <= high for field, (low, high) in limits.items()):
        raise ValueError(_("Completează toate datele emitentului în limitele indicate."))
    identity = ProviderBillingIdentity.objects.select_for_update().filter(profile=profile).first()
    if (identity.revision if identity else 0) != expected_revision:
        raise ValueError(_("Datele de facturare s-au modificat. Reîncarcă pagina."))
    if identity and all(getattr(identity, field) == value for field, value in normalized.items()):
        return identity, False
    if identity is None:
        identity = ProviderBillingIdentity.objects.create(
            profile=profile, updated_by=user, **normalized,
        )
    else:
        for field, value in normalized.items():
            setattr(identity, field, value)
        identity.revision += 1
        identity.updated_by = user
        identity.updated_at = timezone.now()
        identity.save(update_fields=(*normalized.keys(), "revision", "updated_by", "updated_at"))
    ProviderBillingIdentityEvent.objects.create(
        identity=identity, revision=identity.revision, actor=user, **normalized,
    )
    return identity, True
