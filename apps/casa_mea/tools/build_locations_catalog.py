"""Build the runtime locality catalogue from the official SIRUTA workbook."""

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

ROMANIAN_SORT_TRANSLATION = str.maketrans("ăâîșț", "aaist")


def _validate_release_coordinates(
    *,
    release_id: str | None,
    source_url: str | None,
    published_date: str | None,
    retrieved_at: str | None,
) -> None:
    """Reject incomplete or temporally ambiguous release provenance."""

    if not all((release_id, source_url, published_date, retrieved_at)):
        raise ValueError(
            "Ierarhia cere release_id, source_url, published_date și retrieved_at."
        )
    try:
        published = date.fromisoformat(published_date)
        retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Datele release-ului SIRUTA trebuie să fie ISO 8601.") from error
    if retrieved.utcoffset() is None:
        raise ValueError("retrieved_at trebuie să includă fusul orar.")
    if published > retrieved.date():
        raise ValueError("published_date nu poate fi după retrieved_at.")
    if not source_url.startswith(("https://", "http://")):
        raise ValueError("source_url trebuie să fie un URL HTTP(S) explicit.")


def _release_metadata(
    *,
    source_bytes: bytes,
    catalogue_bytes: bytes,
    county_count: int,
    locality_count: int,
    release_id: str | None,
    source_url: str | None,
    published_date: str | None,
    retrieved_at: str | None,
) -> dict:
    """Validate and pin every external and generated input of one release."""

    _validate_release_coordinates(
        release_id=release_id,
        source_url=source_url,
        published_date=published_date,
        retrieved_at=retrieved_at,
    )
    return {
        "dataset": f"SIRUTA S1 {release_id}",
        "release_id": release_id,
        "sheet": "Data",
        "source_url": source_url,
        "published_date": published_date,
        "retrieved_at": retrieved_at,
        "raw_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "generator_policy_version": "siruta-localities-v2",
        "catalogue_sha256": hashlib.sha256(catalogue_bytes).hexdigest(),
        "county_count": county_count,
        "locality_count": locality_count,
    }


