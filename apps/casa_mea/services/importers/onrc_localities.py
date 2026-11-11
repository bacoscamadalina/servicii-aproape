"""Privacy-minimized aggregation of ONRC registered-office locality variants."""

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from services.importers.onrc import (
    EXPECTED_HEADERS,
    firm_fingerprint,
    normalize_administrative_name,
    read_validated_rows,
    registered_office_match,
)


def build_locality_candidates(
    firms_path: Path,
    scratch_dir: Path | None = None,
) -> dict[str, object]:
    """Aggregate coherent companies by normalized administrative locality fields."""

    invalid_rows = 0
    source_rows = 0
    chunk: list[tuple] = []
    chunk_size = 20_000

    with TemporaryDirectory(prefix="casamea-onrc-localities-", dir=scratch_dir) as scratch:
        database_path = Path(scratch) / "localities.sqlite3"
        with closing(sqlite3.connect(database_path)) as database:
            database.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                PRAGMA temp_store = FILE;
                CREATE TABLE office_rows (
                    registration_number TEXT NOT NULL,
                    fingerprint BLOB NOT NULL,
                    country_key TEXT NOT NULL,
                    county_key TEXT NOT NULL,
                    locality_key TEXT NOT NULL,
                    sector_key TEXT NOT NULL,
                    country_label TEXT NOT NULL,
                    county_label TEXT NOT NULL,
                    locality_label TEXT NOT NULL,
                    sector_label TEXT NOT NULL,
                    baseline_status TEXT NOT NULL
                );
                """
            )
            for row in read_validated_rows(firms_path, "firms"):
                source_rows += 1
                registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                if not registration_number or None in row or any(
                    value is None for value in row.values()
                ):
                    invalid_rows += 1
                    continue
                country = (row.get("ADR_TARA") or "").strip()
                county = (row.get("ADR_JUDET") or "").strip()
                locality = (row.get("ADR_LOCALITATE") or "").strip()
                sector = (row.get("ADR_SECTOR") or "").strip()
                baseline_status, _code = registered_office_match(
                    country, county, locality
                )
                chunk.append(
                    (
                        registration_number,
                        firm_fingerprint(row),
                        normalize_administrative_name(country),
                        normalize_administrative_name(county),
                        normalize_administrative_name(locality),
                        normalize_administrative_name(sector),
                        country,
                        county,
                        locality,
                        sector,
                        baseline_status,
                    )
                )
                if len(chunk) == chunk_size:
                    database.executemany(
                        "INSERT INTO office_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        chunk,
                    )
                    chunk.clear()
            if chunk:
                database.executemany(
                    "INSERT INTO office_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    chunk,
                )

            database.executescript(
                """
                CREATE INDEX office_registration_idx
                    ON office_rows(registration_number);
                CREATE TABLE coherent_offices AS
                    SELECT registration_number,
                           MIN(country_key) AS country_key,
                           MIN(county_key) AS county_key,
                           MIN(locality_key) AS locality_key,
                           MIN(sector_key) AS sector_key,
                           MIN(country_label) AS country_label,
                           MIN(county_label) AS county_label,
                           MIN(locality_label) AS locality_label,
                           MIN(sector_label) AS sector_label,
                           MIN(baseline_status) AS baseline_status
                    FROM office_rows
                    GROUP BY registration_number
                    HAVING COUNT(DISTINCT fingerprint) = 1;
                """
            )
            grouped_rows = database.execute(
                """SELECT country_key, county_key, locality_key, sector_key,
                          MIN(country_label), MIN(county_label), MIN(locality_label),
                          MIN(sector_label), baseline_status, COUNT(*)
                   FROM coherent_offices
                   GROUP BY country_key, county_key, locality_key, sector_key,
                            baseline_status
                   ORDER BY COUNT(*) DESC, county_key, locality_key, sector_key"""
            ).fetchall()
            coherent_firms = database.execute(
                "SELECT COUNT(*) FROM coherent_offices"
            ).fetchone()[0]
            scratch_database_bytes = database_path.stat().st_size

    status_counts: Counter[str] = Counter()
    candidates = []
    for (
        country_key,
        county_key,
        locality_key,
        sector_key,
        country_label,
        county_label,
        locality_label,
        sector_label,
        baseline_status,
        firm_count,
    ) in grouped_rows:
        status_counts[baseline_status] += firm_count
        identity = "\x1f".join((country_key, county_key, locality_key, sector_key))
        candidates.append(
            {
                "candidate_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
                "country": country_key,
                "county": county_key,
                "locality": locality_key,
                "sector": sector_key,
                "example_labels": {
                    "country": country_label,
                    "county": county_label,
                    "locality": locality_label,
                    "sector": sector_label,
                },
                "baseline_status": baseline_status,
                "coherent_firm_count": firm_count,
            }
        )

    return {
        "source_rows": source_rows,
        "invalid_rows": invalid_rows,
        "coherent_unique_firms": coherent_firms,
        "candidate_groups": len(candidates),
        "baseline_status_unique_firms": dict(sorted(status_counts.items())),
        "scratch_database_bytes": scratch_database_bytes,
        "candidates": candidates,
    }
