"""Audit MF 2024 predominant-activity evidence before catalogue refinement."""

import csv
import hashlib
import json
import os
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from services.caen import category_for_caen
from services.importers.onrc import _sha256
from services.models import (
    BusinessCaen,
    BusinessCategory,
    BusinessStatus,
    CatalogueScope,
    ImportRun,
    PrimaryActivityEvidence,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from services.staging import refined_scope_key


POLICY_NAME = "mf_2024_reported_predominant_activity"
POLICY_VERSION = "1"
REPORTING_YEAR = 2024
CAEN_VERSION = "2"
RESOURCE_KINDS = {
    "data_bl_bs_sl", "schema_bl_bs_sl", "data_uu", "schema_uu",
}
MF_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "mf" / "manifest-primary-caen-2024.json"
POLICY_CONTRACT = {
    "name": POLICY_NAME,
    "version": POLICY_VERSION,
    "reporting_year": REPORTING_YEAR,
    "caen_version": CAEN_VERSION,
    "join": "normalized_numeric_cui_exact",
    "decision": (
        "exactly_one_known_reported_caen_mapped_to_scope_category_and_"
        "reconciled_with_authorized_onrc_category"
    ),
    "missing_evidence": "exclude_from_refined_preview",
}
POLICY_HASH = hashlib.sha256(
    json.dumps(POLICY_CONTRACT, separators=(",", ":"), sort_keys=True).encode()
).hexdigest()


def normalize_cui(value: str) -> str:
    """Return the canonical numeric CUI, or an empty string for unsafe values."""

    normalized = value.strip()
    return str(int(normalized)) if normalized.isdigit() and int(normalized) else ""


def registration_year(date_value, registration_number: str) -> str:
    """Return a known registration year, falling back to the official number."""

    if date_value:
        return str(date_value.year)
    compact_year = registration_number[1:5]
    if (
        len(registration_number) >= 5
        and registration_number[:1].isalpha()
        and compact_year.isdigit()
        and 1900 <= int(compact_year) <= 2100
    ):
        return compact_year
    suffix = registration_number.rsplit("/", 1)[-1].strip()
    return suffix if len(suffix) == 4 and suffix.isdigit() else "unknown"


def classify_primary_activity(
    *, cui: str, duplicate_onrc_cui: bool, conflicting_mf: bool,
    caen: str | None, known_caen_v2: set[str],
) -> tuple[str, str]:
    """Classify one join outcome and return its sole derived category, if any."""

    if not cui:
        return "missing_or_invalid_onrc_cui", ""
    if duplicate_onrc_cui:
        return "duplicate_onrc_cui", ""
    if conflicting_mf:
        return "conflicting_mf_activity", ""
    if caen is None:
        return "no_mf_2024_filing", ""
    if caen not in known_caen_v2:
        return "unknown_caen_v2", ""
    category = category_for_caen(caen, CAEN_VERSION)
    return (
        ("mapped_include", category)
        if category
        else ("unmapped_reported_activity", "")
    )


def _read_schema_columns(path: Path, delimiter: str) -> list[str]:
    """Read ordered machine-column names from one MF schema artifact."""

    columns = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        for line_number, row in enumerate(reader, start=1):
            if len(row) != 2 or not row[1].strip():
                raise ValueError(f"Schemă MF invalidă la {path.name}:{line_number}")
            columns.append(row[1].strip().upper())
    return columns


def verify_primary_activity_manifest(
    manifest_path: Path, input_dir: Path
) -> tuple[dict[str, object], dict[str, Path], str]:
    """Verify all data/schema resources and parser metadata before reading."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = manifest.get("parser_contract", {})
    try:
        datetime.fromisoformat(str(manifest["retrieved_at"]))
    except (KeyError, ValueError) as error:
        raise ValueError("Data preluării MF nu este ISO validă") from error
    if (
        manifest.get("schema_version") != 1
        or manifest.get("provider") != "Ministerul Finanțelor"
        or manifest.get("dataset_year") != REPORTING_YEAR
        or manifest.get("license") != "CC BY 4.0"
        or not str(manifest.get("dataset_url", "")).startswith("https://")
        or not str(manifest.get("semantic_basis", {}).get("url", "")).startswith("https://")
        or manifest.get("semantic_basis", {}).get("meaning") != POLICY_NAME
        or contract.get("meaning") != POLICY_NAME
        or contract.get("caen_version") != CAEN_VERSION
        or contract.get("encoding") != "utf-8-sig"
        or contract.get("data_delimiter") != ","
        or contract.get("schema_delimiter") != ";"
        or contract.get("required_leading_columns") != ["CUI", "CAEN"]
    ):
        raise ValueError("Manifestul MF nu respectă politica de activitate raportată")
    resources = manifest.get("resources", [])
    if (
        not isinstance(resources, list)
        or len(resources) != 4
        or not all(isinstance(item, dict) for item in resources)
        or len({item.get("kind") for item in resources}) != 4
        or {
        item.get("kind") for item in resources if isinstance(item, dict)
        } != RESOURCE_KINDS
        or any(not str(item.get("url", "")).startswith("https://") for item in resources)
    ):
        raise ValueError("Manifestul MF trebuie să fixeze exact două date și două scheme")

    paths: dict[str, Path] = {}
    verified = []
    for resource in resources:
        kind = str(resource["kind"])
        filename = Path(str(resource["filename"]))
        if filename.name != str(filename):
            raise ValueError("Manifestul MF conține o cale nesigură")
        path = input_dir / filename
        if (
            path.stat().st_size != int(resource["size_bytes"])
            or _sha256(path) != resource["sha256"]
        ):
            raise ValueError(f"Hash sau dimensiune MF invalidă: {path.name}")
        paths[kind] = path
        verified.append({
            "kind": kind,
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": resource["sha256"],
        })

    for suffix in ("bl_bs_sl", "uu"):
        schema_columns = _read_schema_columns(
            paths[f"schema_{suffix}"], str(contract["schema_delimiter"])
        )
        with paths[f"data_{suffix}"].open(
            "r", encoding=str(contract["encoding"]), newline=""
        ) as source:
            header = next(csv.reader(
                source, delimiter=str(contract["data_delimiter"]), strict=True
            ))
        if [column.upper() for column in header] != schema_columns:
            raise ValueError(f"Headerul de date nu corespunde schemei MF: {suffix}")
        if schema_columns[:2] != ["CUI", "CAEN"]:
            raise ValueError(f"Schema MF nu începe cu CUI, CAEN: {suffix}")

    manifest_hash = _sha256(manifest_path)
    evidence_hash = hashlib.sha256(json.dumps(
        {"manifest_sha256": manifest_hash, "resources": verified},
        separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()
    return manifest, paths, evidence_hash


def load_known_caen_v2(path: Path, expected_sha256: str) -> set[str]:
    """Load authoritative version-2 classes pinned by the ONRC manifest."""

    if _sha256(path) != expected_sha256:
        raise ValueError("Nomenclatorul CAEN nu corespunde manifestului ONRC")
    known: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(
            source, delimiter="^", quoting=csv.QUOTE_NONE, strict=True
        )
        expected = {
            "SECTIUNEA", "SUBSECTIUNEA", "DIVIZIUNEA", "GRUPA", "CLASA",
            "DENUMIRE", "VERSIUNE_CAEN",
        }
        if set(reader.fieldnames or []) != expected:
            raise ValueError("Header CAEN neașteptat")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Rând structural invalid în nomenclatorul CAEN")
            if row["VERSIUNE_CAEN"].strip() == CAEN_VERSION:
                raw_code = row["CLASA"].strip()
                # N_CAEN also contains section/division/group rows. Only four-digit
                # class rows are admissible as company activity evidence.
                if not (raw_code.isdigit() and len(raw_code) == 4):
                    continue
                code = raw_code
                known.add(code)
    if not known:
        raise ValueError("Nomenclatorul CAEN v2 este gol")
    return known


def build_primary_activity_index(
    paths: dict[str, Path], scratch_dir: Path
) -> tuple[Path, Counter]:
    """Build a disk-backed CUI→reported-CAEN index with conflict accounting."""

    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.chmod(0o700)
    database_path = scratch_dir / "mf-2024-shadow.sqlite3"
    if database_path.exists():
        database_path.unlink()
    database = sqlite3.connect(database_path)
    database_path.chmod(0o600)
    counters = Counter()
    try:
        database.execute(
            "CREATE TABLE evidence (cui TEXT NOT NULL, caen TEXT NOT NULL, "
            "resource TEXT NOT NULL, fingerprint TEXT NOT NULL)"
        )
        batch = []
        for kind in ("data_bl_bs_sl", "data_uu"):
            path = paths[kind]
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, delimiter=",", strict=True)
                if [item.upper() for item in (reader.fieldnames or [])[:2]] != ["CUI", "CAEN"]:
                    raise ValueError(f"Header MF neașteptat: {path.name}")
                for row in reader:
                    counters["source_rows"] += 1
                    raw_cui = row.get("CUI") or row.get("cui") or ""
                    raw_caen = row.get("CAEN") or row.get("caen") or ""
                    cui = normalize_cui(raw_cui)
                    caen_value = raw_caen.strip()
                    if (
                        None in row
                        or any(value is None for value in row.values())
                        or not cui
                        or not caen_value.isdigit()
                        or not 1 <= len(caen_value) <= 4
                    ):
                        counters["malformed_rows"] += 1
                        continue
                    caen = caen_value.zfill(4)
                    fingerprint = hashlib.sha256(
                        f"{kind}\0{cui}\0{caen}".encode()
                    ).hexdigest()
                    batch.append((cui, caen, kind, fingerprint))
                    if len(batch) >= 20_000:
                        database.executemany("INSERT INTO evidence VALUES (?, ?, ?, ?)", batch)
                        batch.clear()
        database.executemany("INSERT INTO evidence VALUES (?, ?, ?, ?)", batch)
        database.executescript(
            """
            CREATE INDEX evidence_cui_idx ON evidence(cui);
            CREATE TABLE primary_activity AS
              WITH grouped AS (
                SELECT cui, MIN(caen) AS caen, MIN(resource) AS resource,
                       COUNT(*) AS raw_rows
                FROM evidence GROUP BY cui HAVING COUNT(DISTINCT caen) = 1
              )
              SELECT g.cui, g.caen, g.resource, MIN(e.fingerprint) AS fingerprint,
                     g.raw_rows
              FROM grouped g JOIN evidence e
                ON e.cui=g.cui AND e.resource=g.resource
              GROUP BY g.cui, g.caen, g.resource, g.raw_rows;
            CREATE UNIQUE INDEX primary_activity_cui_idx ON primary_activity(cui);
            CREATE TABLE conflicting_activity AS
              SELECT cui, COUNT(DISTINCT caen) AS caen_count
              FROM evidence GROUP BY cui HAVING COUNT(DISTINCT caen) > 1;
            CREATE UNIQUE INDEX conflicting_activity_cui_idx ON conflicting_activity(cui);
            """
        )
        counters["accepted_rows"] = database.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        counters["unique_cui"] = database.execute("SELECT COUNT(*) FROM primary_activity").fetchone()[0]
        counters["conflicting_cui"] = database.execute("SELECT COUNT(*) FROM conflicting_activity").fetchone()[0]
        counters["identical_duplicate_rows"] = database.execute(
            "SELECT COALESCE(SUM(raw_rows - 1), 0) FROM primary_activity"
        ).fetchone()[0]
        database.commit()
    finally:
        database.close()
    return database_path, counters


def audit_active_catalogue_against_primary_activity(
    database_path: Path,
    known_caen_v2: set[str],
    expected_onrc_manifest_sha256: str,
    base_runs: list[ImportRun] | None = None,
) -> dict[str, object]:
    """Partition every selected base candidate without changing catalogue state.

    Explicit base runs allow building a replacement catalogue without temporarily
    exposing the broader authorized-activity catalogue through active pointers.
    """

    active_pointer_mode = base_runs is None
    scopes = (
        list(
            CatalogueScope.objects.select_related("current_run__snapshot")
            .filter(provider="ONRC", current_run__isnull=False).order_by("county")
        )
        if active_pointer_mode
        else []
    )
    selected_runs = (
        [scope.current_run for scope in scopes]
        if active_pointer_mode
        else sorted(base_runs or [], key=lambda run: run.county)
    )
    if len(selected_runs) != 42:
        source = "pointere județene active" if active_pointer_mode else "runuri de bază"
        raise ValueError(f"Auditul necesită exact cele 42 de {source}")
    from services.catalogue_activation import audit_run_for_catalogue

    expected_categories = {
        "constructii", "instalatii", "gradinarit", "curatenie", "tamplarie",
        "reparatii",
    }
    run_ids = [run.pk for run in selected_runs]
    snapshot_ids = {run.snapshot_id for run in selected_runs}
    counties = [run.county for run in selected_runs]
    if (
        len(run_ids) != len(set(run_ids))
        or len(counties) != len(set(counties))
        or len(snapshot_ids) != 1
    ):
        raise ValueError("Runurile de bază nu au identități/snapshot ONRC comune")
    for run in selected_runs:
        if (
            run.snapshot.provider != "ONRC"
            or run.snapshot.manifest_sha256 != expected_onrc_manifest_sha256
            or set(run.categories) != expected_categories
        ):
            raise ValueError(f"Proveniența ONRC diferă pentru {run.county}")
        audit_run_for_catalogue(run)

    if active_pointer_mode:
        for scope in scopes:
            run = scope.current_run
            if (
                run is None
                or run.state != "succeeded"
                or scope.visibility != CatalogueScope.Visibility.INTERNAL_PREVIEW
                or scope.current_approval_id is not None
                or run.county != scope.county
            ):
                raise ValueError(f"Pointerul {scope.county} nu are un run finalizat")

    database = sqlite3.connect(database_path)
    try:
        database.executescript(
            """
            CREATE TABLE candidate (
              id INTEGER PRIMARY KEY, county TEXT NOT NULL, cui TEXT NOT NULL,
              registration_key TEXT NOT NULL, legal_form TEXT NOT NULL,
              registration_year TEXT NOT NULL);
            CREATE INDEX candidate_cui_idx ON candidate(cui);
            CREATE TABLE candidate_category (
              candidate_id INTEGER NOT NULL, category TEXT NOT NULL,
              PRIMARY KEY(candidate_id, category));
            CREATE TABLE candidate_caen (
              candidate_id INTEGER NOT NULL, version TEXT NOT NULL, code TEXT NOT NULL,
              PRIMARY KEY(candidate_id, version, code));
            CREATE TABLE candidate_decision (
              candidate_id INTEGER PRIMARY KEY, decision TEXT NOT NULL,
              caen TEXT NOT NULL, category TEXT NOT NULL,
              resource TEXT NOT NULL, source_fingerprint TEXT NOT NULL);
            """
        )
        base_run_report = []
        run_ids = []
        for run in selected_runs:
            if (
                run.state != "succeeded"
                or run.scope_contract_version != 1
            ):
                raise ValueError(f"Runul {run.county} nu este o bază v1 finalizată")
            run_ids.append(run.pk)
            base_run_report.append({
                "county": run.county, "run_id": run.pk, "scope_key": run.scope_key,
            })
            rows = RegisteredBusinessSnapshot.objects.staging_candidates(run).values_list(
                "id", "cui", "business_id", "business__registration_number",
                "legal_form", "registration_date"
            ).iterator(chunk_size=5_000)
            database.executemany(
                "INSERT INTO candidate VALUES (?, ?, ?, ?, ?, ?)",
                ((
                    row_id, run.county, normalize_cui(cui), str(business_id),
                    legal_form, registration_year(registration_date, registration_number),
                ) for row_id, cui, business_id, registration_number, legal_form, registration_date in rows),
            )
        database.executemany(
            "INSERT INTO candidate_category VALUES (?, ?)",
            BusinessCategory.objects.filter(
                business_snapshot__import_run_id__in=run_ids
            ).values_list("business_snapshot_id", "category").iterator(chunk_size=10_000),
        )
        database.executemany(
            "INSERT INTO candidate_caen VALUES (?, ?, ?)",
            BusinessCaen.objects.filter(
                business_snapshot__import_run_id__in=run_ids
            ).values_list("business_snapshot_id", "version", "code").iterator(chunk_size=10_000),
        )
        database.executescript(
            """
            CREATE INDEX candidate_caen_id_idx ON candidate_caen(candidate_id);
            CREATE TABLE duplicate_onrc_cui AS
              SELECT cui FROM candidate WHERE cui <> '' GROUP BY cui
              HAVING COUNT(DISTINCT registration_key) > 1;
            CREATE UNIQUE INDEX duplicate_onrc_cui_idx ON duplicate_onrc_cui(cui);
            """
        )

        decisions = Counter()
        by_county: dict[str, Counter] = {}
        by_category_base = Counter(dict(database.execute(
            "SELECT category, COUNT(*) FROM candidate_category GROUP BY category"
        )))
        by_category_included = Counter()
        by_legal_form: dict[str, Counter] = {}
        by_year: dict[str, Counter] = {}
        reconciliation = Counter()
        records = database.execute(
            """
            SELECT c.id, c.county, c.cui, c.legal_form, c.registration_year,
                   p.caen, x.cui IS NOT NULL, d.cui IS NOT NULL
            FROM candidate c
            LEFT JOIN primary_activity p ON p.cui=c.cui
            LEFT JOIN conflicting_activity x ON x.cui=c.cui
            LEFT JOIN duplicate_onrc_cui d ON d.cui=c.cui ORDER BY c.id
            """
        )
        for candidate_id, county, cui, legal_form, year, caen, conflict, duplicate in records:
            decision, category = classify_primary_activity(
                cui=cui,
                duplicate_onrc_cui=bool(duplicate),
                conflicting_mf=bool(conflict),
                caen=caen,
                known_caen_v2=known_caen_v2,
            )
            if category:
                authorized = database.execute(
                    "SELECT version, code FROM candidate_caen WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchall()
                if (CAEN_VERSION, caen) in authorized:
                    reconciliation["exact_authorized_v2"] += 1
                elif any(category_for_caen(code, version) == category for version, code in authorized):
                    reconciliation["same_curated_category"] += 1
                else:
                    reconciliation["not_reconciled_to_authorized_home_caen"] += 1
                    decision = "mapped_but_not_authorized"
                    category = ""
            if category:
                by_category_included[category] += 1
            evidence_row = database.execute(
                "SELECT resource, fingerprint FROM primary_activity WHERE cui=?",
                (cui,),
            ).fetchone()
            database.execute(
                "INSERT INTO candidate_decision VALUES (?, ?, ?, ?, ?, ?)",
                (
                    candidate_id,
                    decision,
                    caen or "",
                    category,
                    evidence_row[0] if evidence_row else "",
                    evidence_row[1] if evidence_row else "",
                ),
            )
            decisions[decision] += 1
            by_county.setdefault(county, Counter())[decision] += 1
            by_legal_form.setdefault(legal_form or "unknown", Counter())[decision] += 1
            by_year.setdefault(year, Counter())[decision] += 1

        total = database.execute("SELECT COUNT(*) FROM candidate").fetchone()[0]
        if sum(decisions.values()) != total:
            raise ValueError("Partiția auditului MF nu se închide")
        report = {
            "report_schema_version": 1,
            "policy": dict(POLICY_CONTRACT, sha256=POLICY_HASH),
            "base_runs": base_run_report,
            "base_provenance": {
                "provider": "ONRC",
                "snapshot_ids": sorted({run.snapshot_id for run in selected_runs}),
                "snapshot_manifest_sha256": sorted({
                    run.snapshot.manifest_sha256 for run in selected_runs
                }),
                "scope_contract_versions": sorted({
                    run.scope_contract_version for run in selected_runs
                }),
                "categories": sorted({
                    category for run in selected_runs for category in run.categories
                }),
                "visibility": (
                    "internal_preview" if active_pointer_mode else "not_activated"
                ),
                "publication_approval_count": 0,
            },
            "base_candidates": total,
            "decision_counts": dict(sorted(decisions.items())),
            "retention_percent": round(100 * decisions["mapped_include"] / total, 3),
            "category_relations_before": dict(sorted(by_category_base.items())),
            "included_primary_category": dict(sorted(by_category_included.items())),
            "caen_authorization_reconciliation": dict(sorted(reconciliation.items())),
            "by_county": {key: dict(sorted(value.items())) for key, value in sorted(by_county.items())},
            "by_legal_form": {key: dict(sorted(value.items())) for key, value in sorted(by_legal_form.items())},
            "by_registration_year": {key: dict(sorted(value.items())) for key, value in sorted(by_year.items())},
            "scratch_bytes": os.path.getsize(database_path),
            "catalogue_mutated": False,
            "zero_buckets": {
                key: decisions.get(key, 0)
                for key in (
                    "missing_or_invalid_onrc_cui", "duplicate_onrc_cui",
                    "conflicting_mf_activity", "unknown_caen_v2",
                )
            },
        }
        database.commit()
        return report
    finally:
        database.close()


@transaction.atomic
def prepare_refinement_runs(
    *, manifest: dict[str, object], manifest_sha256: str,
    verified_resources: dict[str, object], base_runs: list[ImportRun],
) -> tuple[SourceSnapshot, list[ImportRun]]:
    """Create the verified MF snapshot and idempotent v2 county runs."""

    evidence_snapshot, _created = SourceSnapshot.objects.get_or_create(
        provider="MF_FINANCIAL_STATEMENTS_2024",
        snapshot_date="2024-12-31",
        defaults={
            "manifest_sha256": manifest_sha256,
            "dataset_url": manifest["dataset_url"],
            "license_label": manifest["license"],
            "verified_resources": verified_resources,
        },
    )
    if (
        evidence_snapshot.state != SourceSnapshot.State.VERIFIED
        or evidence_snapshot.manifest_sha256 != manifest_sha256
        or evidence_snapshot.verified_resources != verified_resources
    ):
        raise ValueError("Snapshotul MF existent nu corespunde manifestului verificat")
    runs = []
    for source_run in sorted(base_runs, key=lambda item: item.county):
        scope_key, categories = refined_scope_key(
            source_run,
            evidence_snapshot,
            policy_version=POLICY_VERSION,
            policy_hash=POLICY_HASH,
            evidence_year=REPORTING_YEAR,
        )
        expected = {
            "county": source_run.county,
            "categories": categories,
            "caen_mapping_version": source_run.caen_mapping_version,
            "caen_mapping_hash": source_run.caen_mapping_hash,
            "status_policy_version": source_run.status_policy_version,
            "locality_policy": source_run.locality_policy,
            "locality_rules_hash": source_run.locality_rules_hash,
            "scope_contract_version": 2,
            "refined_from_run": source_run,
            "activity_evidence_snapshot": evidence_snapshot,
            "activity_evidence_policy_version": POLICY_VERSION,
            "activity_evidence_policy_hash": POLICY_HASH,
            "activity_evidence_year": REPORTING_YEAR,
        }
        run, _created = ImportRun.objects.get_or_create(
            snapshot=source_run.snapshot, scope_key=scope_key, defaults=expected
        )
        if any(getattr(run, field) != value for field, value in expected.items()):
            raise ValueError(f"Runul v2 existent are provenance drift: {source_run.county}")
        runs.append(run)
    return evidence_snapshot, runs


def _claim_refinement_run(run: ImportRun) -> uuid.UUID | None:
    """Claim one pending/failed v2 run with compare-and-swap semantics."""

    run.refresh_from_db()
    if run.state == ImportRun.State.SUCCEEDED:
        return None
    token = uuid.uuid4()
    claimed = ImportRun.objects.filter(
        pk=run.pk, state__in=(ImportRun.State.PENDING, ImportRun.State.FAILED)
    ).update(
        state=ImportRun.State.RUNNING,
        claim_token=token,
        attempt_count=F("attempt_count") + 1,
        started_at=timezone.now(),
        finished_at=None,
        error_summary="",
    )
    if not claimed:
        raise ValueError(f"Runul {run.pk} este deja revendicat")
    return token


def refine_run_from_shadow_index(
    source_run: ImportRun, target_run: ImportRun, database_path: Path
) -> tuple[dict[str, int], bool]:
    """Clone only mapped, authorized, reported-predominant service candidates."""

    expected_key, _categories = refined_scope_key(
        source_run,
        target_run.activity_evidence_snapshot,
        policy_version=target_run.activity_evidence_policy_version,
        policy_hash=target_run.activity_evidence_policy_hash,
        evidence_year=target_run.activity_evidence_year,
    )
    if target_run.scope_key != expected_key or target_run.refined_from_run_id != source_run.pk:
        raise ValueError("Contractul runului rafinat nu corespunde sursei")
    token = _claim_refinement_run(target_run)
    if token is None:
        target_run.refresh_from_db()
        return target_run.counters, False
    try:
        with sqlite3.connect(database_path) as database, transaction.atomic():
            target_run.business_snapshots.all().delete()
            target_run.quarantine_records.all().delete()
            counters = Counter(dict(database.execute(
                """
                SELECT decision, COUNT(*) FROM candidate_decision d
                JOIN candidate c ON c.id=d.candidate_id
                WHERE c.county=? GROUP BY decision
                """,
                (source_run.county,),
            )))
            source_rows = RegisteredBusinessSnapshot.objects.staging_candidates(
                source_run
            ).prefetch_related("caen_codes").order_by("pk")
            for offset in range(0, source_rows.count(), 1_000):
                chunk = list(source_rows[offset : offset + 1_000])
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                evidence = {
                    row[0]: row[1:]
                    for row in database.execute(
                        f"""
                        SELECT candidate_id, caen, category, resource, source_fingerprint
                        FROM candidate_decision
                        WHERE decision='mapped_include'
                          AND candidate_id IN ({placeholders})
                        """,
                        [item.pk for item in chunk],
                    )
                }
                selected = [(item, evidence[item.pk]) for item in chunk if item.pk in evidence]
                created = RegisteredBusinessSnapshot.objects.bulk_create([
                    RegisteredBusinessSnapshot(
                        import_run=target_run,
                        business=source.business,
                        legal_name=source.legal_name,
                        cui=source.cui,
                        euid=source.euid,
                        legal_form=source.legal_form,
                        registration_date=source.registration_date,
                        registered_country_raw=source.registered_country_raw,
                        registered_county_raw=source.registered_county_raw,
                        registered_locality_raw=source.registered_locality_raw,
                        registered_office_siruta=source.registered_office_siruta,
                        locality_match=source.locality_match,
                        status_eligibility=source.status_eligibility,
                        registry_web=source.registry_web,
                        source_fingerprint=source.source_fingerprint,
                    )
                    for source, _evidence in selected
                ])
                BusinessStatus.objects.bulk_create([
                    BusinessStatus(business_snapshot=record, code="1048")
                    for record in created
                ])
                BusinessCategory.objects.bulk_create([
                    BusinessCategory(business_snapshot=record, category=evidence_values[1])
                    for record, (_source, evidence_values) in zip(created, selected)
                ])
                PrimaryActivityEvidence.objects.bulk_create([
                    PrimaryActivityEvidence(
                        business_snapshot=record,
                        resource_kind=evidence_values[2],
                        cui_join_fingerprint=hashlib.sha256(
                            normalize_cui(source.cui).encode()
                        ).hexdigest(),
                        caen_version=CAEN_VERSION,
                        caen_code=evidence_values[0],
                        reporting_year=REPORTING_YEAR,
                        source_row_fingerprint=evidence_values[3],
                    )
                    for record, (source, evidence_values) in zip(created, selected)
                ])
                BusinessCaen.objects.bulk_create([
                    BusinessCaen(
                        business_snapshot=record, version=activity.version, code=activity.code
                    )
                    for record, (source, _evidence) in zip(created, selected)
                    for activity in source.caen_codes.all()
                ])
                counters["staged_businesses"] += len(created)

            staged = target_run.business_snapshots.count()
            counters.update({
                "staged_statuses": BusinessStatus.objects.filter(
                    business_snapshot__import_run=target_run
                ).count(),
                "staged_caen": BusinessCaen.objects.filter(
                    business_snapshot__import_run=target_run
                ).count(),
                "staged_categories": BusinessCategory.objects.filter(
                    business_snapshot__import_run=target_run
                ).count(),
                "staged_activity_evidence": PrimaryActivityEvidence.objects.filter(
                    business_snapshot__import_run=target_run
                ).count(),
                "quarantine_records": 0,
            })
            base_count = sum(
                value for key, value in counters.items()
                if key in {
                    "mapped_include", "mapped_but_not_authorized",
                    "no_mf_2024_filing", "unmapped_reported_activity",
                    "missing_or_invalid_onrc_cui", "duplicate_onrc_cui",
                    "conflicting_mf_activity", "unknown_caen_v2",
                }
            )
            if (
                base_count != source_rows.count()
                or staged != counters["mapped_include"]
                or any(counters[key] != staged for key in (
                    "staged_businesses", "staged_statuses", "staged_categories",
                    "staged_activity_evidence",
                ))
                or counters["staged_caen"] < staged
            ):
                raise ValueError(
                    "Reconcilierea runului rafinat nu se închide: "
                    f"base={base_count}/{source_rows.count()}, staged={staged}, "
                    f"mapped={counters['mapped_include']}, "
                    f"statuses={counters['staged_statuses']}, "
                    f"categories={counters['staged_categories']}, "
                    f"evidence={counters['staged_activity_evidence']}, "
                    f"caen={counters['staged_caen']}"
                )
            rendered = dict(sorted(counters.items()))
            completed = ImportRun.objects.filter(
                pk=target_run.pk,
                state=ImportRun.State.RUNNING,
                claim_token=token,
            ).update(
                state=ImportRun.State.SUCCEEDED,
                claim_token=None,
                counters=rendered,
                error_summary="",
                finished_at=timezone.now(),
            )
            if not completed:
                raise ValueError("Claim pierdut la finalizarea runului rafinat")
        return rendered, True
    except Exception as error:
        ImportRun.objects.filter(
            pk=target_run.pk,
            state=ImportRun.State.RUNNING,
            claim_token=token,
        ).update(
            state=ImportRun.State.FAILED,
            claim_token=None,
            error_summary=str(error)[:1_000],
            finished_at=timezone.now(),
        )
        raise
