"""Read-only pilot evidence; no registry row is counted as service coverage."""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Min
from django.utils import timezone

from .catalogue_activation import publication_approval_is_valid
from .lead_insights import provider_lead_insights
from .locations import locality_name
from .models import CatalogueScope, ImportRun, ProviderLead, SourceSnapshot
from .provider_publication import published_provider_search


@dataclass(frozen=True)
class PilotArea:
    """Exact SIRUTA locality with distinct projects and provider snapshots."""

    siruta_code: str
    locality: str
    projects: int
    deliveries: int
    responses: int
    public_providers: int
    preview_providers: int


@dataclass(frozen=True)
class PilotReadiness:
    """A scoped operational projection, never a publication decision."""

    county: str
    category: str
    source_public: bool
    source_state: str
    projects: int
    deliveries: int
    responses: int
    quoted_projects: int
    awarded_projects: int
    first_quote_hours: float | None
    public_providers: int
    preview_providers: int
    unanswered_areas: int
    areas: tuple[PilotArea, ...]


def pilot_readiness(*, county: str, category: str, window_days: int = 30) -> PilotReadiness:
    """Join demand to exact declared coverage after the normal visibility gates."""

    scope = CatalogueScope.objects.select_related(
        "current_approval", "current_run__snapshot"
    ).filter(
        provider="ONRC", county=county
    ).first()
    source_public = bool(
        scope
        and scope.visibility == CatalogueScope.Visibility.PUBLIC
        and scope.current_approval_id
        and scope.current_run_id == scope.current_approval.import_run_id
        and scope.current_run.state == ImportRun.State.SUCCEEDED
        and scope.current_run.snapshot.state == SourceSnapshot.State.VERIFIED
        and publication_approval_is_valid(scope.current_approval)
    )
    providers = published_provider_search(county=county, siruta_code=None, category=category)
    supply = {}
    for provider in providers:
        for area in provider.coverage_areas:
            if area.county != county:
                continue
            counts = supply.setdefault(area.siruta_code, [0, 0])
            counts[1 if provider.preview else 0] += 1

    now = timezone.now()
    demand = provider_lead_insights(
        window_days=window_days, calculated_at=now, county=county, category=category
    )
    # A batch is one project: retain only its earliest provider quote timestamp.
    first_quotes = ProviderLead.objects.filter(
        created_at__gte=now - timedelta(days=demand.window_days),
        created_at__lt=now,
        county=county,
        category=category,
        quotes__isnull=False,
    ).annotate(first_sent_at=Min("quotes__sent_at")).values_list(
        "pk", "batch_id", "created_at", "batch__created_at", "first_sent_at"
    )
    project_times = {}
    for lead_id, batch_id, created_at, batch_created_at, first_sent_at in first_quotes.iterator():
        project_key = ("batch", batch_id) if batch_id else ("direct", lead_id)
        project_created_at = batch_created_at if batch_id else created_at
        elapsed = max((first_sent_at - project_created_at).total_seconds(), 0)
        project_times[project_key] = min(project_times.get(project_key, elapsed), elapsed)
    first_quote_hours = (
        round(sum(project_times.values()) / len(project_times) / 3600, 1)
        if project_times else None
    )
    demand_by_code = {area.siruta_code: area for area in demand.demand_areas}
    areas = tuple(
        sorted(
            (
                PilotArea(
                    siruta_code=code,
                    locality=locality_name(county, code) or code,
                    projects=demand_by_code[code].projects if code in demand_by_code else 0,
                    deliveries=(
                        demand_by_code[code].provider_deliveries
                        if code in demand_by_code else 0
                    ),
                    responses=(
                        demand_by_code[code].provider_responses
                        if code in demand_by_code else 0
                    ),
                    public_providers=counts[0],
                    preview_providers=counts[1],
                )
                for code, counts in (
                    (code, supply.get(code, [0, 0]))
                    for code in set(supply) | set(demand_by_code)
                )
            ),
            key=lambda area: (-area.projects, -area.public_providers, area.locality),
        )
    )
    return PilotReadiness(
        county=county,
        category=category,
        source_public=source_public,
        source_state=scope.get_visibility_display() if scope else "Fără catalog activ",
        projects=demand.total_projects,
        deliveries=demand.provider_deliveries,
        responses=demand.provider_responses,
        quoted_projects=demand.quoted_projects,
        awarded_projects=demand.awarded_projects,
        first_quote_hours=first_quote_hours,
        public_providers=len([provider for provider in providers if not provider.preview]),
        preview_providers=len([provider for provider in providers if provider.preview]),
        unanswered_areas=sum(
            area.projects > 0 and area.responses == 0 for area in areas
        ),
        areas=areas,
    )
