"""Bounded-memory import of one approved-locality, status-eligible ONRC pilot."""

import hashlib
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from services.caen import (
    CAEN_MAPPING_HASH,
    CAEN_MAPPING_VERSION,
    CAEN_VERSION_LABELS,
    category_for_caen,
)
from services.importers.onrc import (
    _flush,
    firm_fingerprint,
    load_nomenclatures,
    normalize_administrative_name,
    read_validated_rows,
)
from services.importers.onrc_statuses import POLICY_VERSION, proposed_status_decision
from services.importers.locality_aliases import (
    RULES_PATH,
    registered_office_match_with_approved_aliases,
    sha256_file,
)
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


def _registration_date(value: str):
    """Parse the known ONRC date variants, leaving unusable dates empty."""

    normalized = value.strip()
    for date_format in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    return None


def _record_key_hash(registration_number: str) -> str:
    """Hash a registry key before it enters privacy-minimized quarantine."""

    return hashlib.sha256(registration_number.encode("utf-8")).hexdigest()


def claim_import_run(run: ImportRun) -> uuid.UUID | None:
    """Atomically claim a pending/failed run; return None for a completed no-op."""

    claim_token = uuid.uuid4()
    claimed = ImportRun.objects.filter(
        pk=run.pk, state__in=(ImportRun.State.PENDING, ImportRun.State.FAILED)
    ).update(
        state=ImportRun.State.RUNNING,
        attempt_count=F("attempt_count") + 1,
        claim_token=claim_token,
        started_at=timezone.now(),
        finished_at=None,
        error_summary="",
    )
    if claimed:
        return claim_token
    run.refresh_from_db()
    if run.state == ImportRun.State.SUCCEEDED:
        return None
    raise ValueError("Runul este deja în curs sau nu poate fi revendicat")


