"""Reproducible, disk-backed validation for complete ONRC snapshots."""

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from services.caen import CAEN_VERSION_LABELS, category_for_caen
from services.locations import read_locations_catalogue


IMPORTER_VERSION = "2"
APP_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_KINDS = (
    "firms",
    "activities",
    "statuses",
    "caen_dictionary",
    "status_dictionary",
    "caen_versions",
)
EXPECTED_HEADERS = {
    "firms": (
        "DENUMIRE", "CUI", "COD_INMATRICULARE", "DATA_INMATRICULARE", "EUID",
        "FORMA_JURIDICA", "ADR_TARA", "ADR_JUDET", "ADR_LOCALITATE",
        "ADR_DEN_STRADA", "ADR_NR_STRADA", "ADR_BLOC", "ADR_SCARA", "ADR_ETAJ",
        "ADR_APARTAMENT", "ADR_COD_POSTAL", "ADR_SECTOR", "ADR_COMPLETARE",
        "WEB", "TARA_FIRMA_MAMA",
    ),
    "activities": ("COD_INMATRICULARE", "COD_CAEN_AUTORIZAT", "VER_CAEN_AUTORIZAT"),
    "statuses": ("COD_INMATRICULARE", "COD"),
    "caen_dictionary": (
        "SECTIUNEA", "SUBSECTIUNEA", "DIVIZIUNEA", "GRUPA", "CLASA",
        "DENUMIRE", "VERSIUNE_CAEN",
    ),
    "status_dictionary": ("COD", "DENUMIRE"),
    "caen_versions": ("COD", "DESCRIERE"),
}


def normalize_administrative_name(value: str) -> str:
    """Normalize spacing and Romanian legacy cedilla diacritics for exact matching."""

    modern_diacritics = value.translate(
        str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})
    )
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFC", modern_diacritics)
    ).strip().casefold()


@lru_cache(maxsize=1)
def _registered_office_index() -> dict[str, dict[str, tuple[str, ...]]]:
    """Build a county/name index while preserving same-name SIRUTA ambiguity."""

    index: dict[str, dict[str, list[str]]] = {}
    for county, localities in read_locations_catalogue().items():
        county_index = index.setdefault(normalize_administrative_name(county), {})
        for code, name, _label in localities:
            county_index.setdefault(normalize_administrative_name(name), []).append(code)
    return {
        county: {name: tuple(codes) for name, codes in localities.items()}
        for county, localities in index.items()
    }


def registered_office_match(
    country: str, county: str, locality: str
) -> tuple[str, str]:
    """Return match state and code without silently choosing duplicate localities."""

    normalized_country = normalize_administrative_name(country)
    if not normalized_country:
        return "missing_country", ""
    if normalized_country not in {"românia", "romania"}:
        return "foreign", ""
    if not county.strip() or not locality.strip():
        return "missing", ""
    codes = _registered_office_index().get(
        normalize_administrative_name(county), {}
    ).get(normalize_administrative_name(locality), ())
    return (
        ("exact", codes[0])
        if len(codes) == 1
        else ("ambiguous", "")
        if codes
        else ("unmatched", "")
    )


def registered_office_match_status(country: str, county: str, locality: str) -> str:
    """Return only the reconciliation state for validation and UI policy tests."""

    return registered_office_match(country, county, locality)[0]


def firm_fingerprint(row: dict[str, str]) -> bytes:
    """Return a stable compact fingerprint of every official company field."""

    payload = "\x1f".join(row[column] for column in EXPECTED_HEADERS["firms"])
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).digest()


def read_validated_rows(path: Path, file_kind: str) -> Iterator[dict[str, str]]:
    """Yield strict CSV rows after the header matches the known ONRC contract."""

    with path.open(encoding="utf-8-sig", newline="") as source:
        # ONRC names may contain literal, unescaped double quotes. The export contract
        # uses only the caret as structure, so quote processing must stay disabled.
        reader = csv.DictReader(
            source, delimiter="^", quoting=csv.QUOTE_NONE, strict=True
        )
        actual = tuple(reader.fieldnames or ())
        expected = EXPECTED_HEADERS[file_kind]
        if actual != expected:
            raise ValueError(
                f"Schema ONRC neașteptată pentru {file_kind}: {actual!r}; "
                f"așteptat {expected!r}"
            )
        yield from reader


