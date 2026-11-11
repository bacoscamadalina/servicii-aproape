"""Identity-free, read-only audit of the explicitly declared production launch area."""

from dataclasses import dataclass

from django.utils import timezone

from .catalogue_activation import audit_run_for_catalogue, publication_approval_is_valid
from .data_subject_integrity import audit_data_subject_requests
from .models import CatalogueScope
from .report_integrity import audit_public_provider_report_triage
from .retention_integrity import audit_retention_integrity


ANOMALY_CODES = (
    "missing_scope",
    "missing_run",
    "run_county_mismatch",
    "run_integrity_failed",
    "not_public",
    "approval_run_mismatch",
    "approval_invalid",
    "triage_integrity_failed",
    "data_subject_integrity_failed",
    "retention_integrity_failed",
)


@dataclass(frozen=True)
class ProductionReadinessAudit:
    """Expose only aggregate readiness facts, never firms or private identities."""

    launch_counties: int
    ready_counties: int
    anomaly_counts: tuple[tuple[str, int], ...]

    @property
    def is_valid(self) -> bool:
        """Require every declared county and the private report chain to be valid."""

        return self.ready_counties == self.launch_counties and not any(
            count for _code, count in self.anomaly_counts
        )

    def as_dict(self) -> dict:
        """Return a deterministic monitoring contract without launch-area identities."""

        return {
            "schema_version": 1,
            "valid": self.is_valid,
            "launch_counties": self.launch_counties,
            "ready_counties": self.ready_counties,
            "anomalies": dict(self.anomaly_counts),
        }


def audit_production_readiness(*, counties: tuple[str, ...]) -> ProductionReadinessAudit:
    """Re-evaluate mutable publication gates for an explicit launch allowlist."""

    anomalies = dict.fromkeys(ANOMALY_CODES, 0)
    scopes = {
        scope.county: scope
        for scope in CatalogueScope.objects.filter(provider="ONRC", county__in=counties)
        .select_related(
            "current_run__snapshot",
            "current_run__refined_from_run",
            "current_run__activity_evidence_snapshot",
            "current_approval",
        )
    }
    ready = 0
    instant = timezone.now()
    for county in counties:
        scope = scopes.get(county)
        if not scope:
            anomalies["missing_scope"] += 1
            continue
        if not scope.current_run:
            anomalies["missing_run"] += 1
            continue
        if scope.current_run.county != county:
            anomalies["run_county_mismatch"] += 1
            continue
        try:
            audit_run_for_catalogue(scope.current_run)
        except ValueError:
            anomalies["run_integrity_failed"] += 1
            continue
        if scope.visibility != CatalogueScope.Visibility.PUBLIC:
            anomalies["not_public"] += 1
            continue
        if not scope.current_approval or scope.current_approval.import_run_id != scope.current_run_id:
            anomalies["approval_run_mismatch"] += 1
            continue
        if not publication_approval_is_valid(scope.current_approval, instant):
            anomalies["approval_invalid"] += 1
            continue
        ready += 1

    if not audit_public_provider_report_triage().is_valid:
        anomalies["triage_integrity_failed"] = 1
    if not audit_data_subject_requests().is_valid:
        anomalies["data_subject_integrity_failed"] = 1
    if not audit_retention_integrity().is_valid:
        anomalies["retention_integrity_failed"] = 1
    return ProductionReadinessAudit(
        launch_counties=len(counties),
        ready_counties=ready,
        anomaly_counts=tuple((code, anomalies[code]) for code in ANOMALY_CODES),
    )
