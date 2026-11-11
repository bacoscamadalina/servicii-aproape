"""Bounded, identity-free integrity audit for personal-data requests."""

from dataclasses import dataclass
from itertools import chain, groupby
from operator import itemgetter
import re

from .data_retention import REDACTED_DATA_REQUEST_TEXT
from .data_subject_exports import (
    EXPORT_ACKNOWLEDGEMENT,
    EXPORT_POLICY_VERSION,
)
from .data_subject_requests import (
    EXTENSION_ACKNOWLEDGEMENT,
    POLICY_VERSION,
    PROCESS_ACKNOWLEDGEMENT,
    add_calendar_months,
    initial_data_request_due_at,
)
from .models import DataSubjectRequest, DataSubjectRequestEvent


ANOMALY_CODES = (
    "request_revision_mismatch",
    "request_status_mismatch",
    "initial_deadline_mismatch",
    "extension_contract_mismatch",
    "request_timeline_mismatch",
    "event_revision_mismatch",
    "event_transition_mismatch",
    "event_metadata_mismatch",
    "event_chronology_mismatch",
)

_ALLOWED_STATUS_TRANSITIONS = {
    DataSubjectRequest.Status.RECEIVED: {
        DataSubjectRequest.Status.IDENTITY_PENDING,
        DataSubjectRequest.Status.IN_REVIEW,
    },
    DataSubjectRequest.Status.IDENTITY_PENDING: {
        DataSubjectRequest.Status.IN_REVIEW,
    },
    DataSubjectRequest.Status.IN_REVIEW: {
        DataSubjectRequest.Status.FULFILLED,
        DataSubjectRequest.Status.REFUSED,
    },
}
_EVENT_METADATA = {
    DataSubjectRequestEvent.Action.STATUS_TRANSITION: (
        {POLICY_VERSION},
        PROCESS_ACKNOWLEDGEMENT,
    ),
    DataSubjectRequestEvent.Action.DEADLINE_EXTENDED: (
        {POLICY_VERSION},
        EXTENSION_ACKNOWLEDGEMENT,
    ),
    DataSubjectRequestEvent.Action.EXPORT_GENERATED: (
        {EXPORT_POLICY_VERSION},
        EXPORT_ACKNOWLEDGEMENT,
    ),
}
_EXPORT_NOTE = re.compile(r"^Pachet JSON generat în memorie; SHA-256 [0-9a-f]{64}\.$")


@dataclass(frozen=True)
class DataSubjectRequestIntegrityAudit:
    """Fixed aggregate output that cannot disclose requester identity."""

    total_requests: int
    total_events: int
    anomaly_counts: tuple[tuple[str, int], ...]

    @property
    def is_valid(self) -> bool:
        """Return true only when every audited request chain is coherent."""

        return not any(count for _code, count in self.anomaly_counts)

    def as_dict(self) -> dict:
        """Return a deterministic JSON-ready monitoring projection."""

        return {
            "schema_version": 1,
            "valid": self.is_valid,
            "totals": {
                "requests": self.total_requests,
                "events": self.total_events,
            },
            "anomalies": dict(self.anomaly_counts),
        }


