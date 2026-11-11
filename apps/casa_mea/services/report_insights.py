"""Privacy-safe aggregate facts for the administrative report queue."""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Min
from django.utils import timezone

from .models import (
    PublicProviderReport,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
)


WINDOW_DAYS = (7, 30, 90)


@dataclass(frozen=True)
class QueueStateInsight:
    """One current state count and its oldest report intake timestamp."""

    value: str
    label: str
    count: int
    oldest_report_at: object | None


@dataclass(frozen=True)
class CountInsight:
    """One labelled aggregate count without report or provider identity."""

    value: str
    label: str
    count: int


@dataclass(frozen=True)
class PublicReportInsights:
    """A fixed-size aggregate projection over one exact rolling window."""

    window_days: int
    window_start: object
    window_end: object
    calculated_at: object
    current_states: tuple[QueueStateInsight, ...]
    intake_reasons: tuple[CountInsight, ...]
    started_transitions: int
    closed_transitions: int
    closed_outcomes: tuple[CountInsight, ...]
    reports_without_case: int

    @property
    def current_total(self) -> int:
        """Return the case total without introducing a second stored aggregate."""

        return sum(item.count for item in self.current_states)


def normalized_insight_window_days(raw_days) -> int:
    """Accept only the documented windows and otherwise use the 30-day default."""

    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return 30
    return days if days in WINDOW_DAYS else 30


def public_report_insights(*, window_days=30, calculated_at=None) -> PublicReportInsights:
    """Compute the operational projection in exactly four aggregate queries."""

    days = normalized_insight_window_days(window_days)
    now = calculated_at or timezone.now()
    window_start = now - timedelta(days=days)
    state_rows = {
        row["state"]: row
        for row in PublicProviderReportCase.objects.values("state").annotate(
            total=Count("pk"),
            oldest_report_at=Min("report__created_at"),
        )
    }
    reason_counts = dict(
        PublicProviderReport.objects.filter(
            created_at__gte=window_start,
            created_at__lt=now,
        )
        .values_list("reason")
        .annotate(total=Count("pk"))
        .values_list("reason", "total")
    )
    event_counts = {
        (row["new_state"], row["outcome"]): row["total"]
        for row in PublicProviderReportTriageEvent.objects.filter(
            created_at__gte=window_start,
            created_at__lt=now,
        )
        .values("new_state", "outcome")
        .annotate(total=Count("pk"))
    }
    reports_without_case = PublicProviderReport.objects.filter(
        triage_case__isnull=True
    ).count()
    return PublicReportInsights(
        window_days=days,
        window_start=window_start,
        window_end=now,
        calculated_at=now,
        current_states=tuple(
            QueueStateInsight(
                value=value,
                label=label,
                count=state_rows.get(value, {}).get("total", 0),
                oldest_report_at=state_rows.get(value, {}).get("oldest_report_at"),
            )
            for value, label in PublicProviderReportCase.State.choices
        ),
        intake_reasons=tuple(
            CountInsight(value, label, reason_counts.get(value, 0))
            for value, label in PublicProviderReport.Reason.choices
        ),
        started_transitions=sum(
            count
            for (state, _outcome), count in event_counts.items()
            if state == PublicProviderReportCase.State.IN_REVIEW
        ),
        closed_transitions=sum(
            count
            for (state, _outcome), count in event_counts.items()
            if state == PublicProviderReportCase.State.CLOSED
        ),
        closed_outcomes=tuple(
            CountInsight(
                value,
                label,
                event_counts.get((PublicProviderReportCase.State.CLOSED, value), 0),
            )
            for value, label in PublicProviderReportCase.Outcome.choices
        ),
        reports_without_case=reports_without_case,
    )
