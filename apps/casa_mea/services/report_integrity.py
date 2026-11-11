"""Bounded, identity-free integrity audit for public-report triage."""

from dataclasses import dataclass

from django.db.models import Count, Max, Q

from .models import PublicProviderReport, PublicProviderReportCase
from .report_triage import TRIAGE_ACKNOWLEDGEMENT, TRIAGE_POLICY_VERSIONS


ANOMALY_CODES = (
    "report_without_case",
    "case_state_mismatch",
    "case_revision_mismatch",
    "case_outcome_mismatch",
    "event_count_mismatch",
    "event_transition_mismatch",
    "event_revision_mismatch",
    "event_outcome_mismatch",
    "event_metadata_mismatch",
    "event_chronology_mismatch",
)


@dataclass(frozen=True)
class PublicReportTriageIntegrityAudit:
    """Fixed aggregate output that cannot disclose report or provider identity."""

    total_reports: int
    total_cases: int
    total_events: int
    anomaly_counts: tuple[tuple[str, int], ...]

    @property
    def is_valid(self) -> bool:
        """Return true only when every audited invariant holds."""

        return not any(count for _code, count in self.anomaly_counts)

    def as_dict(self) -> dict:
        """Return a deterministic, JSON-ready aggregate projection."""

        return {
            "schema_version": 1,
            "valid": self.is_valid,
            "totals": {
                "reports": self.total_reports,
                "cases": self.total_cases,
                "events": self.total_events,
            },
            "anomalies": dict(self.anomaly_counts),
        }


def audit_public_provider_report_triage(
    *, chunk_size: int = 2_000
) -> PublicReportTriageIntegrityAudit:
    """Audit every report in one bounded aggregate query without changing data."""

    anomalies = dict.fromkeys(ANOMALY_CODES, 0)
    close_outcome_annotations = {
        f"close_outcome_{outcome}": Count(
            "triage_case__events",
            filter=Q(
                triage_case__events__new_state=PublicProviderReportCase.State.CLOSED,
                triage_case__events__outcome=outcome,
            ),
        )
        for outcome in PublicProviderReportCase.Outcome.values
    }
    reports = (
        PublicProviderReport.objects.order_by("pk")
        .annotate(
            events_total=Count("triage_case__events"),
            revision_one_count=Count(
                "triage_case__events",
                filter=Q(triage_case__events__revision=1),
            ),
            revision_two_count=Count(
                "triage_case__events",
                filter=Q(triage_case__events__revision=2),
            ),
            start_transition_count=Count(
                "triage_case__events",
                filter=Q(
                    triage_case__events__previous_state=PublicProviderReportCase.State.NEW,
                    triage_case__events__new_state=PublicProviderReportCase.State.IN_REVIEW,
                ),
            ),
            close_transition_count=Count(
                "triage_case__events",
                filter=Q(
                    triage_case__events__previous_state=PublicProviderReportCase.State.IN_REVIEW,
                    triage_case__events__new_state=PublicProviderReportCase.State.CLOSED,
                ),
            ),
            start_blank_outcome_count=Count(
                "triage_case__events",
                filter=Q(
                    triage_case__events__new_state=PublicProviderReportCase.State.IN_REVIEW,
                    triage_case__events__outcome="",
                ),
            ),
            valid_metadata_count=Count(
                "triage_case__events",
                filter=(
                    Q(
                        triage_case__events__policy_version__in=TRIAGE_POLICY_VERSIONS,
                        triage_case__events__acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
                        triage_case__events__internal_note__regex=r"^\S+( \S+)*$",
                    )
                    & Q(triage_case__events__internal_note__regex=r"^.{8,}$")
                ),
            ),
            revision_one_created_at=Max(
                "triage_case__events__created_at",
                filter=Q(triage_case__events__revision=1),
            ),
            revision_two_created_at=Max(
                "triage_case__events__created_at",
                filter=Q(triage_case__events__revision=2),
            ),
            revision_one_id=Max(
                "triage_case__events__id",
                filter=Q(triage_case__events__revision=1),
            ),
            revision_two_id=Max(
                "triage_case__events__id",
                filter=Q(
                    triage_case__events__revision=2,
                ),
            ),
            **close_outcome_annotations,
        )
        .values(
            "triage_case__id",
            "triage_case__state",
            "triage_case__outcome",
            "triage_case__revision",
            "events_total",
            "revision_one_count",
            "revision_two_count",
            "start_transition_count",
            "close_transition_count",
            "start_blank_outcome_count",
            "valid_metadata_count",
            "revision_one_created_at",
            "revision_two_created_at",
            "revision_one_id",
            "revision_two_id",
            *close_outcome_annotations,
        )
    )

    total_reports = 0
    total_cases = 0
    total_events = 0
    expected_revisions = {
        PublicProviderReportCase.State.NEW: 0,
        PublicProviderReportCase.State.IN_REVIEW: 1,
        PublicProviderReportCase.State.CLOSED: 2,
    }
    expected_event_counts = expected_revisions
    for report in reports.iterator(chunk_size=chunk_size):
        total_reports += 1
        if report["triage_case__id"] is None:
            anomalies["report_without_case"] += 1
            continue
        total_cases += 1
        total_events += report["events_total"]
        state = report["triage_case__state"]
        expected_revision = expected_revisions.get(state)
        if expected_revision is None:
            anomalies["case_state_mismatch"] += 1
        elif report["triage_case__revision"] != expected_revision:
            anomalies["case_revision_mismatch"] += 1

        outcome_is_valid = (
            report["triage_case__outcome"] in PublicProviderReportCase.Outcome.values
            if state == PublicProviderReportCase.State.CLOSED
            else report["triage_case__outcome"] == ""
        )
        if not outcome_is_valid:
            anomalies["case_outcome_mismatch"] += 1

        expected_events = expected_event_counts.get(state, 0)
        if report["events_total"] != expected_events:
            anomalies["event_count_mismatch"] += 1

        expected_revision_one = int(
            state
            in (
                PublicProviderReportCase.State.IN_REVIEW,
                PublicProviderReportCase.State.CLOSED,
            )
        )
        expected_revision_two = int(state == PublicProviderReportCase.State.CLOSED)
        if (
            report["start_transition_count"] != expected_revision_one
            or report["close_transition_count"] != expected_revision_two
        ):
            anomalies["event_transition_mismatch"] += 1
        if (
            report["revision_one_count"] != expected_revision_one
            or report["revision_two_count"] != expected_revision_two
            or report["events_total"]
            != expected_revision_one + expected_revision_two
        ):
            anomalies["event_revision_mismatch"] += 1
        expected_close_outcome_count = report.get(
            f"close_outcome_{report['triage_case__outcome']}", 0
        )
        if (
            report["start_blank_outcome_count"] != expected_revision_one
            or expected_close_outcome_count != expected_revision_two
        ):
            anomalies["event_outcome_mismatch"] += 1
        if report["valid_metadata_count"] != report["events_total"]:
            anomalies["event_metadata_mismatch"] += 1
        if (
            expected_revision_two
            and report["revision_one_count"] == 1
            and report["revision_two_count"] == 1
        ):
            first_order = (
                report["revision_one_created_at"],
                report["revision_one_id"],
            )
            second_order = (
                report["revision_two_created_at"],
                report["revision_two_id"],
            )
            if first_order >= second_order:
                anomalies["event_chronology_mismatch"] += 1

    return PublicReportTriageIntegrityAudit(
        total_reports=total_reports,
        total_cases=total_cases,
        total_events=total_events,
        anomaly_counts=tuple((code, anomalies[code]) for code in ANOMALY_CODES),
    )
