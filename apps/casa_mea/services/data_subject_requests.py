"""Audited administration of personal-data rights requests."""

from calendar import monthrange

from django.db import transaction
from django.utils import timezone

from .models import DataSubjectRequest, DataSubjectRequestEvent


POLICY_VERSION = "2026-09-02-v1"
PROCESS_ACKNOWLEDGEMENT = (
    "Confirm că am verificat identitatea în mod proporțional și că nota documentează "
    "acțiunea fără date personale inutile."
)
EXTENSION_ACKNOWLEDGEMENT = (
    "Confirm că persoana a fost informată despre prelungire și motiv înaintea "
    "expirării termenului inițial."
)


def add_calendar_months(value, months):
    """Advance a timestamp by calendar months, clamping only an unavailable day."""

    zero_based_month = value.month - 1 + months
    year = value.year + zero_based_month // 12
    month = zero_based_month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def initial_data_request_due_at(received_at):
    """Return the one-calendar-month initial response deadline."""

    return add_calendar_months(received_at, 1)


def _require_processor(actor):
    """Keep request contents and decisions behind one dedicated permission."""

    if not (
        actor.is_active
        and actor.is_staff
        and actor.has_perm("services.process_data_subject_request")
    ):
        raise PermissionError("Nu ai permisiunea de a procesa această cerere.")


def _validated_note(note):
    normalized = " ".join(note.split())
    if len(normalized) < 8:
        raise ValueError("Nota internă trebuie să explice acțiunea efectuată.")
    return normalized


@transaction.atomic
def advance_data_subject_request(
    *, request_id, actor, expected_revision, new_status, internal_note, acknowledgement, now=None
):
    """Advance one locked request through its fixed state machine."""

    item = DataSubjectRequest.objects.select_for_update().get(pk=request_id)
    _require_processor(actor)
    if item.revision != expected_revision:
        raise ValueError("Cererea a fost modificată de alt administrator. Reîncarcă pagina.")
    allowed = {
        DataSubjectRequest.Status.RECEIVED: (
            DataSubjectRequest.Status.IDENTITY_PENDING,
            DataSubjectRequest.Status.IN_REVIEW,
        ),
        DataSubjectRequest.Status.IDENTITY_PENDING: (
            DataSubjectRequest.Status.IN_REVIEW,
        ),
        DataSubjectRequest.Status.IN_REVIEW: (
            DataSubjectRequest.Status.FULFILLED,
            DataSubjectRequest.Status.REFUSED,
        ),
    }
    if new_status not in allowed.get(item.status, ()):
        raise ValueError("Această schimbare de stare nu este permisă.")
    if acknowledgement != PROCESS_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea regulilor de procesare este obligatorie.")
    note = _validated_note(internal_note)
    effective_now = now or timezone.now()
    revision = item.revision + 1
    DataSubjectRequestEvent.objects.create(
        request=item,
        action=DataSubjectRequestEvent.Action.STATUS_TRANSITION,
        previous_status=item.status,
        new_status=new_status,
        revision=revision,
        internal_note=note,
        policy_version=POLICY_VERSION,
        acknowledgement=PROCESS_ACKNOWLEDGEMENT,
        actor=actor,
    )
    item.status = new_status
    item.revision = revision
    update_fields = ["status", "revision", "updated_at"]
    if new_status == DataSubjectRequest.Status.IN_REVIEW:
        item.identity_verified_at = effective_now
        update_fields.append("identity_verified_at")
    if new_status in (
        DataSubjectRequest.Status.FULFILLED,
        DataSubjectRequest.Status.REFUSED,
    ):
        item.closed_at = effective_now
        update_fields.append("closed_at")
    item.save(update_fields=update_fields)
    return item


@transaction.atomic
def extend_data_subject_request_deadline(
    *, request_id, actor, expected_revision, internal_note, acknowledgement, now=None
):
    """Record the single notified two-month extension before the initial deadline."""

    item = DataSubjectRequest.objects.select_for_update().get(pk=request_id)
    _require_processor(actor)
    if item.revision != expected_revision:
        raise ValueError("Cererea a fost modificată de alt administrator. Reîncarcă pagina.")
    if item.status in (
        DataSubjectRequest.Status.FULFILLED,
        DataSubjectRequest.Status.REFUSED,
    ):
        raise ValueError("O cerere închisă nu mai poate fi prelungită.")
    if item.extended_due_at is not None:
        raise ValueError("Termenul acestei cereri a fost deja prelungit.")
    effective_now = now or timezone.now()
    if effective_now > item.due_at:
        raise ValueError("Termenul inițial a expirat; prelungirea nu mai poate fi înregistrată ca notificată la timp.")
    if acknowledgement != EXTENSION_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea notificării prelungirii este obligatorie.")
    note = _validated_note(internal_note)
    revision = item.revision + 1
    DataSubjectRequestEvent.objects.create(
        request=item,
        action=DataSubjectRequestEvent.Action.DEADLINE_EXTENDED,
        previous_status=item.status,
        new_status=item.status,
        revision=revision,
        internal_note=note,
        policy_version=POLICY_VERSION,
        acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
        actor=actor,
    )
    item.extended_due_at = add_calendar_months(item.due_at, 2)
    item.extension_notified_at = effective_now
    item.revision = revision
    item.save(
        update_fields=(
            "extended_due_at",
            "extension_notified_at",
            "revision",
            "updated_at",
        )
    )
    return item
