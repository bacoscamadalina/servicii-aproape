"""Privacy-minimized read projection for an active ONRC catalogue scope."""

from dataclasses import dataclass
from datetime import datetime

from django.core.paginator import Page, Paginator
from django.db.models import Prefetch, Q

from .catalog import CATEGORIES
from .caen import category_for_caen
from .locations import locality_name
from .models import BusinessCategory, ImportRun, RegisteredBusinessSnapshot
from .service_evidence import valid_service_evidence


CATEGORY_LABELS = {slug: label for slug, label, _description in CATEGORIES}
ELECTRICIANS_CATEGORY = "electricieni"
ELECTRICAL_INSTALLATION_CAEN = "4321"


def catalogue_categories(run: ImportRun) -> tuple[str, ...]:
    """Expose the electrical specialty when the source contains installations.

    The immutable v2 catalogue stores the broad ``instalatii`` category. Its exact
    MF CAEN evidence is retained per company, so 4321 can be projected as a narrower
    search specialty without relabelling plumbing or other installation firms.
    """

    categories = set(run.categories)
    if "instalatii" in categories:
        categories.add(ELECTRICIANS_CATEGORY)
    return tuple(sorted(categories))


@dataclass(frozen=True)
class RegistryListing:
    """Whitelisted registry facts safe for the discovery result list."""

    business_id: int
    legal_name: str
    initials: str
    category_slugs: tuple[str, ...]
    category_labels: tuple[str, ...]
    registered_office_label: str
    evidence_kind: str
    evidence_source_url: str = ""
    evidence_source_title: str = ""
    evidence_summary: str = ""
    coverage_label: str = ""
    evidence_retrieved_at: object | None = None


@dataclass(frozen=True)
class RegistrySearchPage:
    """One stable page plus source attribution shared by all its rows."""

    page: Page
    total: int
    snapshot_date: object
    dataset_url: str
    license_label: str
    activity_evidence_year: int | None
    activity_evidence_dataset_url: str
    activity_evidence_license_label: str
    contains_direct_service_evidence: bool


@dataclass(frozen=True)
class RegistryCompanyDetail:
    """One privacy-minimized company record resolved through an active scope."""

    listing: RegistryListing
    snapshot_date: object
    dataset_url: str
    license_label: str
    activity_evidence_year: int | None
    activity_evidence_dataset_url: str
    activity_evidence_license_label: str


def _initials(legal_name: str) -> str:
    """Derive a compact, non-identifying visual monogram from the legal name."""

    words = [word for word in legal_name.split() if word]
    return "".join(word[0] for word in words[:2]).upper() or "F"


def _visible_records(
    *,
    run: ImportRun,
    county: str,
    allow_direct_evidence: bool,
    siruta_code: str | None,
    category: str,
    exclude_business_ids=(),
    instant: datetime | None = None,
):
    """Return the canonical visible rows and reviewed evidence for one search."""

    scoped_categories = BusinessCategory.objects.filter(category__in=run.categories)
    # Only the offline exporter omits locality; web readers always supply one.
    strict_records = RegisteredBusinessSnapshot.objects.staging_candidates(run)
    if siruta_code is not None:
        strict_records = strict_records.filter(registered_office_siruta=siruta_code)
    if exclude_business_ids:
        strict_records = strict_records.exclude(business_id__in=exclude_business_ids)
    if category:
        strict_records = (
            strict_records.filter(
                primary_activity_evidence__caen_version="2",
                primary_activity_evidence__caen_code=ELECTRICAL_INSTALLATION_CAEN,
            )
            if category == ELECTRICIANS_CATEGORY
            else strict_records.filter(categories__category=category)
        )
        # The retained ONRC category is broad; CAEN 4321 is presented through
        # the separate electrical specialty, not plumbing/heating discovery.
        if category == "instalatii":
            strict_records = strict_records.exclude(
                primary_activity_evidence__caen_version="2",
                primary_activity_evidence__caen_code=ELECTRICAL_INSTALLATION_CAEN,
            )

    evidence_categories = {category} if category else set(run.categories)
    reviewed = (
        valid_service_evidence(county=county, categories=evidence_categories, instant=instant)
        if (
            allow_direct_evidence
            and run.scope_contract_version == 2
            and run.refined_from_run_id
        )
        else []
    )
    evidence_by_business: dict[int, list] = {}
    for item in reviewed:
        evidence_by_business.setdefault(item.business_id, []).append(item)
    reviewed_business_ids = set(evidence_by_business)
    strict_business_ids = set(
        strict_records.filter(business_id__in=reviewed_business_ids).values_list(
            "business_id", flat=True
        )
    )
    overlay_evidence: dict[int, tuple] = {}
    direct_by_business: dict[int, tuple] = {}
    if reviewed_business_ids:
        eligible_base_records = (
            RegisteredBusinessSnapshot.objects.staging_candidates(run.refined_from_run)
            .filter(
                business_id__in=reviewed_business_ids,
            )
            .prefetch_related("caen_codes")
        )
        if siruta_code is not None:
            eligible_base_records = eligible_base_records.filter(
                registered_office_siruta=siruta_code
            )
        for record in eligible_base_records:
            authorized_categories = {
                category_for_caen(activity.code, activity.version)
                for activity in record.caen_codes.all()
            }
            accepted = tuple(
                item
                for item in evidence_by_business[record.business_id]
                if item.category in authorized_categories
            )
            if accepted:
                direct_by_business[record.business_id] = accepted
                if record.business_id not in strict_business_ids:
                    overlay_evidence[record.pk] = accepted

    records = (
        RegisteredBusinessSnapshot.objects.filter(
            Q(pk__in=strict_records.values("pk")) | Q(pk__in=overlay_evidence)
        )
        .prefetch_related(
            Prefetch("categories", queryset=scoped_categories, to_attr="public_categories")
        )
        .select_related("primary_activity_evidence")
        .order_by("legal_name", "id")
    )
    if exclude_business_ids:
        records = records.exclude(business_id__in=exclude_business_ids)
    return records, overlay_evidence, direct_by_business


