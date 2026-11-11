"""Audited catalogue activation and fail-closed reader contracts."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .locations import locality_choices
from .models import (
    BusinessCaen,
    BusinessCategory,
    BusinessStatus,
    CatalogueActivationEvent,
    CatalogueScope,
    ImportRun,
    PublicationApproval,
    PrimaryActivityEvidence,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from .caen import category_for_caen
from .importers.onrc import _sha256
from .importers.primary_activity import (
    CAEN_VERSION as EVIDENCE_CAEN_VERSION,
    MF_MANIFEST_PATH,
    POLICY_HASH as EVIDENCE_POLICY_HASH,
    POLICY_VERSION as EVIDENCE_POLICY_VERSION,
    REPORTING_YEAR as EVIDENCE_REPORTING_YEAR,
    normalize_cui,
)
from .staging import pilot_scope_key, refined_scope_key


ACKNOWLEDGEMENT = "REGISTERED_OFFICE_NOT_SERVICE_COVERAGE"
PUBLICATION_REVIEW_ACKNOWLEDGEMENT = "LEGAL_PRIVACY_PUBLICATION_REVIEW_COMPLETED"


@dataclass(frozen=True)
class CatalogueState:
    """A public-reader decision that never silently falls back on stale data."""

    status: str
    scope: CatalogueScope | None = None
    run: ImportRun | None = None
    preview: bool = False


def publication_approval_is_valid(
    approval: PublicationApproval | None, now: datetime | None = None
) -> bool:
    """Return whether an approval is currently usable without mutating it."""

    instant = now or timezone.now()
    return bool(
        approval
        and approval.state == PublicationApproval.State.APPROVED
        and approval.revoked_at is None
        and (approval.review_due_at is None or approval.review_due_at > instant)
    )


@transaction.atomic
def record_publication_approval(
    *,
    run: ImportRun,
    actor_username: str,
    review_reference: str,
    review_due_at: datetime,
    acknowledgement: str,
) -> PublicationApproval:
    """Record a new immutable approval version after a real external review."""

    actor = get_user_model().objects.get(username=actor_username, is_active=True)
    if not actor.has_perm("services.approve_catalogue_publication"):
        raise ValueError("Operatorul nu are permisiunea de aprobare a publicării")
    if acknowledgement != PUBLICATION_REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea reviziei juridice și de confidențialitate lipsește")
    if not review_reference.strip():
        raise ValueError("Referința reviziei de publicare este obligatorie")
    if review_due_at <= timezone.now():
        raise ValueError("Termenul de revizuire trebuie să fie în viitor")
    audit_run_for_catalogue(run)
    latest_version = (
        PublicationApproval.objects.filter(import_run=run)
        .order_by("-approval_version")
        .values_list("approval_version", flat=True)
        .first()
        or 0
    )
    return PublicationApproval.objects.create(
        import_run=run,
        approval_version=latest_version + 1,
        approved_by=actor,
        approved_at=timezone.now(),
        review_reference=review_reference.strip(),
        review_due_at=review_due_at,
    )


@transaction.atomic
def revoke_publication_approval(
    *, approval: PublicationApproval, actor_username: str
) -> tuple[PublicationApproval, bool]:
    """Revoke one approval version; active readers fail closed immediately."""

    actor = get_user_model().objects.get(username=actor_username, is_active=True)
    if not actor.has_perm("services.approve_catalogue_publication"):
        raise ValueError("Operatorul nu are permisiunea de revocare a publicării")
    approval = PublicationApproval.objects.select_for_update().get(pk=approval.pk)
    if approval.state == PublicationApproval.State.REVOKED:
        return approval, False
    approval.state = PublicationApproval.State.REVOKED
    approval.revoked_at = timezone.now()
    approval.revoked_by = actor
    approval.save(update_fields=("state", "revoked_at", "revoked_by"))
    return approval, True


def audit_run_for_catalogue(run: ImportRun) -> dict[str, int]:
    """Prove every cross-table invariant required before pointer activation."""

    run = ImportRun.objects.select_related(
        "snapshot", "refined_from_run", "activity_evidence_snapshot"
    ).get(pk=run.pk)
    if run.scope_contract_version == 1:
        expected_scope_key, canonical_categories = pilot_scope_key(
            run.county, run.categories
        )
    elif (
        run.scope_contract_version == 2
        and run.refined_from_run_id
        and run.activity_evidence_snapshot_id
    ):
        if (
            run.activity_evidence_policy_version != EVIDENCE_POLICY_VERSION
            or run.activity_evidence_policy_hash != EVIDENCE_POLICY_HASH
            or run.activity_evidence_year != EVIDENCE_REPORTING_YEAR
            or run.activity_evidence_snapshot.provider
            != "MF_FINANCIAL_STATEMENTS_2024"
            or run.activity_evidence_snapshot.state != SourceSnapshot.State.VERIFIED
            or run.activity_evidence_snapshot.manifest_sha256
            != _sha256(MF_MANIFEST_PATH)
        ):
            raise ValueError("Politica sau snapshotul MF nu corespunde contractului aprobat")
        expected_scope_key, canonical_categories = refined_scope_key(
            run.refined_from_run,
            run.activity_evidence_snapshot,
            policy_version=run.activity_evidence_policy_version,
            policy_hash=run.activity_evidence_policy_hash,
            evidence_year=run.activity_evidence_year,
        )
    else:
        raise ValueError("Versiunea contractului scope nu este validă")
    if run.state != ImportRun.State.SUCCEEDED or run.claim_token is not None:
        raise ValueError("Runul nu este finalizat stabil")
    if run.snapshot.state != SourceSnapshot.State.VERIFIED:
        raise ValueError("Snapshotul runului nu mai este verificat")
    if run.scope_key != expected_scope_key or run.categories != canonical_categories:
        raise ValueError("Proveniența scope-ului nu mai corespunde politicilor curente")

    candidates = RegisteredBusinessSnapshot.objects.staging_candidates(run)
    staged = candidates.count()
    if staged != run.counters.get("staged_businesses") or staged == 0:
        raise ValueError("Numărul candidaților nu corespunde importului finalizat")

    status_rows = BusinessStatus.objects.filter(business_snapshot__import_run=run)
    if status_rows.count() != staged or status_rows.exclude(code="1048").exists():
        raise ValueError("Fiecare candidat trebuie să aibă exact statusul 1048")
    if candidates.annotate(total=Count("caen_codes")).filter(total=0).exists():
        raise ValueError("Există un candidat fără activitate CAEN")
    if candidates.annotate(total=Count("categories")).filter(total=0).exists():
        raise ValueError("Există un candidat fără categorie publică")

    caen_rows = BusinessCaen.objects.filter(business_snapshot__import_run=run).count()
    category_rows = BusinessCategory.objects.filter(
        business_snapshot__import_run=run
    )
    if caen_rows != run.counters.get("staged_caen"):
        raise ValueError("Numărul relațiilor CAEN nu se reconciliază")
    if category_rows.count() != run.counters.get("staged_categories"):
        raise ValueError("Numărul relațiilor de categorie nu se reconciliază")
    if category_rows.exclude(category__in=run.categories).exists():
        raise ValueError("Runul conține categorii în afara scope-ului")
    if run.scope_contract_version == 2:
        evidence = PrimaryActivityEvidence.objects.filter(
            business_snapshot__import_run=run
        )
        if evidence.count() != staged:
            raise ValueError("Fiecare candidat rafinat trebuie să aibă o dovadă MF")
        if evidence.exclude(
            reporting_year=run.activity_evidence_year,
            caen_version=EVIDENCE_CAEN_VERSION,
        ).exists():
            raise ValueError("Dovada MF nu corespunde anului și versiunii CAEN")
        if candidates.annotate(total=Count("categories")).exclude(total=1).exists():
            raise ValueError("Activitatea preponderentă trebuie să derive o categorie")
        permitted_resources = {"data_bl_bs_sl", "data_uu"}
        pinned_resources = run.activity_evidence_snapshot.verified_resources
        if not permitted_resources.issubset(pinned_resources):
            raise ValueError("Resursele de date MF nu sunt fixate în snapshot")
        authorized: dict[int, set[tuple[str, str]]] = {}
        for snapshot_id, version, code in BusinessCaen.objects.filter(
            business_snapshot__import_run=run
        ).values_list("business_snapshot_id", "version", "code").iterator(
            chunk_size=10_000
        ):
            authorized.setdefault(snapshot_id, set()).add((version, code))
        for (
            snapshot_id, cui, resource, code, category, join_fingerprint,
            source_fingerprint,
        ) in evidence.values_list(
            "business_snapshot_id", "business_snapshot__cui", "resource_kind",
            "caen_code", "business_snapshot__categories__category",
            "cui_join_fingerprint", "source_row_fingerprint",
        ).iterator(chunk_size=5_000):
            normalized_cui = normalize_cui(cui)
            expected_join = hashlib.sha256(normalized_cui.encode()).hexdigest()
            expected_source = hashlib.sha256(
                f"{resource}\0{normalized_cui}\0{code}".encode()
            ).hexdigest()
            if (
                resource not in permitted_resources
                or resource not in pinned_resources
                or join_fingerprint != expected_join
                or source_fingerprint != expected_source
            ):
                raise ValueError("Fingerprintul sau resursa dovezii MF este invalidă")
            if category_for_caen(code, EVIDENCE_CAEN_VERSION) != category:
                raise ValueError("Categoria nu corespunde activității MF raportate")
            activities = authorized.get(snapshot_id, set())
            if not (
                (EVIDENCE_CAEN_VERSION, code) in activities
                or any(
                    category_for_caen(activity_code, version) == category
                    for version, activity_code in activities
                )
            ):
                raise ValueError("Activitatea MF nu este reconciliată cu autorizarea ONRC")
    valid_siruta = {code for code, _label in locality_choices(run.county)}
    if candidates.exclude(registered_office_siruta__in=valid_siruta).exists():
        raise ValueError("Runul conține un cod SIRUTA din alt județ")
    if candidates.exclude(locality_match__in=("exact", "hierarchy_alias")).exists():
        raise ValueError("Runul conține o reconciliere de localitate neaprobată")
    quarantine = run.quarantine_records.count()
    if quarantine != run.counters.get("quarantine_records"):
        raise ValueError("Carantina nu se reconciliază cu raportul importului")

    return {
        "staged_businesses": staged,
        "staged_statuses": status_rows.count(),
        "staged_caen": caen_rows,
        "staged_categories": category_rows.count(),
        "quarantine_records": quarantine,
    }


@transaction.atomic
def activate_catalogue_scope(
    *,
    run: ImportRun,
    visibility: str,
    actor_username: str,
    expected_scope_key: str,
    acknowledgement: str,
) -> tuple[CatalogueScope, bool]:
    """Audit and atomically swap one stable county pointer."""

    if acknowledgement != ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea limitelor sediului social lipsește")
    if run.scope_key != expected_scope_key:
        raise ValueError("Scope key nu corespunde runului cerut")
    if visibility not in (
        CatalogueScope.Visibility.INTERNAL_PREVIEW,
        CatalogueScope.Visibility.PUBLIC,
    ):
        raise ValueError("Vizibilitate de catalog necunoscută")
    actor = get_user_model().objects.get(username=actor_username, is_staff=True)
    audited = audit_run_for_catalogue(run)

    approval = None
    if visibility == CatalogueScope.Visibility.PUBLIC:
        approval = PublicationApproval.objects.filter(import_run=run).order_by(
            "-approval_version"
        ).first()
        if not publication_approval_is_valid(approval):
            raise ValueError("Runul nu are o aprobare de publicare validă")

    CatalogueScope.objects.get_or_create(provider="ONRC", county=run.county)
    scope = CatalogueScope.objects.select_for_update().get(
        provider="ONRC", county=run.county
    )
    expected_approval_id = approval.pk if approval is not None else None
    if (
        scope.current_run_id == run.pk
        and scope.current_approval_id == expected_approval_id
        and scope.visibility == visibility
    ):
        return scope, False

    previous_run = scope.current_run
    previous_visibility = scope.visibility
    scope.current_run = run
    scope.current_approval = approval
    scope.visibility = visibility
    scope.activated_at = timezone.now()
    scope.save(
        update_fields=(
            "current_run",
            "current_approval",
            "visibility",
            "activated_at",
        )
    )
    CatalogueActivationEvent.objects.create(
        scope=scope,
        action=CatalogueActivationEvent.Action.ACTIVATE,
        previous_run=previous_run,
        new_run=run,
        approval=approval,
        actor=actor,
        previous_visibility=previous_visibility,
        new_visibility=visibility,
        acknowledgement=acknowledgement,
        audited_counters=audited,
    )
    return scope, True


@transaction.atomic
def activate_catalogue_scopes_for_preview(
    *,
    plans: list[dict[str, object]],
    actor_username: str,
    acknowledgement: str,
) -> list[CatalogueScope]:
    """Atomically swap several county preview pointers with predecessor CAS checks."""

    if acknowledgement != ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea limitelor sediului social lipsește")
    if not plans:
        raise ValueError("Planul de activare este gol")
    actor = get_user_model().objects.get(username=actor_username, is_staff=True)
    run_ids = [int(plan["run_id"]) for plan in plans]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("Planul de activare conține runuri duplicate")
    runs = {
        run.pk: run
        for run in ImportRun.objects.select_for_update()
        .select_related("snapshot")
        .filter(pk__in=run_ids)
        .order_by("pk")
    }
    if len(runs) != len(run_ids):
        raise ValueError("Planul de activare conține un run inexistent")
    counties = [runs[run_id].county for run_id in run_ids]
    if len(counties) != len(set(counties)):
        raise ValueError("Planul conține mai multe runuri pentru același județ")

    for county in counties:
        CatalogueScope.objects.get_or_create(provider="ONRC", county=county)
    scopes = {
        scope.county: scope
        for scope in CatalogueScope.objects.select_for_update()
        .filter(provider="ONRC", county__in=counties)
        .order_by("county")
    }
    audited: dict[int, dict[str, int]] = {}
    for plan in plans:
        run = runs[int(plan["run_id"])]
        if plan.get("expected_scope_key") != run.scope_key:
            raise ValueError(f"Scope key invalid pentru {run.county}")
        scope = scopes[run.county]
        expected_previous = plan.get("expected_previous_run_id")
        if scope.current_run_id != expected_previous:
            raise ValueError(f"Pointer predecessor schimbat pentru {run.county}")
        audited[run.pk] = audit_run_for_catalogue(run)

    instant = timezone.now()
    changed_scopes: list[CatalogueScope] = []
    for plan in plans:
        run = runs[int(plan["run_id"])]
        scope = scopes[run.county]
        if (
            scope.current_run_id == run.pk
            and scope.visibility == CatalogueScope.Visibility.INTERNAL_PREVIEW
            and scope.current_approval_id is None
        ):
            continue
        previous_run = scope.current_run
        previous_visibility = scope.visibility
        scope.current_run = run
        scope.current_approval = None
        scope.visibility = CatalogueScope.Visibility.INTERNAL_PREVIEW
        scope.activated_at = instant
        scope.save(
            update_fields=(
                "current_run",
                "current_approval",
                "visibility",
                "activated_at",
            )
        )
        CatalogueActivationEvent.objects.create(
            scope=scope,
            action=CatalogueActivationEvent.Action.ACTIVATE,
            previous_run=previous_run,
            new_run=run,
            actor=actor,
            previous_visibility=previous_visibility,
            new_visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
            acknowledgement=acknowledgement,
            audited_counters=audited[run.pk],
        )
        changed_scopes.append(scope)
    return changed_scopes


@transaction.atomic
def deactivate_catalogue_scope(
    *, county: str, actor_username: str, acknowledgement: str
) -> tuple[CatalogueScope, bool]:
    """Atomically disable a county pointer and retain an append-only event."""

    if acknowledgement != ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea limitelor sediului social lipsește")
    actor = get_user_model().objects.get(username=actor_username, is_staff=True)
    scope = CatalogueScope.objects.select_for_update().get(
        provider="ONRC", county=county
    )
    if scope.visibility == CatalogueScope.Visibility.OFF:
        return scope, False
    previous_run = scope.current_run
    previous_visibility = scope.visibility
    scope.current_run = None
    scope.current_approval = None
    scope.visibility = CatalogueScope.Visibility.OFF
    scope.activated_at = None
    scope.save(
        update_fields=(
            "current_run",
            "current_approval",
            "visibility",
            "activated_at",
        )
    )
    CatalogueActivationEvent.objects.create(
        scope=scope,
        action=CatalogueActivationEvent.Action.DEACTIVATE,
        previous_run=previous_run,
        actor=actor,
        previous_visibility=previous_visibility,
        new_visibility=CatalogueScope.Visibility.OFF,
        acknowledgement=acknowledgement,
        audited_counters={},
    )
    return scope, True


def catalogue_state(county: str) -> CatalogueState:
    """Resolve one catalogue pointer and fail closed on every stale condition."""

    scope = (
        CatalogueScope.objects.select_related(
            "current_run__snapshot", "current_run__activity_evidence_snapshot",
            "current_approval"
        )
        .filter(provider="ONRC", county=county)
        .first()
    )
    if not scope or scope.visibility == CatalogueScope.Visibility.OFF:
        return CatalogueState(status="none", scope=scope)
    run = scope.current_run
    if (
        not run
        or run.county != county
        or run.state != ImportRun.State.SUCCEEDED
        or run.claim_token is not None
        or run.snapshot.state != SourceSnapshot.State.VERIFIED
        or (
            run.scope_contract_version == 2
            and (
                not run.activity_evidence_snapshot
                or run.activity_evidence_snapshot.state
                != SourceSnapshot.State.VERIFIED
            )
        )
    ):
        return CatalogueState(status="unavailable", scope=scope)
    if scope.visibility == CatalogueScope.Visibility.INTERNAL_PREVIEW:
        return (
            CatalogueState(status="active", scope=scope, run=run, preview=True)
            if settings.DEBUG
            else CatalogueState(status="unavailable", scope=scope)
        )
    if (
        scope.visibility == CatalogueScope.Visibility.PUBLIC
        and scope.current_approval
        and scope.current_approval.import_run_id == run.pk
        and publication_approval_is_valid(scope.current_approval)
    ):
        return CatalogueState(status="active", scope=scope, run=run)
    return CatalogueState(status="unavailable", scope=scope)