def _sha256(path: Path) -> str:
    """Hash one source file in bounded memory."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(
    manifest_path: Path,
    input_dir: Path,
) -> tuple[dict[str, object], dict[str, Path], dict[str, dict[str, object]]]:
    """Verify snapshot identity, all six resources, and the pinned SIRUTA artifact."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Versiunea manifestului ONRC nu este suportată")
    resources = manifest.get("resources")
    if not isinstance(resources, dict) or any(key not in resources for key in RESOURCE_KINDS):
        raise ValueError("Manifestul ONRC nu conține toate cele șase resurse obligatorii")

    paths: dict[str, Path] = {}
    verified: dict[str, dict[str, object]] = {}
    for kind in RESOURCE_KINDS:
        specification = resources[kind]
        path = input_dir / specification["filename"]
        if not path.is_file():
            raise ValueError(f"Resursa {kind} lipsește: {path}")
        size = path.stat().st_size
        digest = _sha256(path)
        if size != specification["size_bytes"] or digest != specification["sha256"]:
            raise ValueError(
                f"Integritatea resursei {kind} a eșuat: "
                f"size={size}, sha256={digest}"
            )
        paths[kind] = path
        verified[kind] = {"size_bytes": size, "sha256": digest}

    for siruta_kind in ("siruta_catalogue", "siruta_hierarchy"):
        siruta = manifest.get(siruta_kind)
        if not isinstance(siruta, dict):
            raise ValueError(f"Manifestul nu fixează artefactul {siruta_kind}")
        siruta_path = APP_ROOT / siruta["repository_path"]
        siruta_size = siruta_path.stat().st_size
        siruta_digest = _sha256(siruta_path)
        if siruta_size != siruta["size_bytes"] or siruta_digest != siruta["sha256"]:
            raise ValueError(
                f"Artefactul {siruta_kind} diferă de versiunea fixată în manifest"
            )
        verified[siruta_kind] = {
            "size_bytes": siruta_size,
            "sha256": siruta_digest,
            "source_date": siruta["source_date"],
        }
    return manifest, paths, verified


def load_nomenclatures(paths: dict[str, Path]) -> tuple[set[tuple[str, str]], set[str]]:
    """Load small same-snapshot dictionaries and validate the CAEN version contract."""

    versions = {}
    for row in read_validated_rows(paths["caen_versions"], "caen_versions"):
        match = re.search(r"(\d{4})$", row["DESCRIERE"].strip())
        if row["COD"].strip() and match:
            versions[row["COD"].strip()] = match.group(1)
    if versions != CAEN_VERSION_LABELS:
        raise ValueError(
            f"Versiunile CAEN din nomenclator diferă de contract: {versions!r}"
        )

    caen_codes = {
        (row["VERSIUNE_CAEN"].strip(), row["CLASA"].strip())
        for row in read_validated_rows(paths["caen_dictionary"], "caen_dictionary")
        if re.fullmatch(r"\d{4}", row["CLASA"].strip())
        and row["VERSIUNE_CAEN"].strip() in versions
    }
    status_codes = {
        row["COD"].strip()
        for row in read_validated_rows(paths["status_dictionary"], "status_dictionary")
        if row["COD"].strip()
    }
    if not caen_codes or not status_codes:
        raise ValueError("Nomenclatoarele ONRC sunt goale sau nevalide")
    return caen_codes, status_codes


def _flush(database: sqlite3.Connection, statement: str, chunk: list[tuple]) -> None:
    """Write and clear one bounded-memory chunk."""

    if chunk:
        database.executemany(statement, chunk)
        chunk.clear()


