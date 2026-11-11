"""Reviewed direct-service evidence kept separate from registry-derived facts."""

from datetime import datetime
import re

from django.contrib.auth import get_user_model
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from .locations import read_locations_catalogue
from .models import (
    BusinessIdentity,
    ImportRun,
    RegisteredBusinessSnapshot,
    VerifiedServiceCoverage,
    VerifiedServiceEvidence,
)
from .staging import available_categories


EVIDENCE_ACKNOWLEDGEMENT = "DIRECT_SERVICE_SOURCE_REVIEWED"


def valid_service_evidence(
    *, county: str, categories: set[str], instant: datetime | None = None
) -> list[VerifiedServiceEvidence]:
    """Return current evidence after the mutable expiry/revocation gates."""

    now = instant or timezone.now()
    return list(VerifiedServiceEvidence.objects.filter(
        state=VerifiedServiceEvidence.State.ACTIVE,
        revoked_at=None,
        expires_at__gt=now,
        category__in=categories,
        coverage__county=county,
    ).select_related("business").distinct())


@transaction.atomic
def record_verified_service_evidence(
    *,
    business: BusinessIdentity,
    category: str,
    source_url: str,
    source_title: str,
    identity_reference: str,
    evidence_summary: str,
    coverage_counties: list[str],
    retrieved_at: datetime,
    content_sha256: str,
    expires_at: datetime,
    actor_username: str,
    acknowledgement: str,
) -> VerifiedServiceEvidence:
    """Append one reviewed evidence version without editing registry facts."""

    actor = get_user_model().objects.get(username=actor_username, is_active=True)
    if not actor.has_perm("services.verify_service_evidence"):
        raise ValueError("Operatorul nu are permisiunea de verificare a serviciilor")
    if acknowledgement != EVIDENCE_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea reviziei sursei directe lipsește")
    if category not in available_categories():
        raise ValueError("Categoria serviciului nu este recunoscută")
    counties = sorted(set(coverage_counties))
    if not counties or set(counties) - set(read_locations_catalogue()):
        raise ValueError("Acoperirea trebuie să conțină numai județe SIRUTA cunoscute")
    now = timezone.now()
    if expires_at <= now:
        raise ValueError("Termenul de reverificare trebuie să fie în viitor")
    if retrieved_at > now:
        raise ValueError("Data preluării dovezii nu poate fi în viitor")
    if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValueError("Hashul conținutului sursă nu este SHA-256 valid")
    if not source_title.strip() or not identity_reference.strip() or not evidence_summary.strip():
        raise ValueError("Identitatea, titlul și rezumatul dovezii sunt obligatorii")
    URLValidator(schemes=("https",))(source_url)
    authorized_records = business.snapshot_records.filter(
        import_run__scope_contract_version=1,
        import_run__state=ImportRun.State.SUCCEEDED,
        status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
        categories__category=category,
    )
    if not authorized_records.exists():
        raise ValueError("Firma nu are o autorizare ONRC reconciliată pentru categorie")
    known_identifiers = {business.registration_number.casefold()} | {
        cui.casefold()
        for cui in authorized_records.exclude(cui="").values_list("cui", flat=True)
    }
    normalized_reference = identity_reference.casefold()
    if not any(identifier in normalized_reference for identifier in known_identifiers):
        raise ValueError("Sursa directă nu identifică neechivoc firma ONRC")
    BusinessIdentity.objects.select_for_update().get(pk=business.pk)
    latest_version = (
        VerifiedServiceEvidence.objects.filter(business=business, category=category)
        .order_by("-evidence_version")
        .values_list("evidence_version", flat=True)
        .first()
        or 0
    )
    VerifiedServiceEvidence.objects.filter(
        business=business,
        category=category,
        state=VerifiedServiceEvidence.State.ACTIVE,
    ).update(
        state=VerifiedServiceEvidence.State.SUPERSEDED,
        superseded_at=now,
    )
    evidence = VerifiedServiceEvidence.objects.create(
        business=business,
        category=category,
        evidence_version=latest_version + 1,
        source_url=source_url,
        source_title=source_title.strip(),
        identity_reference=identity_reference.strip(),
        evidence_summary=evidence_summary.strip(),
        retrieved_at=retrieved_at,
        content_sha256=content_sha256,
        approved_by=actor,
        approved_at=now,
        expires_at=expires_at,
    )
    VerifiedServiceCoverage.objects.bulk_create(
        [VerifiedServiceCoverage(evidence=evidence, county=county) for county in counties]
    )
    return evidence


@transaction.atomic
def revoke_verified_service_evidence(
    *, evidence: VerifiedServiceEvidence, actor_username: str
) -> tuple[VerifiedServiceEvidence, bool]:
    """Revoke one evidence version so readers stop using it immediately."""

    actor = get_user_model().objects.get(username=actor_username, is_active=True)
    if not actor.has_perm("services.verify_service_evidence"):
        raise ValueError("Operatorul nu are permisiunea de revocare a dovezii")
    evidence = VerifiedServiceEvidence.objects.select_for_update().get(pk=evidence.pk)
    if evidence.state == VerifiedServiceEvidence.State.REVOKED:
        return evidence, False
    if evidence.state != VerifiedServiceEvidence.State.ACTIVE:
        raise ValueError("Numai dovada activă poate fi revocată")
    evidence.state = VerifiedServiceEvidence.State.REVOKED
    evidence.revoked_at = timezone.now()
    evidence.revoked_by = actor
    evidence.save(update_fields=("state", "revoked_at", "revoked_by"))
    return evidence, True
