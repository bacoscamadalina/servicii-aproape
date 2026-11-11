"""Transactional private declarations of provider services and service areas."""

from dataclasses import dataclass
import hashlib
import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .catalog import CATEGORIES
from .locations import (
    SIRUTA_CATALOGUE_VERSION,
    county_choices,
    locality_name,
    siruta_catalogue_sha256,
)
from .models import (
    BusinessCaen,
    BusinessCategory,
    CatalogueScope,
    ImportRun,
    ProviderDraftCoverage,
    ProviderDraftService,
    ProviderDevelopmentDemoGrant,
    ProviderMembership,
    ProviderProfile,
    ProviderRegistrationRequest,
    ProviderServiceAreaDraft,
    ProviderServiceAreaSubmission,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)


@dataclass(frozen=True)
class ProviderAuthorization:
    """Current legal ceiling for one provider's private service declaration."""

    run: ImportRun
    catalogue_run: ImportRun
    categories: frozenset[str]
    is_demo: bool = False


class ProviderDraftRevisionConflict(ValueError):
    """Signal an optimistic-lock conflict independently of translated copy."""


REVIEW_POLICY_VERSION = "2026-08-25-v1"
REVIEW_ACKNOWLEDGEMENT = "SERVICE_AREA_REVIEW_SEPARATE_FROM_PUBLICATION"
SUBMISSION_SCHEMA_VERSION = 1


def may_prepare_unverified_offering_draft(profile: ProviderProfile) -> bool:
    """Allow pre-reconciliation editing only for the audited unlisted-company flow."""

    return ProviderRegistrationRequest.objects.filter(
        status=ProviderRegistrationRequest.Status.CONVERTED,
        linked_business_id=profile.business_id,
        converted_claim_id=profile.approved_claim_id,
    ).exists()


def provider_authorization(
    profile: ProviderProfile, *, lock_scope: bool = False
) -> ProviderAuthorization:
    """Resolve one coherent ONRC run or an explicit development-only demo grant."""

    scopes_query = (
        CatalogueScope.objects.select_related(
            "current_run__snapshot",
            "current_run__refined_from_run__snapshot",
        )
        .filter(
            provider="ONRC",
            current_run__isnull=False,
            current_run__state=ImportRun.State.SUCCEEDED,
            current_run__claim_token__isnull=True,
            current_run__snapshot__state=SourceSnapshot.State.VERIFIED,
            current_run__refined_from_run__isnull=False,
            current_run__refined_from_run__state=ImportRun.State.SUCCEEDED,
            current_run__refined_from_run__claim_token__isnull=True,
            current_run__refined_from_run__snapshot__state=SourceSnapshot.State.VERIFIED,
            current_run__refined_from_run__business_snapshots__business=profile.business,
        )
    )
    if lock_scope:
        scopes_query = scopes_query.select_for_update(of=("self",))
    scopes = list(scopes_query)
    is_demo = False
    if len(scopes) == 1:
        scope = scopes[0]
        current_run = scope.current_run
        authorization_run = current_run.refined_from_run
        if current_run.county != scope.county or authorization_run.county != scope.county:
            raise ValueError(_("Sursa ONRC activă are un județ inconsistent."))
    elif not scopes:
        grant_query = ProviderDevelopmentDemoGrant.objects.select_related(
            "authorization_run__snapshot", "catalogue_run__snapshot"
        ).filter(profile=profile, enabled=True)
        if lock_scope:
            grant_query = grant_query.select_for_update()
        grant = (
            grant_query.first()
            if settings.PROVIDER_DEVELOPMENT_DEMO_ENABLED
            else None
        )
        if grant is None:
            raise ValueError(
                _("Autorizările ONRC ale firmei nu pot fi determinate în siguranță.")
            )
        scope_query = CatalogueScope.objects.filter(
            provider="ONRC",
            county=grant.catalogue_run.county,
            current_run=grant.catalogue_run,
            current_run__state=ImportRun.State.SUCCEEDED,
            current_run__snapshot__state=SourceSnapshot.State.VERIFIED,
        )
        if lock_scope:
            scope_query = scope_query.select_for_update(of=("self",))
        if not scope_query.exists():
            raise ValueError(_("Catalogul asociat demonstrației nu mai este curent."))
        authorization_run = grant.authorization_run
        current_run = grant.catalogue_run
        is_demo = True
        if (
            authorization_run.snapshot.provider != "SERVICIIAPROAPE_DEMO"
            or authorization_run.scope_contract_version != 1
            or authorization_run.state != ImportRun.State.SUCCEEDED
            or authorization_run.claim_token is not None
            or authorization_run.snapshot.state != SourceSnapshot.State.VERIFIED
            or authorization_run.county != current_run.county
        ):
            raise ValueError(_("Autorizarea demonstrativă nu mai este validă."))
    else:
        raise ValueError(
            _("Autorizările ONRC ale firmei nu pot fi determinate în siguranță.")
        )
    try:
        business_snapshot = RegisteredBusinessSnapshot.objects.staging_candidates(
            authorization_run
        ).get(business=profile.business)
    except (
        RegisteredBusinessSnapshot.DoesNotExist,
        RegisteredBusinessSnapshot.MultipleObjectsReturned,
    ) as error:
        raise ValueError(
            _("Firma nu are o înregistrare ONRC coerentă în sursa activă.")
        ) from error
    categories = set(
        BusinessCategory.objects.filter(business_snapshot=business_snapshot).values_list(
            "category", flat=True
        )
    )
    if BusinessCaen.objects.filter(
        business_snapshot=business_snapshot, version="2", code="4321"
    ).exists():
        categories.add("electricieni")
    categories = frozenset(categories)
    known_categories = {slug for slug, _label, _description in CATEGORIES}
    if not categories or not categories.issubset(known_categories):
        raise ValueError(_("Categoriile ONRC ale firmei nu pot fi validate."))
    return ProviderAuthorization(
        run=authorization_run,
        catalogue_run=current_run,
        categories=categories,
        is_demo=is_demo,
    )