def import_onrc_pilot_into_staging(
    run: ImportRun,
    paths: dict[str, Path],
    scratch_dir: Path | None = None,
) -> tuple[dict[str, object], bool]:
    """Build and atomically stage one run; a succeeded rerun is a no-op."""

    if run.snapshot.state != SourceSnapshot.State.VERIFIED:
        raise ValueError("Snapshotul sursă nu este verificat")

    expected_scope_key, canonical_categories = pilot_scope_key(
        run.county, run.categories
    )
    expected_contract = {
        "scope_key": expected_scope_key,
        "categories": canonical_categories,
        "caen_mapping_version": CAEN_MAPPING_VERSION,
        "caen_mapping_hash": CAEN_MAPPING_HASH,
        "status_policy_version": POLICY_VERSION,
        "locality_policy": LOCALITY_POLICY,
        "locality_rules_hash": sha256_file(RULES_PATH),
    }
    if any(getattr(run, field) != value for field, value in expected_contract.items()):
        raise ValueError("Runul pilot nu corespunde politicilor curente")

    target_siruta = {
        code for code, _name, _label in read_locations_catalogue()[run.county]
    }
    selected_categories = set(run.categories)
    normalized_target_county = normalize_administrative_name(run.county)
    caen_codes, status_codes = load_nomenclatures(paths)
    chunk_size = 20_000
    claim_token = claim_import_run(run)
    if claim_token is None:
        return run.counters, False
    run.refresh_from_db()

    try:
        with TemporaryDirectory(prefix="casamea-onrc-pilot-", dir=scratch_dir) as scratch:
            database_path = Path(scratch) / "pilot.sqlite3"
            with closing(sqlite3.connect(database_path)) as database:
                database.executescript(
                    """
                    PRAGMA journal_mode = OFF;
                    PRAGMA synchronous = OFF;
                    PRAGMA temp_store = FILE;
                    CREATE TABLE firm_fingerprints (
                        registration_number TEXT NOT NULL,
                        fingerprint BLOB NOT NULL
                    );
                    CREATE TABLE target_firms (
                        registration_number TEXT NOT NULL,
                        fingerprint BLOB NOT NULL,
                        legal_name TEXT NOT NULL,
                        cui TEXT NOT NULL,
                        euid TEXT NOT NULL,
                        legal_form TEXT NOT NULL,
                        registration_date TEXT NOT NULL,
                        country TEXT NOT NULL,
                        county TEXT NOT NULL,
                        locality TEXT NOT NULL,
                        siruta_code TEXT NOT NULL,
                        locality_match TEXT NOT NULL,
                        registry_web TEXT NOT NULL
                    );
                    CREATE TABLE selected_activities (
                        registration_number TEXT NOT NULL,
                        version TEXT NOT NULL,
                        code TEXT NOT NULL,
                        category TEXT NOT NULL
                    );
                    CREATE TABLE status_rows (
                        registration_number TEXT NOT NULL,
                        status_code TEXT NOT NULL
                    );
                    """
                )
                counters: Counter[str] = Counter()
                fingerprint_chunk: list[tuple] = []
                target_chunk: list[tuple] = []
                for row in read_validated_rows(paths["firms"], "firms"):
                    counters["source_firm_rows"] += 1
                    registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                    if (
                        not registration_number
                        or None in row
                        or any(value is None for value in row.values())
                    ):
                        counters["invalid_firm_rows"] += 1
                        continue
                    fingerprint = firm_fingerprint(row)
                    fingerprint_chunk.append((registration_number, fingerprint))
                    if len(fingerprint_chunk) == chunk_size:
                        _flush(
                            database,
                            "INSERT INTO firm_fingerprints VALUES (?, ?)",
                            fingerprint_chunk,
                        )
                    country = normalize_administrative_name(row.get("ADR_TARA") or "")
                    county = normalize_administrative_name(row.get("ADR_JUDET") or "")
                    if country not in {"românia", "romania"} or county != normalized_target_county:
                        continue
                    match_status, siruta_code = registered_office_match_with_approved_aliases(
                        row.get("ADR_TARA") or "",
                        row.get("ADR_JUDET") or "",
                        row.get("ADR_LOCALITATE") or "",
                    )
                    if match_status in {"exact", "hierarchy_alias"} and siruta_code in target_siruta:
                        counters[f"target_{match_status}_firm_rows"] += 1
                        target_chunk.append(
                            (
                                registration_number,
                                fingerprint,
                                row["DENUMIRE"].strip(),
                                row["CUI"].strip(),
                                row["EUID"].strip(),
                                row["FORMA_JURIDICA"].strip(),
                                row["DATA_INMATRICULARE"].strip(),
                                row["ADR_TARA"].strip(),
                                row["ADR_JUDET"].strip(),
                                row["ADR_LOCALITATE"].strip(),
                                siruta_code,
                                match_status,
                                row["WEB"].strip(),
                            )
                        )
                    if len(target_chunk) == chunk_size:
                        _flush(
                            database,
                            "INSERT INTO target_firms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            target_chunk,
                        )
                _flush(
                    database,
                    "INSERT INTO firm_fingerprints VALUES (?, ?)",
                    fingerprint_chunk,
                )
                _flush(
                    database,
                    "INSERT INTO target_firms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    target_chunk,
                )
                database.executescript(
                    """
                    CREATE INDEX pilot_fingerprint_idx
                        ON firm_fingerprints(registration_number);
                    CREATE INDEX pilot_target_idx ON target_firms(registration_number);
                    CREATE TABLE coherent_registrations AS
                        SELECT registration_number
                        FROM firm_fingerprints
                        GROUP BY registration_number
                        HAVING COUNT(DISTINCT fingerprint) = 1;
                    CREATE UNIQUE INDEX pilot_coherent_idx
                        ON coherent_registrations(registration_number);
                    """
                )

                activity_chunk: list[tuple] = []
                for row in read_validated_rows(paths["activities"], "activities"):
                    counters["source_activity_rows"] += 1
                    registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                    raw_code = (row.get("COD_CAEN_AUTORIZAT") or "").strip()
                    version = (row.get("VER_CAEN_AUTORIZAT") or "").strip()
                    code = raw_code.zfill(4)
                    if (
                        not registration_number
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
                        activity_chunk.append(
                            (registration_number, version, code, category)
                        )
                    if len(activity_chunk) == chunk_size:
                        _flush(
                            database,
                            "INSERT INTO selected_activities VALUES (?, ?, ?, ?)",
                            activity_chunk,
                        )
                _flush(
                    database,
                    "INSERT INTO selected_activities VALUES (?, ?, ?, ?)",
                    activity_chunk,
                )
                status_chunk: list[tuple] = []
                for row in read_validated_rows(paths["statuses"], "statuses"):
                    counters["source_status_rows"] += 1
                    registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                    code = (row.get("COD") or "").strip()
                    if (
                        not registration_number
                        or not code
                        or None in row
                        or any(value is None for value in row.values())
                    ):
                        counters["invalid_status_rows"] += 1
                    elif code not in status_codes:
                        counters["unknown_status_rows"] += 1
                    else:
                        status_chunk.append((registration_number, code))
                    if len(status_chunk) == chunk_size:
                        _flush(
                            database,
                            "INSERT INTO status_rows VALUES (?, ?)",
                            status_chunk,
                        )
                _flush(
                    database, "INSERT INTO status_rows VALUES (?, ?)", status_chunk
                )
                database.executescript(
                    """
                    CREATE INDEX pilot_activity_idx
                        ON selected_activities(registration_number);
                    CREATE INDEX pilot_status_idx
                        ON status_rows(registration_number, status_code);
                    CREATE TABLE candidate_registrations AS
                        SELECT DISTINCT target.registration_number
                        FROM target_firms AS target
                        JOIN coherent_registrations AS coherent USING (registration_number)
                        JOIN selected_activities AS activity USING (registration_number);
                    CREATE UNIQUE INDEX pilot_candidate_idx
                        ON candidate_registrations(registration_number);
                    CREATE TABLE candidate_status_sets AS
                        SELECT candidate.registration_number,
                               group_concat(status.status_code, ',') AS status_set
                        FROM candidate_registrations AS candidate
                        LEFT JOIN (
                            SELECT DISTINCT registration_number, status_code
                            FROM status_rows ORDER BY registration_number, status_code
                        ) AS status USING (registration_number)
                        GROUP BY candidate.registration_number;
                    CREATE UNIQUE INDEX pilot_candidate_status_idx
                        ON candidate_status_sets(registration_number);
                    CREATE TABLE eligible_registrations AS
                        SELECT registration_number FROM candidate_status_sets
                        WHERE status_set = '1048';
                    CREATE UNIQUE INDEX pilot_eligible_idx
                        ON eligible_registrations(registration_number);
                    """
                )
                decision_counts: Counter[str] = Counter()
                for status_set, count in database.execute(
                    """SELECT COALESCE(status_set, ''), COUNT(*)
                       FROM candidate_status_sets GROUP BY status_set"""
                ):
                    codes = tuple(code for code in status_set.split(",") if code)
                    decision_counts[proposed_status_decision(codes)] += count

                conflicting = database.execute(
                    """SELECT DISTINCT target.registration_number
                       FROM target_firms AS target
                       JOIN selected_activities AS activity USING (registration_number)
                       JOIN (
                           SELECT registration_number
                           FROM firm_fingerprints GROUP BY registration_number
                           HAVING COUNT(DISTINCT fingerprint) > 1
                       ) AS conflict USING (registration_number)"""
                ).fetchall()
                counters["candidate_coherent_firms"] = database.execute(
                    "SELECT COUNT(*) FROM candidate_registrations"
                ).fetchone()[0]
                counters["candidate_conflicting_firms"] = len(conflicting)
                eligible_count = database.execute(
                    "SELECT COUNT(*) FROM eligible_registrations"
                ).fetchone()[0]
                if sum(decision_counts.values()) != counters["candidate_coherent_firms"]:
                    raise ValueError("Deciziile de stare nu acoperă toți candidații")
                counters["scratch_database_bytes"] = database_path.stat().st_size

                with transaction.atomic():
                    run.business_snapshots.all().delete()
                    run.quarantine_records.all().delete()
                    for (registration_number,) in conflicting:
                        ImportQuarantine.objects.create(
                            import_run=run,
                            resource_kind="firms",
                            reason="conflicting_payload",
                            record_key_hash=_record_key_hash(registration_number),
                            diagnostic={
                                "scope": "approved_locality_policy_and_category"
                            },
                        )

                    cursor = database.execute(
                        """SELECT target.registration_number,
                                  MIN(target.legal_name), MIN(target.cui),
                                  MIN(target.euid), MIN(target.legal_form),
                                  MIN(target.registration_date), MIN(target.country),
                                  MIN(target.county), MIN(target.locality),
                                  MIN(target.siruta_code), MIN(target.locality_match),
                                  MIN(target.registry_web),
                                  MIN(hex(target.fingerprint))
                           FROM target_firms AS target
                           JOIN eligible_registrations AS eligible
                               USING (registration_number)
                           GROUP BY target.registration_number
                           ORDER BY target.registration_number"""
                    )
                    staged = 0
                    while rows := cursor.fetchmany(2_000):
                        registrations = [row[0] for row in rows]
                        BusinessIdentity.objects.bulk_create(
                            [
                                BusinessIdentity(registration_number=registration)
                                for registration in registrations
                            ],
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
                            record.business.registration_number: record
                            for record in records
                        }
                        activity_rows = database.execute(
                            f"""SELECT DISTINCT registration_number, version, code, category
                                FROM selected_activities
                                WHERE registration_number IN ({','.join('?' for _ in registrations)})""",
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
                            [
                                BusinessStatus(business_snapshot=record, code="1048")
                                for record in records
                            ]
                        )
                        staged += len(records)

                    counters["staged_businesses"] = staged
                    counters.update(
                        {
                            f"status_{decision}": count
                            for decision, count in decision_counts.items()
                        }
                    )
                    staged_queryset = RegisteredBusinessSnapshot.objects.filter(
                        import_run=run
                    )
                    incomplete_relations = staged_queryset.annotate(
                        status_count=Count("statuses", distinct=True),
                        caen_count=Count("caen_codes", distinct=True),
                        category_count=Count("categories", distinct=True),
                    ).filter(
                        Q(status_count=0) | Q(caen_count=0) | Q(category_count=0)
                    ).count()
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
                        "quarantine": ImportQuarantine.objects.filter(
                            import_run=run
                        ).count(),
                    }
                    if (
                        eligible_count != staged
                        or relation_counts["statuses"] != staged
                        or relation_counts["caen"] < staged
                        or relation_counts["categories"] < staged
                        or relation_counts["quarantine"]
                        != counters["candidate_conflicting_firms"]
                        or incomplete_relations
                    ):
                        raise ValueError("Reconcilierea relațiilor staged a eșuat")
                    counters["staged_statuses"] = relation_counts["statuses"]
                    counters["staged_caen"] = relation_counts["caen"]
                    counters["staged_categories"] = relation_counts["categories"]
                    counters["quarantine_records"] = relation_counts["quarantine"]
                    run.counters = dict(sorted(counters.items()))
                    run.state = ImportRun.State.SUCCEEDED
                    run.finished_at = timezone.now()
                    run.error_summary = ""
                    completed = ImportRun.objects.filter(
                        pk=run.pk,
                        state=ImportRun.State.RUNNING,
                        claim_token=claim_token,
                    ).update(
                        counters=run.counters,
                        state=ImportRun.State.SUCCEEDED,
                        finished_at=run.finished_at,
                        error_summary="",
                        claim_token=None,
                    )
                    if not completed:
                        raise ValueError("Claim-ul runului a fost pierdut înainte de finalizare")
        return run.counters, True
    except Exception as error:
        ImportRun.objects.filter(
            pk=run.pk,
            state=ImportRun.State.RUNNING,
            claim_token=claim_token,
        ).update(
            state=ImportRun.State.FAILED,
            finished_at=timezone.now(),
            error_summary=f"{type(error).__name__}: {error}"[:1000],
            claim_token=None,
        )
        raise
