"""Deterministic pilot-scope creation without importing or publishing records."""

import hashlib
import json
from datetime import date
from pathlib import Path

from django.db import transaction

from services.caen import (
    CAEN_CATEGORY_CODES,
    CAEN_MAPPING_HASH,
    CAEN_MAPPING_VERSION,
)
from services.importers.onrc import _sha256
from services.importers.onrc_statuses import POLICY_VERSION
from services.importers.locality_aliases import RULES_PATH, sha256_file
from services.locations import read_locations_catalogue
from services.models import ImportRun, SourceSnapshot


LOCALITY_POLICY = "exact_plus_approved_hierarchy_aliases"


def available_categories() -> set[str]:
    """Return every category admitted by the versioned CAEN mapping."""

    return {
        category
        for categories in CAEN_CATEGORY_CODES.values()
        for category in categories
    }


def pilot_scope_key(
    county: str,
    categories: list[str],
) -> tuple[str, list[str]]:
    """Validate and hash every policy input that determines one pilot scope."""

    if county not in read_locations_catalogue():
        raise ValueError(f"Județ SIRUTA necunoscut: {county}")
    normalized_categories = sorted(set(categories))
    if not normalized_categories:
        raise ValueError("Pilotul necesită cel puțin o categorie")
    unknown = set(normalized_categories) - available_categories()
    if unknown:
        raise ValueError(f"Categorii necunoscute: {', '.join(sorted(unknown))}")
    contract = {
        "county": county,
        "categories": normalized_categories,
        "caen_mapping_version": CAEN_MAPPING_VERSION,
        "caen_mapping_hash": CAEN_MAPPING_HASH,
        "status_policy_version": POLICY_VERSION,
        "locality_policy": LOCALITY_POLICY,
        "locality_rules_hash": sha256_file(RULES_PATH),
    }
    rendered = json.dumps(contract, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest(), normalized_categories


def refined_scope_key(
    source_run: ImportRun,
    evidence_snapshot: SourceSnapshot,
    *,
    policy_version: str,
    policy_hash: str,
    evidence_year: int,
) -> tuple[str, list[str]]:
    """Hash the version-2 refinement without changing the legacy v1 formula."""

    _base_key, categories = pilot_scope_key(source_run.county, source_run.categories)
    if source_run.scope_contract_version != 1 or source_run.scope_key != _base_key:
        raise ValueError("Runul de bază nu respectă contractul v1")
    if evidence_snapshot.state != SourceSnapshot.State.VERIFIED:
        raise ValueError("Snapshotul dovezii de activitate nu este verificat")
    contract = {
        "scope_contract_version": 2,
        "base_run_id": source_run.pk,
        "base_scope_key": source_run.scope_key,
        "county": source_run.county,
        "categories": categories,
        "activity_evidence_snapshot_id": evidence_snapshot.pk,
        "activity_evidence_manifest_sha256": evidence_snapshot.manifest_sha256,
        "activity_evidence_policy_version": policy_version,
        "activity_evidence_policy_hash": policy_hash,
        "activity_evidence_year": evidence_year,
    }
    rendered = json.dumps(contract, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(rendered.encode()).hexdigest(), categories


@transaction.atomic
def prepare_pilot_import_run(
    manifest: dict[str, object],
    manifest_path: Path,
    verified_sources: dict[str, dict[str, object]],
    county: str,
    categories: list[str],
) -> tuple[ImportRun, bool]:
    """Create an idempotent pending run; never activate it or expose it to the UI."""

    scope_key, normalized_categories = pilot_scope_key(county, categories)
    try:
        snapshot_date = date.fromisoformat(str(manifest["snapshot_date"]))
    except (TypeError, ValueError) as error:
        raise ValueError("Data snapshotului din manifest nu este validă") from error
    snapshot, _created = SourceSnapshot.objects.get_or_create(
        provider="ONRC",
        snapshot_date=snapshot_date,
        defaults={
            "manifest_sha256": _sha256(manifest_path),
            "dataset_url": manifest["dataset_url"],
            "license_label": manifest["license"],
            "verified_resources": verified_sources,
        },
    )
    if snapshot.manifest_sha256 != _sha256(manifest_path):
        raise ValueError("Snapshotul existent are alt manifest pentru aceeași dată")
    if snapshot.state != SourceSnapshot.State.VERIFIED:
        raise ValueError("Snapshotul ONRC nu este în starea verificată")
    expected_run = {
        "county": county,
        "categories": normalized_categories,
        "caen_mapping_version": CAEN_MAPPING_VERSION,
        "caen_mapping_hash": CAEN_MAPPING_HASH,
        "status_policy_version": POLICY_VERSION,
        "locality_policy": LOCALITY_POLICY,
        "locality_rules_hash": sha256_file(RULES_PATH),
    }
    run, created = ImportRun.objects.get_or_create(
        snapshot=snapshot,
        scope_key=scope_key,
        defaults=expected_run,
    )
    if any(getattr(run, field) != value for field, value in expected_run.items()):
        raise ValueError("Runul existent nu mai corespunde contractului scope-ului")
    return run, created