def _audit_request(rows):
    """Evaluate one request and its ordered event stream without retaining identities."""

    first = next(rows)
    request_rows = chain((first,), rows)
    flags = dict.fromkeys(ANOMALY_CODES, False)
    current_status = DataSubjectRequest.Status.RECEIVED
    event_count = 0
    extension_events = 0
    extension_event_at = None
    identity_event_at = None
    closed_event_at = None
    previous_order = None
    retained = first["retention_applied_at"] is not None

    for row in request_rows:
        if row["events__id"] is None:
            continue
        event_count += 1
        action = row["events__action"]
        previous_status = row["events__previous_status"]
        new_status = row["events__new_status"]
        if row["events__revision"] != event_count:
            flags["event_revision_mismatch"] = True

        order = (row["events__created_at"], row["events__id"])
        if previous_order is not None and previous_order >= order:
            flags["event_chronology_mismatch"] = True
        previous_order = order

        metadata = _EVENT_METADATA.get(action)
        note = row["events__internal_note"]
        note_is_valid = (
            note == REDACTED_DATA_REQUEST_TEXT
            if retained
            else len(note) >= 8 and note == " ".join(note.split())
        )
        if (
            metadata is None
            or row["events__policy_version"] not in metadata[0]
            or row["events__acknowledgement"] != metadata[1]
            or not note_is_valid
            or (
                action == DataSubjectRequestEvent.Action.EXPORT_GENERATED
                and not retained
                and _EXPORT_NOTE.fullmatch(note) is None
            )
        ):
            flags["event_metadata_mismatch"] = True

        if action == DataSubjectRequestEvent.Action.STATUS_TRANSITION:
            if (
                previous_status != current_status
                or new_status not in _ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
            ):
                flags["event_transition_mismatch"] = True
            current_status = new_status
            if new_status == DataSubjectRequest.Status.IN_REVIEW:
                identity_event_at = row["events__created_at"]
            elif new_status in (
                DataSubjectRequest.Status.FULFILLED,
                DataSubjectRequest.Status.REFUSED,
            ):
                closed_event_at = row["events__created_at"]
        elif action == DataSubjectRequestEvent.Action.DEADLINE_EXTENDED:
            extension_events += 1
            extension_event_at = row["events__created_at"]
            if (
                current_status
                in (
                    DataSubjectRequest.Status.FULFILLED,
                    DataSubjectRequest.Status.REFUSED,
                )
                or previous_status != current_status
                or new_status != current_status
            ):
                flags["event_transition_mismatch"] = True
        elif action == DataSubjectRequestEvent.Action.EXPORT_GENERATED:
            if (
                current_status != DataSubjectRequest.Status.IN_REVIEW
                or previous_status != current_status
                or new_status != current_status
            ):
                flags["event_transition_mismatch"] = True
        else:
            flags["event_transition_mismatch"] = True

    if first["revision"] != event_count:
        flags["request_revision_mismatch"] = True
    if first["status"] != current_status:
        flags["request_status_mismatch"] = True
    if first["due_at"] != initial_data_request_due_at(first["received_at"]):
        flags["initial_deadline_mismatch"] = True

    extended_due_at = first["extended_due_at"]
    notified_at = first["extension_notified_at"]
    has_extension = extended_due_at is not None and notified_at is not None
    if (
        (extended_due_at is None) != (notified_at is None)
        or extension_events != int(has_extension)
        or (
            has_extension
            and (
                extended_due_at != add_calendar_months(first["due_at"], 2)
                or notified_at > first["due_at"]
                or extension_event_at is None
                or notified_at > extension_event_at
            )
        )
    ):
        flags["extension_contract_mismatch"] = True

    identity_at = first["identity_verified_at"]
    closed_at = first["closed_at"]
    status_requires_identity = first["status"] in (
        DataSubjectRequest.Status.IN_REVIEW,
        DataSubjectRequest.Status.FULFILLED,
        DataSubjectRequest.Status.REFUSED,
    )
    status_is_closed = first["status"] in (
        DataSubjectRequest.Status.FULFILLED,
        DataSubjectRequest.Status.REFUSED,
    )
    if (
        (identity_at is not None) != status_requires_identity
        or (closed_at is not None) != status_is_closed
        or (identity_at is not None and identity_at < first["received_at"])
        or (notified_at is not None and notified_at < first["received_at"])
        or (closed_at is not None and identity_at is not None and closed_at < identity_at)
        or (
            status_requires_identity
            and (identity_event_at is None or identity_at > identity_event_at)
        )
        or (
            status_is_closed
            and (closed_event_at is None or closed_at > closed_event_at)
        )
    ):
        flags["request_timeline_mismatch"] = True

    return event_count, flags


def audit_data_subject_requests(
    *, chunk_size: int = 2_000
) -> DataSubjectRequestIntegrityAudit:
    """Audit every request through one streaming LEFT JOIN without changing data."""

    rows = (
        DataSubjectRequest.objects.order_by("pk", "events__revision", "events__id")
        .values(
            "id",
            "status",
            "revision",
            "received_at",
            "due_at",
            "extended_due_at",
            "extension_notified_at",
            "identity_verified_at",
            "closed_at",
            "retention_applied_at",
            "events__id",
            "events__action",
            "events__previous_status",
            "events__new_status",
            "events__revision",
            "events__internal_note",
            "events__policy_version",
            "events__acknowledgement",
            "events__created_at",
        )
    )
    anomalies = dict.fromkeys(ANOMALY_CODES, 0)
    total_requests = 0
    total_events = 0
    for _request_id, request_rows in groupby(
        rows.iterator(chunk_size=chunk_size), key=itemgetter("id")
    ):
        total_requests += 1
        event_count, flags = _audit_request(request_rows)
        total_events += event_count
        for code, present in flags.items():
            anomalies[code] += int(present)

    return DataSubjectRequestIntegrityAudit(
        total_requests=total_requests,
        total_events=total_events,
        anomaly_counts=tuple((code, anomalies[code]) for code in ANOMALY_CODES),
    )