def audit_snapshot(
    paths: dict[str, Path],
    scratch_dir: Path | None = None,
) -> dict[str, object]:
    """Audit a verified bundle without mutating the marketplace database."""

    caen_codes, status_codes = load_nomenclatures(paths)
    version_counts: Counter[str] = Counter()
    raw_category_counts: Counter[str] = Counter()
    activity_rejections: Counter[str] = Counter()
    status_rejections: Counter[str] = Counter()
    chunk_size = 20_000

    with TemporaryDirectory(prefix="casamea-onrc-audit-", dir=scratch_dir) as scratch:
        database_path = Path(scratch) / "relations.sqlite3"
        with closing(sqlite3.connect(database_path)) as database:
            database.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                PRAGMA temp_store = FILE;
                CREATE TABLE firm_rows (
                    registration_number TEXT NOT NULL,
                    fingerprint BLOB NOT NULL,
                    match_status TEXT NOT NULL,
                    siruta_code TEXT NOT NULL
                );
                CREATE TABLE activity_refs (registration_number TEXT NOT NULL);
                CREATE TABLE category_links (
                    registration_number TEXT NOT NULL,
                    category TEXT NOT NULL
                );
                CREATE TABLE status_refs (
                    registration_number TEXT NOT NULL,
                    status_code TEXT NOT NULL
                );
                """
            )

            firm_rows = 0
            invalid_firms = 0
            firm_chunk: list[tuple] = []
            for row in read_validated_rows(paths["firms"], "firms"):
                firm_rows += 1
                registration_number = (row.get("COD_INMATRICULARE") or "").strip()
                if not registration_number or None in row or any(
                    value is None for value in row.values()
                ):
                    invalid_firms += 1
                    continue
                match_status, siruta_code = registered_office_match(
                    row.get("ADR_TARA") or "",
                    row.get("ADR_JUDET") or "",
                    row.get("ADR_LOCALITATE") or "",
                )
                firm_chunk.append(
                    (
                        registration_number,
                        firm_fingerprint(row),
                        match_status,
                        siruta_code,
                    )
                )
                if len(firm_chunk) == chunk_size:
                    _flush(database, "INSERT INTO firm_rows VALUES (?, ?, ?, ?)", firm_chunk)
            _flush(database, "INSERT INTO firm_rows VALUES (?, ?, ?, ?)", firm_chunk)

            database.executescript(
                """
                CREATE INDEX firm_registration_idx ON firm_rows(registration_number);
                CREATE TABLE firm_registrations AS
                    SELECT DISTINCT registration_number FROM firm_rows;
                CREATE UNIQUE INDEX firm_registration_unique_idx
                    ON firm_registrations(registration_number);
                CREATE TABLE coherent_firms AS
                    SELECT registration_number,
                           MIN(match_status) AS match_status,
                           MIN(siruta_code) AS siruta_code
                    FROM firm_rows
                    GROUP BY registration_number
                    HAVING COUNT(DISTINCT fingerprint) = 1;
                CREATE UNIQUE INDEX coherent_firm_idx
                    ON coherent_firms(registration_number);
                """
            )
            unique_firms = database.execute(
                "SELECT COUNT(*) FROM firm_registrations"
            ).fetchone()[0]
            coherent_firms = database.execute(
                "SELECT COUNT(*) FROM coherent_firms"
            ).fetchone()[0]
            duplicate_groups = database.execute(
                """SELECT
                       SUM(CASE WHEN fingerprints = 1 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN fingerprints > 1 THEN 1 ELSE 0 END)
                   FROM (
                       SELECT COUNT(DISTINCT fingerprint) AS fingerprints
                       FROM firm_rows GROUP BY registration_number HAVING COUNT(*) > 1
                   )"""
            ).fetchone()
            match_counts = dict(
                database.execute(
                    "SELECT match_status, COUNT(*) FROM coherent_firms GROUP BY match_status"
                ).fetchall()
            )

            activity_rows = 0
            activity_chunk: list[tuple] = []
            category_chunk: list[tuple] = []
            for row in read_validated_rows(paths["activities"], "activities"):
                activity_rows += 1
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
                    activity_rejections["invalid_structure"] += 1
                    continue
                activity_chunk.append((registration_number,))
                if (version, code) not in caen_codes:
                    activity_rejections["unknown_caen"] += 1
                else:
                    version_counts[CAEN_VERSION_LABELS[version]] += 1
                    category = category_for_caen(code, version)
                    if version in {"0", "1"}:
                        activity_rejections["unsupported_mapping_version"] += 1
                    elif not category:
                        activity_rejections["unmapped_supported_activity"] += 1
                    else:
                        raw_category_counts[category] += 1
                        category_chunk.append((registration_number, category))
                if len(activity_chunk) == chunk_size:
                    _flush(database, "INSERT INTO activity_refs VALUES (?)", activity_chunk)
                if len(category_chunk) == chunk_size:
                    _flush(database, "INSERT INTO category_links VALUES (?, ?)", category_chunk)
            _flush(database, "INSERT INTO activity_refs VALUES (?)", activity_chunk)
            _flush(database, "INSERT INTO category_links VALUES (?, ?)", category_chunk)

            status_rows = 0
            status_chunk: list[tuple] = []
            for row in read_validated_rows(paths["statuses"], "statuses"):
                status_rows += 1
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
                if code not in status_codes:
                    status_rejections["unknown_status"] += 1
                status_chunk.append((registration_number, code))
                if len(status_chunk) == chunk_size:
                    _flush(database, "INSERT INTO status_refs VALUES (?, ?)", status_chunk)
            _flush(database, "INSERT INTO status_refs VALUES (?, ?)", status_chunk)

            database.executescript(
                """
                CREATE INDEX activity_ref_idx ON activity_refs(registration_number);
                CREATE INDEX category_link_idx
                    ON category_links(registration_number, category);
                CREATE INDEX status_ref_idx ON status_refs(registration_number, status_code);
                """
            )
            orphan_activities = database.execute(
                """SELECT COUNT(*) FROM activity_refs AS item
                   LEFT JOIN firm_registrations USING (registration_number)
                   WHERE firm_registrations.registration_number IS NULL"""
            ).fetchone()[0]
            orphan_statuses = database.execute(
                """SELECT COUNT(*) FROM status_refs AS item
                   LEFT JOIN firm_registrations USING (registration_number)
                   WHERE firm_registrations.registration_number IS NULL"""
            ).fetchone()[0]
            unique_category_firms = dict(
                database.execute(
                    """SELECT category, COUNT(DISTINCT registration_number)
                       FROM category_links JOIN coherent_firms USING (registration_number)
                       GROUP BY category ORDER BY category"""
                ).fetchall()
            )
            exact_category_firms = dict(
                database.execute(
                    """SELECT category, COUNT(DISTINCT registration_number)
                       FROM category_links JOIN coherent_firms USING (registration_number)
                       WHERE match_status = 'exact'
                       GROUP BY category ORDER BY category"""
                ).fetchall()
            )
            status_summary = {
                "firms_with_function_status": database.execute(
                    """SELECT COUNT(DISTINCT registration_number)
                       FROM status_refs JOIN coherent_firms USING (registration_number)
                       WHERE status_code = '1048'"""
                ).fetchone()[0],
                "firms_with_radiated_status": database.execute(
                    """SELECT COUNT(DISTINCT registration_number)
                       FROM status_refs JOIN coherent_firms USING (registration_number)
                       WHERE status_code = '1084'"""
                ).fetchone()[0],
            }
            database.commit()
            scratch_database_bytes = database_path.stat().st_size

    return {
        "nomenclatures": {
            "caen_class_keys": len(caen_codes),
            "status_codes": len(status_codes),
            "caen_versions": CAEN_VERSION_LABELS,
        },
        "firms": {
            "rows": firm_rows,
            "invalid_rows": invalid_firms,
            "unique_registration_numbers": unique_firms,
            "coherent_unique_firms": coherent_firms,
            "duplicate_extra_rows": firm_rows - invalid_firms - unique_firms,
            "identical_duplicate_registration_numbers": duplicate_groups[0] or 0,
            "conflicting_duplicate_registration_numbers": duplicate_groups[1] or 0,
            "registered_office_siruta_match_unique_firms": dict(sorted(match_counts.items())),
        },
        "activities": {
            "rows": activity_rows,
            "rejections": dict(sorted(activity_rejections.items())),
            "orphan_rows": orphan_activities,
            "caen_versions": dict(sorted(version_counts.items())),
            "mapped_activity_rows": dict(sorted(raw_category_counts.items())),
            "unique_coherent_firms_per_category": unique_category_firms,
            "exact_siruta_unique_firms_per_category": exact_category_firms,
        },
        "statuses": {
            "rows": status_rows,
            "rejections": dict(sorted(status_rejections.items())),
            "orphan_rows": orphan_statuses,
            **status_summary,
        },
        "scratch_database_bytes": scratch_database_bytes,
    }