def _project_listing(
    *,
    record: RegisteredBusinessSnapshot,
    county: str,
    locality_label: str,
    overlay_evidence: dict[int, tuple],
    direct_by_business: dict[int, tuple],
) -> RegistryListing:
    """Whitelist one database row for display without registry identifiers."""

    direct = direct_by_business.get(record.business_id, ())
    primary_categories = tuple(
        item.category
        for item in sorted(record.public_categories, key=lambda item: item.category)
        if item.category in CATEGORY_LABELS
    )
    primary_evidence = getattr(record, "primary_activity_evidence", None)
    if (
        primary_evidence
        and primary_evidence.caen_version == "2"
        and primary_evidence.caen_code == ELECTRICAL_INSTALLATION_CAEN
    ):
        primary_categories = tuple(
            ELECTRICIANS_CATEGORY if item == "instalatii" else item
            for item in primary_categories
        )
    direct_categories = {item.category for item in direct}
    categories = tuple(
        sorted(
            direct_categories
            if record.pk in overlay_evidence
            else set(primary_categories) | direct_categories
        )
    )
    evidence = direct[0] if direct else None
    return RegistryListing(
        business_id=record.business_id,
        legal_name=record.legal_name,
        initials=_initials(record.legal_name),
        category_slugs=categories,
        category_labels=tuple(CATEGORY_LABELS[item] for item in categories),
        registered_office_label=(
            locality_label or locality_name(county, record.registered_office_siruta)
        ),
        evidence_kind=(
            "direct_service" if record.pk in overlay_evidence else "mf_primary"
        ),
        evidence_source_url=evidence.source_url if evidence else "",
        evidence_source_title=evidence.source_title if evidence else "",
        evidence_summary=evidence.evidence_summary if evidence else "",
        coverage_label=county if evidence else "",
        evidence_retrieved_at=evidence.retrieved_at if evidence else None,
    )


def registry_search(
    *,
    run: ImportRun,
    county: str,
    allow_direct_evidence: bool,
    siruta_code: str | None,
    locality_label: str,
    category: str,
    page_number: str,
    page_size: int = 20,
    exclude_business_ids=(),
) -> RegistrySearchPage:
    """Merge strict MF rows with reviewed direct-service evidence, then paginate."""

    records, overlay_evidence, direct_by_business = _visible_records(
        run=run,
        county=county,
        allow_direct_evidence=allow_direct_evidence,
        siruta_code=siruta_code,
        category=category,
        exclude_business_ids=exclude_business_ids,
    )
    paginator = Paginator(records, page_size)
    page = paginator.get_page(page_number)
    listings = []
    for record in page.object_list:
        listings.append(
            _project_listing(
                record=record,
                county=county,
                locality_label=locality_label,
                overlay_evidence=overlay_evidence,
                direct_by_business=direct_by_business,
            )
        )
    page.object_list = listings
    return RegistrySearchPage(
        page=page,
        total=paginator.count,
        snapshot_date=run.snapshot.snapshot_date,
        dataset_url=run.snapshot.dataset_url,
        license_label=run.snapshot.license_label,
        activity_evidence_year=run.activity_evidence_year,
        activity_evidence_dataset_url=(
            run.activity_evidence_snapshot.dataset_url
            if run.activity_evidence_snapshot_id else ""
        ),
        activity_evidence_license_label=(
            run.activity_evidence_snapshot.license_label
            if run.activity_evidence_snapshot_id else ""
        ),
        contains_direct_service_evidence=bool(direct_by_business),
    )


def registry_company_detail(
    *,
    run: ImportRun,
    county: str,
    allow_direct_evidence: bool,
    siruta_code: str | None,
    locality_label: str,
    category: str,
    business_id: int,
) -> RegistryCompanyDetail | None:
    """Resolve one company only if it is visible in the supplied active scope."""

    records, overlay_evidence, direct_by_business = _visible_records(
        run=run,
        county=county,
        allow_direct_evidence=allow_direct_evidence,
        siruta_code=siruta_code,
        category=category,
    )
    record = records.filter(business_id=business_id).first()
    if not record:
        return None
    return RegistryCompanyDetail(
        listing=_project_listing(
            record=record,
            county=county,
            locality_label=locality_label,
            overlay_evidence=overlay_evidence,
            direct_by_business=direct_by_business,
        ),
        snapshot_date=run.snapshot.snapshot_date,
        dataset_url=run.snapshot.dataset_url,
        license_label=run.snapshot.license_label,
        activity_evidence_year=run.activity_evidence_year,
        activity_evidence_dataset_url=(
            run.activity_evidence_snapshot.dataset_url
            if run.activity_evidence_snapshot_id else ""
        ),
        activity_evidence_license_label=(
            run.activity_evidence_snapshot.license_label
            if run.activity_evidence_snapshot_id else ""
        ),
    )