def _lock_active_owner_profile(user) -> ProviderProfile:
    """Lock and return the only private profile actively owned by ``user``."""

    if not user.is_active:
        raise PermissionError(_("Contul furnizorului nu este activ."))
    memberships = list(
        ProviderMembership.objects.select_for_update()
        .filter(
            user=user,
            state=ProviderMembership.State.ACTIVE,
            profile__state=ProviderProfile.State.DRAFT,
        )[:2]
    )
    if len(memberships) != 1:
        raise PermissionError(_("Accesul la profil nu mai este activ."))
    return ProviderProfile.objects.select_for_update().select_related("business").get(
        pk=memberships[0].profile_id
    )


def _normalized_draft_content(
    draft: ProviderServiceAreaDraft,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Read a deterministic service and coverage snapshot from normalized children."""

    return (
        tuple(sorted(draft.services.values_list("category", flat=True))),
        tuple(sorted(draft.coverage.values_list("county", "siruta_code"))),
    )


def _contract_sha256(
    *,
    profile: ProviderProfile,
    revision: int,
    services,
    coverage,
    authorization_run_id: int,
    catalogue_run_id: int,
    siruta_version: str,
    siruta_sha256: str,
) -> str:
    """Hash every semantic input of one immutable moderation snapshot."""

    payload = {
        "schema_version": SUBMISSION_SCHEMA_VERSION,
        "profile_id": profile.pk,
        "business_id": profile.business_id,
        "revision": revision,
        "services": list(services),
        "coverage": [list(pair) for pair in coverage],
        "authorization_run_id": authorization_run_id,
        "catalogue_run_id": catalogue_run_id,
        "siruta_catalogue_version": siruta_version,
        "siruta_catalogue_sha256": siruta_sha256,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _validate_content(
    *,
    services,
    coverage,
    authorization: ProviderAuthorization | None,
) -> None:
    """Validate a private draft and, when available, its ONRC authorization ceiling."""

    known_categories = {slug for slug, _label, _description in CATEGORIES}
    if not services or len(services) > len(known_categories):
        raise ValueError(_("Alege cel puțin un serviciu autorizat."))
    if not set(services).issubset(known_categories):
        raise ValueError(_("Lista serviciilor conține o categorie necunoscută."))
    if authorization is not None and not set(services).issubset(
        authorization.categories
    ):
        raise ValueError(
            _("Poți declara numai servicii care apar în activitățile autorizate ONRC.")
        )
    if not coverage or len(coverage) > 100:
        raise ValueError(_("Alege între 1 și 100 de localități deservite."))
    known_counties = {county for county, _label in county_choices()}
    if any(
        county not in known_counties or not locality_name(county, siruta_code)
        for county, siruta_code in coverage
    ):
        raise ValueError(_("Lista conține o localitate SIRUTA invalidă pentru județul ales."))


@transaction.atomic
def replace_provider_services_and_coverage_for_owner(
    *,
    user,
    expected_revision: int,
    categories,
    coverage_pairs,
) -> tuple[ProviderServiceAreaDraft, bool]:
    """Atomically replace one owner's private declaration using optimistic revisioning."""

    profile = _lock_active_owner_profile(user)
    try:
        authorization = provider_authorization(profile, lock_scope=True)
    except ValueError:
        # A missing-company profile may prepare a private draft before legal-service
        # reconciliation. Submission still resolves and requires current authorization.
        if not may_prepare_unverified_offering_draft(profile):
            raise
        authorization = None

    normalized_categories = frozenset(str(value).strip() for value in categories)
    normalized_coverage = frozenset(
        (str(county).strip(), str(siruta_code).strip())
        for county, siruta_code in coverage_pairs
    )
    _validate_content(
        services=normalized_categories,
        coverage=normalized_coverage,
        authorization=authorization,
    )

    draft, _created = ProviderServiceAreaDraft.objects.select_for_update().get_or_create(
        profile=profile
    )
    if draft.revision != expected_revision:
        raise ProviderDraftRevisionConflict(
            _("Ciorna a fost modificată într-o altă sesiune. Reîncarcă pagina.")
        )
    current_categories = frozenset(
        draft.services.values_list("category", flat=True)
    )
    current_coverage = frozenset(
        draft.coverage.values_list("county", "siruta_code")
    )
    catalogue_hash = siruta_catalogue_sha256()
    if (
        current_categories == normalized_categories
        and current_coverage == normalized_coverage
        and draft.authorization_run_id
        == (authorization.run.pk if authorization is not None else None)
        and draft.siruta_catalogue_version == SIRUTA_CATALOGUE_VERSION
        and draft.siruta_catalogue_sha256 == catalogue_hash
    ):
        return draft, False

    next_revision = draft.revision + 1
    current_submission = (
        ProviderServiceAreaSubmission.objects.select_for_update()
        .filter(draft=draft, superseded_at__isnull=True)
        .first()
    )
    if current_submission:
        current_submission.superseded_at = timezone.now()
        current_submission.superseded_by = user
        current_submission.superseded_by_revision = next_revision
        current_submission.save(
            update_fields=(
                "superseded_at",
                "superseded_by",
                "superseded_by_revision",
            )
        )

    # A published snapshot may only claim the exact approved service revision.
    # Reducing visibility is part of the same transaction as the provider edit.
    from .provider_publication import _unpublish_locked

    _unpublish_locked(
        profile=profile,
        actor=user,
        note="Serviciile sau acoperirea declarată au fost modificate.",
        superseding_version=next_revision,
    )

    draft.services.all().delete()
    draft.coverage.all().delete()
    ProviderDraftService.objects.bulk_create(
        ProviderDraftService(draft=draft, category=category)
        for category in sorted(normalized_categories)
    )
    ProviderDraftCoverage.objects.bulk_create(
        ProviderDraftCoverage(draft=draft, county=county, siruta_code=siruta_code)
        for county, siruta_code in sorted(normalized_coverage)
    )
    draft.revision = next_revision
    draft.review_state = ProviderServiceAreaDraft.ReviewState.DRAFT
    draft.reviewed_revision = None
    draft.authorization_run = authorization.run if authorization is not None else None
    draft.siruta_catalogue_version = SIRUTA_CATALOGUE_VERSION
    draft.siruta_catalogue_sha256 = catalogue_hash
    draft.updated_by = user
    draft.save(
        update_fields=(
            "revision",
            "review_state",
            "reviewed_revision",
            "authorization_run",
            "siruta_catalogue_version",
            "siruta_catalogue_sha256",
            "updated_by",
            "updated_at",
        )
    )
    return draft, True


@transaction.atomic
def submit_provider_service_area_for_review(
    *, user, expected_revision: int
) -> tuple[ProviderServiceAreaSubmission, bool]:
    """Snapshot and submit the owner's current exact revision for private review."""

    profile = _lock_active_owner_profile(user)
    authorization = provider_authorization(profile, lock_scope=True)
    try:
        draft = ProviderServiceAreaDraft.objects.select_for_update().get(profile=profile)
    except ProviderServiceAreaDraft.DoesNotExist as error:
        raise ValueError(_("Salvează mai întâi serviciile și localitățile.")) from error
    if draft.revision != expected_revision:
        raise ProviderDraftRevisionConflict(
            _("Ciorna a fost modificată într-o altă sesiune. Reîncarcă pagina.")
        )
    if draft.revision == 0:
        raise ValueError(_("Revizia goală nu poate fi trimisă la verificare."))
    services, coverage = _normalized_draft_content(draft)
    _validate_content(
        services=services,
        coverage=coverage,
        authorization=authorization,
    )
    current_siruta_hash = siruta_catalogue_sha256()
    if (
        draft.authorization_run_id != authorization.run.pk
        or draft.siruta_catalogue_version != SIRUTA_CATALOGUE_VERSION
        or draft.siruta_catalogue_sha256 != current_siruta_hash
    ):
        raise ValueError(
            _("Datele ONRC sau SIRUTA s-au actualizat. Salvează din nou declarația.")
        )
    contract_hash = _contract_sha256(
        profile=profile,
        revision=draft.revision,
        services=services,
        coverage=coverage,
        authorization_run_id=authorization.run.pk,
        catalogue_run_id=authorization.catalogue_run.pk,
        siruta_version=SIRUTA_CATALOGUE_VERSION,
        siruta_sha256=current_siruta_hash,
    )
    current_submission = (
        ProviderServiceAreaSubmission.objects.select_for_update()
        .filter(draft=draft, superseded_at__isnull=True)
        .first()
    )
    if current_submission:
        if (
            current_submission.revision == draft.revision
            and current_submission.decision
            == ProviderServiceAreaSubmission.Decision.PENDING
            and current_submission.contract_sha256 == contract_hash
        ):
            return current_submission, False
        raise ValueError(
            _("Revizia curentă a fost deja decisă. Modifică declarația înainte de retrimitere.")
        )
    submission = ProviderServiceAreaSubmission.objects.create(
        draft=draft,
        revision=draft.revision,
        snapshot_schema_version=SUBMISSION_SCHEMA_VERSION,
        services_snapshot=list(services),
        coverage_snapshot=[list(pair) for pair in coverage],
        contract_sha256=contract_hash,
        authorization_run=authorization.run,
        catalogue_run=authorization.catalogue_run,
        siruta_catalogue_version=SIRUTA_CATALOGUE_VERSION,
        siruta_catalogue_sha256=current_siruta_hash,
        submitted_by=user,
    )
    draft.review_state = ProviderServiceAreaDraft.ReviewState.PENDING
    draft.reviewed_revision = draft.revision
    draft.save(update_fields=("review_state", "reviewed_revision", "updated_at"))
    return submission, True


def _require_service_area_reviewer(reviewer) -> None:
    """Fail closed unless the actor has the dedicated staff review permission."""

    if not reviewer.is_active or not reviewer.is_staff or not reviewer.has_perm(
        "services.review_provider_service_area"
    ):
        raise PermissionError("Nu ai permisiunea de a decide această declarație.")


@transaction.atomic
def review_provider_service_area_submission(
    *,
    submission_id: int,
    reviewer,
    decision: str,
    internal_note: str,
    provider_feedback: str,
    acknowledgement: str,
) -> tuple[ProviderServiceAreaSubmission, bool]:
    """Record one audited private decision for the exact submitted revision."""

    _require_service_area_reviewer(reviewer)
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea limitelor verificării lipsește.")
    if decision not in (
        ProviderServiceAreaSubmission.Decision.APPROVED,
        ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
    ):
        raise ValueError("Decizia de verificare nu este validă.")
    note = " ".join(internal_note.split())
    feedback = " ".join(provider_feedback.split())
    if len(note) < 8:
        raise ValueError("Nota internă trebuie să documenteze decizia.")
    if len(note) > 1200 or len(feedback) > 700:
        raise ValueError("Textul deciziei depășește limita permisă.")
    if (
        decision == ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED
        and len(feedback) < 8
    ):
        raise ValueError("Explică furnizorului ce trebuie modificat.")

    reference = ProviderServiceAreaSubmission.objects.select_related(
        "draft__profile", "catalogue_run"
    ).get(pk=submission_id)
    profile = ProviderProfile.objects.select_for_update().select_related("business").get(
        pk=reference.draft.profile_id
    )
    scope = CatalogueScope.objects.select_for_update().get(
        provider="ONRC", county=reference.catalogue_run.county
    )
    draft = ProviderServiceAreaDraft.objects.select_for_update().get(
        pk=reference.draft_id
    )
    submission = ProviderServiceAreaSubmission.objects.select_for_update().get(
        pk=submission_id
    )

    if reviewer.pk == submission.submitted_by_id or ProviderMembership.objects.filter(
        profile=profile,
        user=reviewer,
    ).exclude(state=ProviderMembership.State.REVOKED).exists():
        raise ValueError("Evaluatorul nu își poate decide propria declarație.")
    if profile.state != ProviderProfile.State.DRAFT or not ProviderMembership.objects.filter(
        profile=profile,
        state=ProviderMembership.State.ACTIVE,
        user__is_active=True,
    ).exists():
        raise ValueError("Profilul furnizorului nu mai are un proprietar activ.")
    if submission.superseded_at is not None:
        raise ValueError("Depunerea a fost înlocuită de o revizie mai nouă.")
    if submission.decision != ProviderServiceAreaSubmission.Decision.PENDING:
        if (
            submission.decision == decision
            and submission.reviewed_by_id == reviewer.pk
            and submission.internal_review_note == note
            and submission.provider_feedback == feedback
            and submission.review_acknowledgement == acknowledgement
        ):
            return submission, False
        raise ValueError("Depunerea are deja o decizie diferită sau finală.")
    if (
        draft.revision != submission.revision
        or draft.review_state != ProviderServiceAreaDraft.ReviewState.PENDING
        or draft.reviewed_revision != submission.revision
    ):
        raise ValueError("Ciorna nu mai corespunde reviziei trimise.")

    services, coverage = _normalized_draft_content(draft)
    if list(services) != submission.services_snapshot or [
        list(pair) for pair in coverage
    ] != submission.coverage_snapshot:
        raise ValueError("Conținutul reviziei trimise nu mai este intact.")
    expected_hash = _contract_sha256(
        profile=profile,
        revision=submission.revision,
        services=services,
        coverage=coverage,
        authorization_run_id=submission.authorization_run_id,
        catalogue_run_id=submission.catalogue_run_id,
        siruta_version=submission.siruta_catalogue_version,
        siruta_sha256=submission.siruta_catalogue_sha256,
    )
    if expected_hash != submission.contract_sha256:
        raise ValueError("Contractul criptografic al depunerii nu mai este valid.")

    if decision == ProviderServiceAreaSubmission.Decision.APPROVED:
        if scope.current_run_id != submission.catalogue_run_id:
            raise ValueError(
                "Catalogul ONRC s-a actualizat. Furnizorul trebuie să salveze din nou."
            )
        authorization = provider_authorization(profile)
        if (
            authorization.run.pk != submission.authorization_run_id
            or authorization.catalogue_run.pk != submission.catalogue_run_id
            or submission.siruta_catalogue_version != SIRUTA_CATALOGUE_VERSION
            or submission.siruta_catalogue_sha256 != siruta_catalogue_sha256()
        ):
            raise ValueError("Sursele ONRC sau SIRUTA ale depunerii nu mai sunt curente.")
        _validate_content(
            services=services,
            coverage=coverage,
            authorization=authorization,
        )

    instant = timezone.now()
    submission.decision = decision
    submission.reviewed_by = reviewer
    submission.reviewed_at = instant
    submission.review_policy_version = REVIEW_POLICY_VERSION
    submission.review_acknowledgement = acknowledgement
    submission.internal_review_note = note
    submission.provider_feedback = feedback
    submission.save(
        update_fields=(
            "decision",
            "reviewed_by",
            "reviewed_at",
            "review_policy_version",
            "review_acknowledgement",
            "internal_review_note",
            "provider_feedback",
        )
    )
    draft.review_state = (
        ProviderServiceAreaDraft.ReviewState.APPROVED
        if decision == ProviderServiceAreaSubmission.Decision.APPROVED
        else ProviderServiceAreaDraft.ReviewState.CHANGES_REQUIRED
    )
    draft.reviewed_revision = submission.revision
    draft.save(update_fields=("review_state", "reviewed_revision", "updated_at"))
    return submission, True
