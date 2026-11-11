"""Privacy-minimized demand and response aggregates for provider requests."""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .catalog import CATEGORIES
from .locations import locality_name
from .models import ProviderLead, ProviderQuote


WINDOW_DAYS = (7, 30, 90)
CATEGORY_LABELS = {slug: label for slug, label, _description in CATEGORIES}


@dataclass(frozen=True)
class LeadDemandInsight:
    """One aggregate row that cannot expose a customer or provider identity."""

    category: str
    category_label: str
    county: str
    siruta_code: str
    locality: str
    projects: int
    provider_deliveries: int
    provider_responses: int
    quoted_projects: int
    awarded_projects: int

    @property
    def average_recipients(self) -> float:
        """Show how broadly submitted demand could be distributed."""

        return round(self.provider_deliveries / self.projects, 1) if self.projects else 0


@dataclass(frozen=True)
class LeadCategoryInsight:
    """Demand totals for one curated service category."""

    category: str
    label: str
    projects: int
    provider_deliveries: int
    provider_responses: int
    quoted_projects: int
    awarded_projects: int


@dataclass(frozen=True)
class ProviderLeadInsights:
    """Fixed-window operational projection over submitted customer projects."""

    window_days: int
    window_start: object
    window_end: object
    calculated_at: object
    total_projects: int
    provider_deliveries: int
    provider_responses: int
    quoted_projects: int
    awarded_projects: int
    categories: tuple[LeadCategoryInsight, ...]
    demand_areas: tuple[LeadDemandInsight, ...]


def normalized_insight_window_days(raw_days) -> int:
    """Accept only the three documented windows and default to 30 days."""

    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return 30
    return days if days in WINDOW_DAYS else 30


def provider_lead_insights(
    *, window_days=30, calculated_at=None, county=None, category=None
) -> ProviderLeadInsights:
    """Aggregate projects by exact service area in one identity-free query.

    A batch represents one customer project even though it produces several provider
    deliveries. Direct requests remain one project and one delivery.
    """

    days = normalized_insight_window_days(window_days)
    now = calculated_at or timezone.now()
    window_start = now - timedelta(days=days)
    leads = ProviderLead.objects.filter(
        created_at__gte=window_start,
        created_at__lt=now,
    )
    if county:
        leads = leads.filter(county=county)
    if category:
        leads = leads.filter(category=category)
    grouped = leads.values("category", "county", "siruta_code").annotate(
        direct_projects=Count("pk", filter=Q(batch__isnull=True), distinct=True),
        batch_projects=Count("batch_id", filter=Q(batch__isnull=False), distinct=True),
        provider_deliveries=Count("pk", distinct=True),
        provider_responses=Count(
            "pk",
            filter=Q(quotes__isnull=False),
            distinct=True,
        ),
        direct_quoted=Count(
            "pk", filter=Q(batch__isnull=True, quotes__isnull=False), distinct=True
        ),
        batch_quoted=Count(
            "batch_id", filter=Q(batch__isnull=False, quotes__isnull=False), distinct=True
        ),
        direct_awards=Count(
            "pk",
            filter=Q(
                batch__isnull=True,
                quotes__status=ProviderQuote.Status.ACCEPTED,
            ),
            distinct=True,
        ),
        batch_awards=Count(
            "batch_id",
            filter=Q(
                batch__isnull=False,
                quotes__status=ProviderQuote.Status.ACCEPTED,
            ),
            distinct=True,
        ),
    )
    demand_areas = tuple(
        sorted(
            (
                LeadDemandInsight(
                    category=row["category"],
                    category_label=str(
                        CATEGORY_LABELS.get(row["category"], row["category"])
                    ),
                    county=row["county"],
                    siruta_code=row["siruta_code"],
                    locality=locality_name(row["county"], row["siruta_code"]),
                    projects=row["direct_projects"] + row["batch_projects"],
                    provider_deliveries=row["provider_deliveries"],
                    provider_responses=row["provider_responses"],
                    quoted_projects=row["direct_quoted"] + row["batch_quoted"],
                    awarded_projects=row["direct_awards"] + row["batch_awards"],
                )
                for row in grouped
            ),
            key=lambda item: (-item.projects, item.county, item.locality, item.category),
        )
    )
    category_totals = {
        slug: {
            "projects": 0,
            "provider_deliveries": 0,
            "provider_responses": 0,
            "quoted_projects": 0,
            "awarded_projects": 0,
        }
        for slug, _label, _description in CATEGORIES
    }
    for area in demand_areas:
        totals = category_totals.setdefault(
            area.category,
            {
                "projects": 0,
                "provider_deliveries": 0,
                "provider_responses": 0,
                "quoted_projects": 0,
                "awarded_projects": 0,
            },
        )
        totals["projects"] += area.projects
        totals["provider_deliveries"] += area.provider_deliveries
        totals["provider_responses"] += area.provider_responses
        totals["quoted_projects"] += area.quoted_projects
        totals["awarded_projects"] += area.awarded_projects
    categories = tuple(
        LeadCategoryInsight(
            category=slug,
            label=str(CATEGORY_LABELS.get(slug, slug)),
            **totals,
        )
        for slug, totals in category_totals.items()
    )
    return ProviderLeadInsights(
        window_days=days,
        window_start=window_start,
        window_end=now,
        calculated_at=now,
        total_projects=sum(item.projects for item in demand_areas),
        provider_deliveries=sum(item.provider_deliveries for item in demand_areas),
        provider_responses=sum(item.provider_responses for item in demand_areas),
        quoted_projects=sum(item.quoted_projects for item in demand_areas),
        awarded_projects=sum(item.awarded_projects for item in demand_areas),
        categories=categories,
        demand_areas=demand_areas,
    )
