"""Disk-backed audit of ONRC status combinations for a conservative pilot policy."""

import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from services.importers.onrc import (
    _flush,
    firm_fingerprint,
    read_validated_rows,
)


POLICY_VERSION = "1"
POLICY_STATE = "approved_for_internal_staging"
POLICY_APPROVED_AT = "2026-08-21"
POLICY_APPROVED_BY = "independent exhaustive ONRC status review"


def proposed_status_decision(status_codes: tuple[str, ...]) -> str:
    """Classify one official status set without interpreting unknown combinations."""

    codes = set(status_codes)
    if "1084" in codes:
        return "excluded_radiated"
    if codes == {"1048"}:
        return "eligible_function_only"
    if "1048" in codes:
        return "needs_review_mixed_function"
    return "quarantined_without_function"


def audit_status_policy(
    firms_path: Path,
    statuses_path: Path,
    status_dictionary_path: Path,
    scratch_dir: Path | None = None,
) -> dict[str, object]:
    """Inventory status sets for coherent firms without exposing company identity."""

    dictionary: dict[str, str] = {}
    dictionary_rejections: Counter[str] = Counter()
    for row in read_validated_rows(status_dictionary_path, "status_dictionary"):
        code = (row.get("COD") or "").strip()
        description = (row.get("DENUMIRE") or "").strip()
        if (
            not code
            or not description
            or None in row
            or any(value is None for value in row.values())
        ):
            dictionary_rejections["invalid_row"] += 1
        elif code in dictionary and dictionary[code] == description:
            dictionary_rejections["identical_duplicate_code"] += 1
        elif code in dictionary:
            dictionary_rejections["conflicting_duplicate_code"] += 1
        else:
            dictionary[code] = description
    if not dictionary or dictionary_rejections["conflicting_duplicate_code"]:
        raise ValueError("Nomenclatorul stărilor este gol sau conține coduri conflictuale")

    chunk_size = 20_000
    status_rejections: Counter[str] = Counter()
    with TemporaryDirectory(prefix="casamea-onrc-status-", dir=scratch_dir) as scratch:
        database_path = Path(scratch) / "statuses.sqlite3"
        with closing(sqlite3.connect(database_path)) as database:
            database.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                PRAGMA temp_store = FILE;
                CREATE TABLE firm_rows (
                    registration_number TEXT NOT NULL,
                    fingerprint BLOB NOT NULL
                );
                CREATE TABLE status_rows (
                    registration_number TEXT NOT NULL,
                    status_code TEXT NOT NULL
                );
                """
            )

            source_firm_rows = 0
            invalid_firm_rows = 0
            firm_chunk: list[tuple] = []
            for row in read_validated_rows(firms_path, "firms"):
                source_firm_rows += 1
                registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                if not registration_number or None in row or any(
                    value is None for value in row.values()
                ):
                    invalid_firm_rows += 1
                    continue
                firm_chunk.append((registration_number, firm_fingerprint(row)))
                if len(firm_chunk) == chunk_size:
                    _flush(database, "INSERT INTO firm_rows VALUES (?, ?)", firm_chunk)
            _flush(database, "INSERT INTO firm_rows VALUES (?, ?)", firm_chunk)
            database.executescript(
                """
                CREATE INDEX status_audit_firm_idx ON firm_rows(registration_number);
                CREATE TABLE firm_registrations AS
                    SELECT DISTINCT registration_number FROM firm_rows;
                CREATE UNIQUE INDEX status_audit_registration_idx
                    ON firm_registrations(registration_number);
                CREATE TABLE coherent_firms AS
                    SELECT registration_number
                    FROM firm_rows
                    GROUP BY registration_number
                    HAVING COUNT(DISTINCT fingerprint) = 1;
                CREATE UNIQUE INDEX status_audit_coherent_idx
                    ON coherent_firms(registration_number);
                """
            )

            source_status_rows = 0
            accepted_status_rows = 0
            status_chunk: list[tuple] = []
            for row in read_validated_rows(statuses_path, "statuses"):
                source_status_rows += 1
                registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                code = (row.get("COD") or "").strip()
                if (
                    not registration_number
                    or not code
                    or None in row
                    or any(value is None for value in row.values())
                ):
                    status_rejections["invalid_structure"] += 1
                    continue
                if code not in dictionary:
                    status_rejections["unknown_status"] += 1
                    continue
                accepted_status_rows += 1
                status_chunk.append((registration_number, code))
                if len(status_chunk) == chunk_size:
                    _flush(database, "INSERT INTO status_rows VALUES (?, ?)", status_chunk)
            _flush(database, "INSERT INTO status_rows VALUES (?, ?)", status_chunk)
            database.executescript(
                """
                CREATE INDEX status_audit_link_idx
                    ON status_rows(registration_number, status_code);
                CREATE TABLE distinct_statuses AS
                    SELECT DISTINCT registration_number, status_code FROM status_rows;
                CREATE INDEX status_audit_distinct_idx
                    ON distinct_statuses(registration_number, status_code);
                CREATE TABLE status_sets AS
                    SELECT registration_number, group_concat(status_code, ',') AS status_set
                    FROM (
                        SELECT registration_number, status_code
                        FROM distinct_statuses
                        ORDER BY registration_number, status_code
                    )
                    GROUP BY registration_number;
                CREATE UNIQUE INDEX status_audit_set_idx
                    ON status_sets(registration_number);
                """
            )

            coherent_firms = database.execute(
                "SELECT COUNT(*) FROM coherent_firms"
            ).fetchone()[0]
            unique_firms = database.execute(
                "SELECT COUNT(*) FROM firm_registrations"
            ).fetchone()[0]
            distinct_status_memberships = database.execute(
                "SELECT COUNT(*) FROM distinct_statuses"
            ).fetchone()[0]
            duplicate_status_rows = accepted_status_rows - distinct_status_memberships

            def linked_count(table: str, linked_table: str, inverse: bool = False) -> int:
                """Count raw rows or memberships in one explicit firm-link bucket."""

                operator = "IS NULL" if inverse else "IS NOT NULL"
                return database.execute(
                    f"""SELECT COUNT(*) FROM {table} AS status
                        LEFT JOIN {linked_table} AS firm USING (registration_number)
                        WHERE firm.registration_number {operator}"""
                ).fetchone()[0]

            raw_orphan_rows = linked_count("status_rows", "firm_registrations", True)
            distinct_orphan_memberships = linked_count(
                "distinct_statuses", "firm_registrations", True
            )
            raw_coherent_rows = database.execute(
                """SELECT COUNT(*) FROM status_rows
                   JOIN coherent_firms USING (registration_number)"""
            ).fetchone()[0]
            distinct_coherent_memberships = database.execute(
                """SELECT COUNT(*) FROM distinct_statuses
                   JOIN coherent_firms USING (registration_number)"""
            ).fetchone()[0]
            raw_noncoherent_rows = accepted_status_rows - raw_coherent_rows - raw_orphan_rows
            distinct_noncoherent_memberships = (
                distinct_status_memberships
                - distinct_coherent_memberships
                - distinct_orphan_memberships
            )
            noncoherent_firms_with_status = database.execute(
                """SELECT COUNT(DISTINCT status.registration_number)
                   FROM distinct_statuses AS status
                   JOIN firm_registrations AS firm USING (registration_number)
                   LEFT JOIN coherent_firms AS coherent USING (registration_number)
                   WHERE coherent.registration_number IS NULL"""
            ).fetchone()[0]
            code_counts = dict(
                database.execute(
                    """SELECT status_code, COUNT(*)
                       FROM distinct_statuses JOIN coherent_firms USING (registration_number)
                       GROUP BY status_code ORDER BY status_code"""
                ).fetchall()
            )
            raw_combinations = database.execute(
                """SELECT COALESCE(status_set, ''), COUNT(*)
                   FROM coherent_firms LEFT JOIN status_sets USING (registration_number)
                   GROUP BY COALESCE(status_set, '')
                   ORDER BY COUNT(*) DESC, status_set"""
            ).fetchall()
            scratch_database_bytes = database_path.stat().st_size

    decision_counts: Counter[str] = Counter()
    combinations = []
    for serialized_codes, firm_count in raw_combinations:
        codes = tuple(code for code in serialized_codes.split(",") if code)
        decision = proposed_status_decision(codes)
        decision_counts[decision] += firm_count
        combinations.append(
            {
                "status_codes": list(codes),
                "status_descriptions": [dictionary[code] for code in codes],
                "coherent_firm_count": firm_count,
                "proposed_decision": decision,
            }
        )

    return {
        "policy_version": POLICY_VERSION,
        "policy_state": POLICY_STATE,
        "policy_approved_at": POLICY_APPROVED_AT,
        "policy_approved_by": POLICY_APPROVED_BY,
        "policy_contract": {
            "eligible_function_only": "status set is exactly [1048] (funcțiune)",
            "excluded_radiated": "status set contains 1084 (radiată)",
            "needs_review_mixed_function": "status set contains 1048 plus other codes",
            "quarantined_without_function": "status set is empty or lacks 1048 and 1084",
        },
        "source_firms": {
            "rows": source_firm_rows,
            "invalid_rows": invalid_firm_rows,
            "coherent_unique_firms": coherent_firms,
            "noncoherent_unique_firms": unique_firms - coherent_firms,
        },
        "source_statuses": {
            "rows": source_status_rows,
            "accepted_rows": accepted_status_rows,
            "duplicate_rows": duplicate_status_rows,
            "distinct_memberships": distinct_status_memberships,
            "rejections": dict(sorted(status_rejections.items())),
            "link_accounting": {
                "raw_rows": {
                    "coherent_firm": raw_coherent_rows,
                    "noncoherent_firm": raw_noncoherent_rows,
                    "orphan": raw_orphan_rows,
                },
                "distinct_memberships": {
                    "coherent_firm": distinct_coherent_memberships,
                    "noncoherent_firm": distinct_noncoherent_memberships,
                    "orphan": distinct_orphan_memberships,
                },
                "noncoherent_unique_firms_with_status": noncoherent_firms_with_status,
            },
        },
        "nomenclature": {
            "codes": len(dictionary),
            "rejections": dict(sorted(dictionary_rejections.items())),
            "coherent_firms_per_code": code_counts,
        },
        "decision_counts": dict(sorted(decision_counts.items())),
        "status_combination_count": len(combinations),
        "status_combinations": combinations,
        "scratch_database_bytes": scratch_database_bytes,
    }
