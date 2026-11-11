"""One-pass, bounded-memory ONRC import for multiple county-owned runs."""

import re
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterable

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from services.caen import (
    CAEN_MAPPING_HASH,
    CAEN_MAPPING_VERSION,
    CAEN_VERSION_LABELS,
    category_for_caen,
)
from services.importers.locality_aliases import (
    RULES_PATH,
    registered_office_match_with_approved_aliases,
    sha256_file,
)
from services.importers.onrc import (
    _flush,
    firm_fingerprint,
    load_nomenclatures,
    normalize_administrative_name,
    read_validated_rows,
)
from services.importers.onrc_pilot import (
    _record_key_hash,
    _registration_date,
    claim_import_run,
)
from services.importers.onrc_statuses import POLICY_VERSION
from services.locations import read_locations_catalogue
from services.models import (
    BusinessCaen,
    BusinessCategory,
    BusinessIdentity,
    BusinessStatus,
    ImportQuarantine,
    ImportRun,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from services.staging import LOCALITY_POLICY, pilot_scope_key


def _validated_batch_contract(
    runs: Iterable[ImportRun],
) -> tuple[list[ImportRun], list[str], dict[str, str], dict[str, set[str]]]:
    """Validate one immutable shared-source contract and canonical county ownership."""

    materialized = list(runs)
    if not materialized:
        raise ValueError("Importul multi-județ necesită cel puțin un run")
    if len({run.pk for run in materialized}) != len(materialized):
        raise ValueError("Lista conține run ID duplicat")
    if len({run.snapshot_id for run in materialized}) != 1:
        raise ValueError("Runurile multi-județ trebuie să folosească același snapshot")
    snapshot = materialized[0].snapshot
    if snapshot.provider != "ONRC" or snapshot.state != SourceSnapshot.State.VERIFIED:
        raise ValueError("Snapshotul batch trebuie să fie ONRC și verificat")

    catalog = read_locations_catalogue()
    normalized_to_canonical: dict[str, str] = {}
    target_siruta: dict[str, set[str]] = {}
    shared_categories: list[str] | None = None
    shared_policy: tuple[str, ...] | None = None
    for run in materialized:
        normalized_county = normalize_administrative_name(run.county)
        if normalized_county in normalized_to_canonical:
            raise ValueError("Batchul conține mai multe runuri pentru același județ")
        expected_scope, categories = pilot_scope_key(run.county, run.categories)
        expected = {
            "scope_key": expected_scope,
            "categories": categories,
            "caen_mapping_version": CAEN_MAPPING_VERSION,
            "caen_mapping_hash": CAEN_MAPPING_HASH,
            "status_policy_version": POLICY_VERSION,
            "locality_policy": LOCALITY_POLICY,
            "locality_rules_hash": sha256_file(RULES_PATH),
        }
        if run.snapshot_id != snapshot.pk or any(
            getattr(run, field) != value for field, value in expected.items()
        ):
            raise ValueError(f"Runul {run.pk} nu corespunde contractului batch")
        policy = tuple(str(expected[field]) for field in (
            "caen_mapping_version",
            "caen_mapping_hash",
            "status_policy_version",
            "locality_policy",
            "locality_rules_hash",
        ))
        if shared_categories is None:
            shared_categories = categories
            shared_policy = policy
        elif categories != shared_categories or policy != shared_policy:
            raise ValueError("Runurile batch nu au aceleași categorii și politici")
        normalized_to_canonical[normalized_county] = run.county
        target_siruta[run.county] = {
            code for code, _name, _label in catalog[run.county]
        }
    return materialized, shared_categories or [], normalized_to_canonical, target_siruta


def _stage_county_from_scratch(
    database: sqlite3.Connection,
    run: ImportRun,
    claim_token,
    common_counters: Counter[str],
    target_siruta: set[str],
) -> dict[str, object]:
    """Stage one county in its own transaction from the immutable shared scratch DB."""

    county = run.county
    counters = Counter(common_counters)
    for match, count in database.execute(
        "SELECT locality_match, COUNT(*) FROM target_firms "
        "WHERE target_county = ? GROUP BY locality_match",
        (county,),
    ):
        counters[f"target_{match}_firm_rows"] = count
    counters["candidate_coherent_firms"] = database.execute(
        "SELECT COUNT(*) FROM candidate_status_decisions WHERE target_county = ?",
        (county,),
    ).fetchone()[0]
    decision_counts = Counter(
        dict(
            database.execute(
                """SELECT decision, COUNT(*) FROM candidate_status_decisions
                   WHERE target_county = ? GROUP BY decision""",
                (county,),
            ).fetchall()
        )
    )
    conflicting = database.execute(
        """SELECT DISTINCT target.registration_number
           FROM target_firms AS target
           JOIN selected_activities AS activity USING (registration_number)
           JOIN conflicting_registrations AS conflict USING (registration_number)
           WHERE target.target_county = ?""",
        (county,),
    ).fetchall()
    counters["candidate_conflicting_firms"] = len(conflicting)
    eligible_count = database.execute(
        "SELECT COUNT(*) FROM eligible_registrations WHERE target_county = ?",
        (county,),
    ).fetchone()[0]
    if sum(decision_counts.values()) != counters["candidate_coherent_firms"]:
        raise ValueError(f"Deciziile de stare nu acoperă județul {county}")

    with transaction.atomic():
        run.business_snapshots.all().delete()
        run.quarantine_records.all().delete()
        ImportQuarantine.objects.bulk_create(
            [
                ImportQuarantine(
                    import_run=run,
                    resource_kind="firms",
                    reason="conflicting_payload",
                    record_key_hash=_record_key_hash(registration_number),
                    diagnostic={"scope": "approved_locality_policy_and_category"},
                )
                for (registration_number,) in conflicting
            ]
        )

        cursor = database.execute(
            """SELECT target.registration_number,
                      MIN(target.legal_name), MIN(target.cui), MIN(target.euid),
                      MIN(target.legal_form), MIN(target.registration_date),
                      MIN(target.country), MIN(target.county), MIN(target.locality),
                      MIN(target.siruta_code), MIN(target.locality_match),
                      MIN(target.registry_web), MIN(hex(target.fingerprint))
               FROM target_firms AS target
               JOIN eligible_registrations AS eligible
                 ON eligible.target_county = target.target_county
                AND eligible.registration_number = target.registration_number
               WHERE target.target_county = ?
               GROUP BY target.registration_number
               ORDER BY target.registration_number""",
            (county,),
        )
        staged = 0
        while rows := cursor.fetchmany(2_000):
            registrations = [row[0] for row in rows]
            BusinessIdentity.objects.bulk_create(
                [BusinessIdentity(registration_number=value) for value in registrations],
                ignore_conflicts=True,
            )
            identities = {
                identity.registration_number: identity
                for identity in BusinessIdentity.objects.filter(
                    registration_number__in=registrations
                )
            }
            records = RegisteredBusinessSnapshot.objects.bulk_create(
                [
                    RegisteredBusinessSnapshot(
                        import_run=run,
                        business=identities[row[0]],
                        legal_name=row[1],
                        cui=row[2],
                        euid=row[3],
                        legal_form=row[4],
                        registration_date=_registration_date(row[5]),
                        registered_country_raw=row[6],
                        registered_county_raw=row[7],
                        registered_locality_raw=row[8],
                        registered_office_siruta=row[9],
                        locality_match=row[10],
                        status_eligibility=(
                            RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE
                        ),
                        registry_web=row[11],
                        source_fingerprint=row[12].lower(),
                    )
                    for row in rows
                ]
            )
            records_by_registration = {
                record.business.registration_number: record for record in records
            }
            placeholders = ",".join("?" for _ in registrations)
            activity_rows = database.execute(
                f"""SELECT DISTINCT registration_number, version, code, category
                    FROM selected_activities
                    WHERE registration_number IN ({placeholders})""",
                registrations,
            ).fetchall()
            BusinessCaen.objects.bulk_create(
                [
                    BusinessCaen(
                        business_snapshot=records_by_registration[row[0]],
                        version=row[1],
                        code=row[2],
                    )
                    for row in activity_rows
                ],
                ignore_conflicts=True,
            )
            BusinessCategory.objects.bulk_create(
                [
                    BusinessCategory(
                        business_snapshot=records_by_registration[registration],
                        category=category,
                    )
                    for registration, category in {
                        (row[0], row[3]) for row in activity_rows
                    }
                ],
                ignore_conflicts=True,
            )
            BusinessStatus.objects.bulk_create(
                [BusinessStatus(business_snapshot=record, code="1048") for record in records]
            )
            staged += len(records)

        counters["staged_businesses"] = staged
        counters.update(
            {f"status_{decision}": count for decision, count in decision_counts.items()}
        )
        staged_queryset = RegisteredBusinessSnapshot.objects.filter(import_run=run)
        incomplete = staged_queryset.annotate(
            status_count=Count("statuses", distinct=True),
            caen_count=Count("caen_codes", distinct=True),
            category_count=Count("categories", distinct=True),
        ).filter(Q(status_count=0) | Q(caen_count=0) | Q(category_count=0)).exists()
        relation_counts = {
            "statuses": BusinessStatus.objects.filter(
                business_snapshot__import_run=run
            ).count(),
            "caen": BusinessCaen.objects.filter(
                business_snapshot__import_run=run
            ).count(),
            "categories": BusinessCategory.objects.filter(
                business_snapshot__import_run=run
            ).count(),
            "quarantine": ImportQuarantine.objects.filter(import_run=run).count(),
        }
        foreign_siruta = staged_queryset.exclude(
            registered_office_siruta__in=target_siruta
        ).exists()
        foreign_category = BusinessCategory.objects.filter(
            business_snapshot__import_run=run
        ).exclude(category__in=run.categories).exists()
        if (
            eligible_count != staged
            or relation_counts["statuses"] != staged
            or relation_counts["caen"] < staged
            or relation_counts["categories"] < staged
            or relation_counts["quarantine"] != len(conflicting)
            or incomplete
            or foreign_siruta
            or foreign_category
        ):
            raise ValueError(f"Reconcilierea staged a eșuat pentru {county}")
        counters["staged_statuses"] = relation_counts["statuses"]
        counters["staged_caen"] = relation_counts["caen"]
        counters["staged_categories"] = relation_counts["categories"]
        counters["quarantine_records"] = relation_counts["quarantine"]
        rendered = dict(sorted(counters.items()))
        completed = ImportRun.objects.filter(
            pk=run.pk,
            state=ImportRun.State.RUNNING,
            claim_token=claim_token,
        ).update(
            counters=rendered,
            state=ImportRun.State.SUCCEEDED,
            finished_at=timezone.now(),
            error_summary="",
            claim_token=None,
        )
        if not completed:
            raise ValueError(f"Claim pierdut înainte de finalizarea județului {county}")
    return rendered


def import_onrc_counties_into_staging(
    runs: Iterable[ImportRun],
    paths: dict[str, Path],
    post_scan_verify: Callable[[], None],
    scratch_dir: Path | None = None,
) -> dict[int, dict[str, object]]:
    """Scan the national bundle once, then stage each county in isolation."""

    materialized, categories, normalized_counties, target_siruta = (
        _validated_batch_contract(runs)
    )
    results: dict[int, dict[str, object]] = {}
    actionable = []
    for run in materialized:
        run.refresh_from_db()
        if run.state == ImportRun.State.SUCCEEDED:
            results[run.pk] = {
                "county": run.county,
                "changed": False,
                "state": run.state,
                "counters": run.counters,
                "error": "",
            }
        elif run.state == ImportRun.State.RUNNING:
            results[run.pk] = {
                "county": run.county,
                "changed": False,
                "state": run.state,
                "counters": run.counters,
                "error": "run_busy_requires_explicit_recovery",
            }
        else:
            actionable.append(run)
    if not actionable:
        return results

    source_bytes = sum(
        paths[kind].stat().st_size for kind in ("firms", "activities", "statuses")
    )
    scratch_root = scratch_dir or Path("/tmp")
    if shutil.disk_usage(scratch_root).free < source_bytes * 4:
        raise ValueError("Spațiu temporar insuficient pentru scratch-ul național")
    caen_codes, status_codes = load_nomenclatures(paths)
    selected_categories = set(categories)
    chunk_size = 20_000

    with TemporaryDirectory(prefix="casamea-onrc-counties-", dir=scratch_root) as scratch:
        database_path = Path(scratch) / "counties.sqlite3"
        with closing(sqlite3.connect(database_path)) as database:
            database_path.chmod(0o600)
            escaped_scratch = str(Path(scratch).resolve()).replace("'", "''")
            database.execute(f"PRAGMA temp_store_directory = '{escaped_scratch}'")
            database.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                PRAGMA temp_store = FILE;
                CREATE TABLE firm_fingerprints (
                    registration_number TEXT NOT NULL, fingerprint BLOB NOT NULL
                );
                CREATE TABLE target_firms (
                    target_county TEXT NOT NULL, registration_number TEXT NOT NULL,
                    fingerprint BLOB NOT NULL, legal_name TEXT NOT NULL,
                    cui TEXT NOT NULL, euid TEXT NOT NULL, legal_form TEXT NOT NULL,
                    registration_date TEXT NOT NULL, country TEXT NOT NULL,
                    county TEXT NOT NULL, locality TEXT NOT NULL,
                    siruta_code TEXT NOT NULL, locality_match TEXT NOT NULL,
                    registry_web TEXT NOT NULL
                );
                CREATE TABLE selected_activities (
                    registration_number TEXT NOT NULL, version TEXT NOT NULL,
                    code TEXT NOT NULL, category TEXT NOT NULL
                );
                CREATE TABLE status_rows (
                    registration_number TEXT NOT NULL, status_code TEXT NOT NULL
                );
                """
            )
            counters: Counter[str] = Counter()
            fingerprints: list[tuple] = []
            targets: list[tuple] = []
            for row in read_validated_rows(paths["firms"], "firms"):
                counters["source_firm_rows"] += 1
                registration = (row.get("COD_INMATRICULARE") or "").strip()
                if not registration or None in row or any(
                    value is None for value in row.values()
                ):
                    counters["invalid_firm_rows"] += 1
                    continue
                fingerprint = firm_fingerprint(row)
                fingerprints.append((registration, fingerprint))
                if len(fingerprints) == chunk_size:
                    _flush(database, "INSERT INTO firm_fingerprints VALUES (?, ?)", fingerprints)
                country = normalize_administrative_name(row.get("ADR_TARA") or "")
                normalized_county = normalize_administrative_name(row.get("ADR_JUDET") or "")
                canonical_county = normalized_counties.get(normalized_county)
                if country not in {"românia", "romania"} or canonical_county is None:
                    continue
                match, siruta = registered_office_match_with_approved_aliases(
                    row.get("ADR_TARA") or "",
                    row.get("ADR_JUDET") or "",
                    row.get("ADR_LOCALITATE") or "",
                )
                if match in {"exact", "hierarchy_alias"} and siruta in target_siruta[canonical_county]:
                    targets.append(
                        (
                            canonical_county, registration, fingerprint,
                            row["DENUMIRE"].strip(), row["CUI"].strip(),
                            row["EUID"].strip(), row["FORMA_JURIDICA"].strip(),
                            row["DATA_INMATRICULARE"].strip(), row["ADR_TARA"].strip(),
                            row["ADR_JUDET"].strip(), row["ADR_LOCALITATE"].strip(),
                            siruta, match, row["WEB"].strip(),
                        )
                    )
                if len(targets) == chunk_size:
                    _flush(database, "INSERT INTO target_firms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", targets)
            _flush(database, "INSERT INTO firm_fingerprints VALUES (?, ?)", fingerprints)
            _flush(database, "INSERT INTO target_firms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", targets)
            database.executescript(
                """
                CREATE INDEX batch_fingerprint_idx ON firm_fingerprints(registration_number);
                CREATE INDEX batch_target_idx ON target_firms(target_county, registration_number);
                CREATE TABLE coherent_registrations AS
                    SELECT registration_number FROM firm_fingerprints
                    GROUP BY registration_number HAVING COUNT(DISTINCT fingerprint) = 1;
                CREATE UNIQUE INDEX batch_coherent_idx ON coherent_registrations(registration_number);
                CREATE TABLE conflicting_registrations AS
                    SELECT registration_number FROM firm_fingerprints
                    GROUP BY registration_number HAVING COUNT(DISTINCT fingerprint) > 1;
                CREATE UNIQUE INDEX batch_conflict_idx ON conflicting_registrations(registration_number);
                """
            )

            activities: list[tuple] = []
            for row in read_validated_rows(paths["activities"], "activities"):
                counters["source_activity_rows"] += 1
                registration = (row.get("COD_INMATRICULARE") or "").strip()
                raw_code = (row.get("COD_CAEN_AUTORIZAT") or "").strip()
                version = (row.get("VER_CAEN_AUTORIZAT") or "").strip()
                code = raw_code.zfill(4)
                if (
                    not registration
                    or not re.fullmatch(r"\d{1,4}", raw_code)
                    or version not in CAEN_VERSION_LABELS
                    or None in row
                    or any(value is None for value in row.values())
                ):
                    counters["invalid_activity_rows"] += 1
                    continue
                if (version, code) not in caen_codes:
                    counters["unknown_caen_rows"] += 1
                    continue
                category = category_for_caen(code, version)
                if category in selected_categories:
                    activities.append((registration, version, code, category))
                if len(activities) == chunk_size:
                    _flush(database, "INSERT INTO selected_activities VALUES (?, ?, ?, ?)", activities)
            _flush(database, "INSERT INTO selected_activities VALUES (?, ?, ?, ?)", activities)

            statuses: list[tuple] = []
            for row in read_validated_rows(paths["statuses"], "statuses"):
                counters["source_status_rows"] += 1
                registration = (row.get("COD_INMATRICULARE") or "").strip()
                code = (row.get("COD") or "").strip()
                if not registration or not code or None in row or any(
                    value is None for value in row.values()
                ):
                    counters["invalid_status_rows"] += 1
                elif code not in status_codes:
                    counters["unknown_status_rows"] += 1
                else:
                    statuses.append((registration, code))
                if len(statuses) == chunk_size:
                    _flush(database, "INSERT INTO status_rows VALUES (?, ?)", statuses)
            _flush(database, "INSERT INTO status_rows VALUES (?, ?)", statuses)
            database.executescript(
                """
                CREATE INDEX batch_activity_idx ON selected_activities(registration_number);
                CREATE INDEX batch_status_idx ON status_rows(registration_number, status_code);
                CREATE TABLE candidate_registrations AS
                    SELECT DISTINCT target.target_county, target.registration_number
                    FROM target_firms AS target
                    JOIN coherent_registrations AS coherent USING (registration_number)
                    JOIN selected_activities AS activity USING (registration_number);
                CREATE UNIQUE INDEX batch_candidate_idx
                    ON candidate_registrations(target_county, registration_number);
                CREATE TABLE candidate_status_decisions AS
                    SELECT candidate.target_county, candidate.registration_number,
                           COUNT(DISTINCT status.status_code) AS status_count,
                           MAX(CASE WHEN status.status_code = '1048' THEN 1 ELSE 0 END) AS has_1048,
                           MAX(CASE WHEN status.status_code = '1084' THEN 1 ELSE 0 END) AS has_1084,
                           CASE
                             WHEN MAX(CASE WHEN status.status_code = '1084' THEN 1 ELSE 0 END) = 1
                               THEN 'excluded_radiated'
                             WHEN COUNT(DISTINCT status.status_code) = 1
                              AND MAX(CASE WHEN status.status_code = '1048' THEN 1 ELSE 0 END) = 1
                               THEN 'eligible_function_only'
                             WHEN MAX(CASE WHEN status.status_code = '1048' THEN 1 ELSE 0 END) = 1
                               THEN 'needs_review_mixed_function'
                             ELSE 'quarantined_without_function'
                           END AS decision
                    FROM candidate_registrations AS candidate
                    LEFT JOIN status_rows AS status USING (registration_number)
                    GROUP BY candidate.target_county, candidate.registration_number;
                CREATE UNIQUE INDEX batch_decision_idx
                    ON candidate_status_decisions(target_county, registration_number);
                CREATE TABLE eligible_registrations AS
                    SELECT target_county, registration_number
                    FROM candidate_status_decisions
                    WHERE status_count = 1 AND has_1048 = 1;
                CREATE UNIQUE INDEX batch_eligible_idx
                    ON eligible_registrations(target_county, registration_number);
                """
            )
            counters["scratch_database_bytes"] = database_path.stat().st_size

            post_scan_verify()
            refreshed = list(
                ImportRun.objects.select_related("snapshot").filter(
                    pk__in=[run.pk for run in materialized]
                )
            )
            refreshed, _, _, refreshed_siruta = _validated_batch_contract(refreshed)
            refreshed_by_id = {run.pk: run for run in refreshed}
            if shutil.disk_usage(scratch_root).free < database_path.stat().st_size // 2:
                raise ValueError("Spațiu temporar insuficient înainte de staging")

            for original in materialized:
                if original.pk in results:
                    continue
                run = refreshed_by_id[original.pk]
                token = None
                try:
                    token = claim_import_run(run)
                    if token is None:
                        run.refresh_from_db()
                        results[run.pk] = {
                            "county": run.county,
                            "changed": False,
                            "state": run.state,
                            "counters": run.counters,
                            "error": "",
                        }
                        continue
                    run.refresh_from_db()
                    _validated_batch_contract([run])
                    rendered = _stage_county_from_scratch(
                        database, run, token, counters, refreshed_siruta[run.county]
                    )
                    results[run.pk] = {
                        "county": run.county,
                        "changed": True,
                        "state": ImportRun.State.SUCCEEDED,
                        "counters": rendered,
                        "error": "",
                    }
                except Exception as error:
                    if token is not None:
                        ImportRun.objects.filter(
                            pk=run.pk,
                            state=ImportRun.State.RUNNING,
                            claim_token=token,
                        ).update(
                            state=ImportRun.State.FAILED,
                            finished_at=timezone.now(),
                            error_summary=f"{type(error).__name__}: {error}"[:1000],
                            claim_token=None,
                        )
                    run.refresh_from_db()
                    actual_error = (
                        ""
                        if run.state == ImportRun.State.SUCCEEDED
                        else "run_busy_requires_explicit_recovery"
                        if run.state == ImportRun.State.RUNNING
                        else f"{type(error).__name__}: {error}"
                    )
                    results[run.pk] = {
                        "county": run.county,
                        "changed": False,
                        "state": run.state,
                        "counters": run.counters,
                        "error": actual_error,
                    }
                finally:
                    token = None
    return results