def _write_new_candidate_pair(
    *,
    catalogue_bytes: bytes,
    hierarchy_bytes: bytes,
    destination: Path,
    hierarchy_destination: Path,
) -> None:
    """Install a staged pair only into fresh paths and roll back a split failure."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    hierarchy_destination.parent.mkdir(parents=True, exist_ok=True)
    staged_paths: list[Path] = []
    catalogue_installed = False
    try:
        for parent, prefix, content in (
            (destination.parent, ".siruta-catalogue-", catalogue_bytes),
            (hierarchy_destination.parent, ".siruta-hierarchy-", hierarchy_bytes),
        ):
            with tempfile.NamedTemporaryFile(
                dir=parent, prefix=prefix, delete=False
            ) as staged:
                staged.write(content)
                staged_paths.append(Path(staged.name))
        os.link(staged_paths[0], destination)
        catalogue_installed = True
        os.link(staged_paths[1], hierarchy_destination)
    except Exception:
        if catalogue_installed:
            destination.unlink(missing_ok=True)
        raise
    finally:
        for staged_path in staged_paths:
            staged_path.unlink(missing_ok=True)


def normalized_name(value: str) -> str:
    """Return modern Romanian diacritics and readable title casing."""

    return str(value).strip().replace("Ş", "Ș").replace("Ţ", "Ț").title()


def romanian_sort_key(value: str) -> str:
    """Return a stable, diacritic-aware key suited to Romanian pickers."""

    return value.casefold().translate(ROMANIAN_SORT_TRANSLATION)


def write_catalog(
    source: Path,
    destination: Path,
    hierarchy_destination: Path | None = None,
    *,
    release_id: str | None = None,
    source_url: str | None = None,
    published_date: str | None = None,
    retrieved_at: str | None = None,
) -> None:
    """Write the UI catalogue and, optionally, its administrative hierarchy."""

    if hierarchy_destination is not None:
        _validate_release_coordinates(
            release_id=release_id,
            source_url=source_url,
            published_date=published_date,
            retrieved_at=retrieved_at,
        )
        if destination == hierarchy_destination:
            raise ValueError("Catalogul și ierarhia trebuie să aibă destinații diferite.")
        if destination.exists() or hierarchy_destination.exists():
            raise FileExistsError(
                "Candidatul SIRUTA se generează numai în două destinații noi."
            )

    import pandas as pd

    source_bytes = source.read_bytes()
    data = pd.read_excel(BytesIO(source_bytes), sheet_name="Data")
    county_names = {
        int(row.JUD): normalized_name(
            str(row.DENLOC)
            .replace("JUDEŢUL ", "")
            .replace("MUNICIPIUL ", "")
        )
        for row in data[data.NIV == 1].itertuples()
    }
    administrative_units = {
        int(row.SIRUTA): {
            "name": normalized_name(
                str(row.DENLOC)
                .replace("MUNICIPIUL ", "")
                .replace("ORAŞ ", "")
                .replace("ORAȘ ", "")
                .replace("COMUNA ", "")
            ),
            "tip": int(row.TIP),
        }
        for row in data[data.NIV == 2].itertuples()
    }
    rows_by_county = defaultdict(list)

    for row in data[data.NIV == 3].itertuples():
        rows_by_county[county_names[int(row.JUD)]].append(
            (
                str(int(row.SIRUTA)),
                normalized_name(row.DENLOC),
                administrative_units[int(row.SIRSUP)]["name"],
            )
        )

    catalogue = {}
    for county, rows in sorted(
        rows_by_county.items(), key=lambda item: romanian_sort_key(item[0])
    ):
        name_counts = Counter(name for _, name, _ in rows)
        catalogue[county] = [
            [
                code,
                name,
                f"{name} — {administrative}" if name_counts[name] > 1 else name,
            ]
            for code, name, administrative in sorted(
                rows,
                key=lambda item: (romanian_sort_key(item[1]), romanian_sort_key(item[2])),
            )
        ]

    catalogue_bytes = json.dumps(
        catalogue, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if hierarchy_destination is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".siruta-catalogue-", delete=False
        ) as staged_catalogue:
            staged_catalogue.write(catalogue_bytes)
            staged_catalogue_path = Path(staged_catalogue.name)
        try:
            os.replace(staged_catalogue_path, destination)
        finally:
            staged_catalogue_path.unlink(missing_ok=True)
        return

    # Invariant: every searchable NIV 3 locality keeps the official NIV 2
    # parent and both TIP codes. Alias resolution must never infer hierarchy
    # from a display label or from name uniqueness within a county.
    hierarchy = {
        "schema_version": 2,
        "source": _release_metadata(
            source_bytes=source_bytes,
            catalogue_bytes=catalogue_bytes,
            county_count=len(catalogue),
            locality_count=sum(len(rows) for rows in catalogue.values()),
            release_id=release_id,
            source_url=source_url,
            published_date=published_date,
            retrieved_at=retrieved_at,
        ),
        "localities": [
            {
                "siruta_code": str(int(row.SIRUTA)),
                "county": county_names[int(row.JUD)],
                "locality_name": normalized_name(row.DENLOC),
                "locality_tip": int(row.TIP),
                "parent_siruta": str(int(row.SIRSUP)),
                "parent_name": administrative_units[int(row.SIRSUP)]["name"],
                "parent_tip": administrative_units[int(row.SIRSUP)]["tip"],
            }
            for row in data[data.NIV == 3].itertuples()
        ],
    }
    hierarchy_bytes = json.dumps(
        hierarchy, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    _write_new_candidate_pair(
        catalogue_bytes=catalogue_bytes,
        hierarchy_bytes=hierarchy_bytes,
        destination=destination,
        hierarchy_destination=hierarchy_destination,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--hierarchy-destination", type=Path)
    parser.add_argument("--release-id")
    parser.add_argument("--source-url")
    parser.add_argument("--published-date")
    parser.add_argument("--retrieved-at")
    arguments = parser.parse_args()
    write_catalog(
        arguments.source,
        arguments.destination,
        arguments.hierarchy_destination,
        release_id=arguments.release_id,
        source_url=arguments.source_url,
        published_date=arguments.published_date,
        retrieved_at=arguments.retrieved_at,
    )
