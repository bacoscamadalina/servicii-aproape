"""Audited transitions for the operational queue of immutable public reports."""

from django.db import transaction

from .models import (
    ProviderMembership,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
)
from .provider_publication import publication_submission_contract_is_valid


TRIAGE_POLICY_VERSIONS = ("2026-08-27-v1",)
TRIAGE_POLICY_VERSION = TRIAGE_POLICY_VERSIONS[-1]
TRIAGE_ACKNOWLEDGEMENT = (
    "Am analizat sesizarea și confirm că această decizie nu modifică automat "
    "vizibilitatea profilului."
)


def _require_triage_reviewer(reviewer, *, profile_id: int) -> None:
    """Reject unauthorized or provider-conflicted administrative reviewers."""

    if not (
        reviewer.is_active
        and reviewer.is_staff
        and reviewer.has_perm("services.triage_public_provider_report")
    ):
        raise PermissionError("Nu ai permisiunea de a analiza această sesizare.")
    if ProviderMembership.objects.filter(profile_id=profile_id, user=reviewer).exclude(
        state=ProviderMembership.State.REVOKED
    ).exists():
        raise PermissionError("Nu poți analiza o sesizare despre propriul profil.")


def _validated_note_and_acknowledgement(*, internal_note: str, acknowledgement: str) -> str:
    normalized_note = " ".join(internal_note.split())
    if len(normalized_note) < 8:
        raise ValueError("Nota internă trebuie să explice pe scurt decizia.")
    if acknowledgement != TRIAGE_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea regulilor de analiză este obligatorie.")
    return normalized_note


def _locked_case(case_id: int) -> PublicProviderReportCase:
    """Lock the pre-existing case row and load the exact snapshot needed for integrity."""

    return (
        PublicProviderReportCase.objects.select_for_update()
        .select_related(
            "report__submission__profile__business",
            "report__submission__service_area_submission",
        )
        .get(pk=case_id)
    )


@transaction.atomic
def start_public_provider_report_review(
    *, case_id: int, reviewer, expected_revision: int, internal_note: str, acknowledgement: str
):
    """Claim a new case for review without changing its report or provider profile."""

    case = _locked_case(case_id)
    _require_triage_reviewer(reviewer, profile_id=case.report.submission.profile_id)
    if case.revision != expected_revision:
        raise ValueError("Dosarul a fost modificat de alt administrator. Reîncarcă pagina.")
    if case.state != PublicProviderReportCase.State.NEW:
        raise ValueError("Doar o sesizare nouă poate fi preluată în analiză.")
    if not publication_submission_contract_is_valid(case.report.submission):
        raise ValueError("Integritatea snapshotului raportat nu mai poate fi confirmată.")
    note = _validated_note_and_acknowledgement(
        internal_note=internal_note, acknowledgement=acknowledgement
    )
    revision = case.revision + 1
    PublicProviderReportTriageEvent.objects.create(
        case=case,
        previous_state=case.state,
        new_state=PublicProviderReportCase.State.IN_REVIEW,
        revision=revision,
        internal_note=note,
        policy_version=TRIAGE_POLICY_VERSION,
        acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        actor=reviewer,
    )
    case.state = PublicProviderReportCase.State.IN_REVIEW
    case.revision = revision
    case.save(update_fields=("state", "revision", "updated_at"))
    return case


@transaction.atomic
def close_public_provider_report_case(
    *, case_id: int, reviewer, expected_revision: int, outcome: str, internal_note: str, acknowledgement: str
):
    """Close one in-review case while leaving publication state untouched."""

    case = _locked_case(case_id)
    _require_triage_reviewer(reviewer, profile_id=case.report.submission.profile_id)
    if case.revision != expected_revision:
        raise ValueError("Dosarul a fost modificat de alt administrator. Reîncarcă pagina.")
    if case.state != PublicProviderReportCase.State.IN_REVIEW:
        raise ValueError("Doar o sesizare aflată în analiză poate fi închisă.")
    if outcome not in PublicProviderReportCase.Outcome.values:
        raise ValueError("Alege o concluzie validă.")
    if not publication_submission_contract_is_valid(case.report.submission):
        raise ValueError("Integritatea snapshotului raportat nu mai poate fi confirmată.")
    note = _validated_note_and_acknowledgement(
        internal_note=internal_note, acknowledgement=acknowledgement
    )
    revision = case.revision + 1
    PublicProviderReportTriageEvent.objects.create(
        case=case,
        previous_state=case.state,
        new_state=PublicProviderReportCase.State.CLOSED,
        outcome=outcome,
        revision=revision,
        internal_note=note,
        policy_version=TRIAGE_POLICY_VERSION,
        acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        actor=reviewer,
    )
    case.state = PublicProviderReportCase.State.CLOSED
    case.outcome = outcome
    case.revision = revision
    case.save(update_fields=("state", "outcome", "revision", "updated_at"))
    return case
