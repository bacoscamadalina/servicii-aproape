"""Deterministic, read-only comparison of two generated SIRUTA catalogues."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


HIERARCHY_FIELDS = (
    "siruta_code",
    "county",
    "locality_name",
    "locality_tip",
    "parent_siruta",
    "parent_name",
    "parent_tip",
)
TRACKED_FIELDS = (*HIERARCHY_FIELDS[1:], "display_label")


class SirutaRefreshError(ValueError):
    """Reject a malformed or internally inconsistent generated catalogue pair."""


@dataclass(frozen=True)
class SirutaSnapshot:
    """Validated metadata and code-indexed hierarchy for one SIRUTA release."""

    catalogue_sha256: str
    hierarchy_sha256: str
    hierarchy_schema_version: int
    source: dict
    county_count: int
    localities: dict[str, dict]

    def summary(self) -> dict:
        """Return deterministic metadata without duplicating the full hierarchy."""

        return {
            "catalogue_sha256": self.catalogue_sha256,
            "hierarchy_sha256": self.hierarchy_sha256,
            "hierarchy_schema_version": self.hierarchy_schema_version,
            "source": self.source,
            "county_count": self.county_count,
            "locality_count": len(self.localities),
        }


@dataclass(frozen=True)
class SirutaRefreshAudit:
    """Complete semantic change set between the pinned and candidate releases."""

    current: SirutaSnapshot
    candidate: SirutaSnapshot
    added: tuple[dict, ...]
    removed: tuple[dict, ...]
    changed: tuple[dict, ...]
    changed_fields: tuple[tuple[str, int], ...]

    @property
    def content_hash_changed(self) -> bool:
        """Return whether deploying the candidate changes a persisted source pin."""

        return (
            self.current.catalogue_sha256 != self.candidate.catalogue_sha256
            or self.current.hierarchy_sha256 != self.candidate.hierarchy_sha256
        )

    @property
    def catalogue_hash_changed(self) -> bool:
        """Return whether provider drafts and publications receive a new source pin."""

        return self.current.catalogue_sha256 != self.candidate.catalogue_sha256

    @property
    def hierarchy_hash_changed(self) -> bool:
        """Return whether ONRC locality reconciliation receives a new hierarchy pin."""

        return self.current.hierarchy_sha256 != self.candidate.hierarchy_sha256

    @property
    def has_semantic_changes(self) -> bool:
        """Return whether a searchable locality was added, removed, or changed."""

        return bool(self.added or self.removed or self.changed)

    def as_dict(self) -> dict:
        """Return a stable JSON report suitable for human review and CI artifacts."""

        status = (
            "semantic_change"
            if self.has_semantic_changes
            else "hash_only_change"
            if self.content_hash_changed
            else "unchanged"
        )
        required_rollout_steps = (
            [
                "Actualizează SIRUTA_CATALOGUE_VERSION la release_id-ul candidatului.",
                "Regenerează și revizuiește manifestele ONRC și regulile de alias localitate.",
                "Revalidează runurile ONRC și pinurile profilurilor înainte de activare.",
            ]
            if self.content_hash_changed
            else []
        )
        return {
            "report_schema_version": 1,
            "status": status,
            "current": self.current.summary(),
            "candidate": self.candidate.summary(),
            "changes": {
                "added_count": len(self.added),
                "removed_count": len(self.removed),
                "changed_count": len(self.changed),
                "changed_fields": dict(self.changed_fields),
                "added": list(self.added),
                "removed": list(self.removed),
                "changed": list(self.changed),
            },
            "impact": {
                "content_hash_changed": self.content_hash_changed,
                "catalogue_hash_changed": self.catalogue_hash_changed,
                "hierarchy_hash_changed": self.hierarchy_hash_changed,
                "requires_coordinated_rollout": self.content_hash_changed,
                "provider_source_pins_will_change": self.catalogue_hash_changed,
                "required_application_version": self.candidate.source.get("release_id"),
                "required_rollout_steps": required_rollout_steps,
                "automatic_install_permitted": False,
            },
        }


def _read_json_and_sha256(path: Path) -> tuple[object, str]:
    """Parse and hash one immutable byte read so identity matches audited content."""

    try:
        content = path.read_bytes()
        return json.loads(content.decode("utf-8")), hashlib.sha256(content).hexdigest()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SirutaRefreshError(f"Sursa SIRUTA nu poate fi citită: {error}") from error


def _sort_code(code: str) -> tuple[int, int | str]:
    """Sort ordinary numeric SIRUTA identifiers naturally and malformed ones last."""

    return (0, int(code)) if code.isdigit() else (1, code)


def load_siruta_snapshot(
    catalogue_path: Path,
    hierarchy_path: Path,
    *,
    require_release_metadata: bool = False,
) -> SirutaSnapshot:
    """Load and cross-check a generated UI catalogue and hierarchy as one unit."""

    catalogue, catalogue_sha256 = _read_json_and_sha256(catalogue_path)
    hierarchy, hierarchy_sha256 = _read_json_and_sha256(hierarchy_path)

    if not isinstance(catalogue, dict) or not catalogue:
        raise SirutaRefreshError("Catalogul SIRUTA trebuie să conțină județe.")
    hierarchy_schema_version = (
        hierarchy.get("schema_version") if isinstance(hierarchy, dict) else None
    )
    valid_schemas = {2} if require_release_metadata else {1, 2}
    if hierarchy_schema_version not in valid_schemas:
        expected = "2 cu metadate de release" if require_release_metadata else "1 sau 2"
        raise SirutaRefreshError(f"Ierarhia SIRUTA trebuie să folosească schema {expected}.")
    source = hierarchy.get("source")
    rows = hierarchy.get("localities")
    if not isinstance(source, dict) or not isinstance(rows, list):
        raise SirutaRefreshError("Ierarhia SIRUTA nu conține sursa și localitățile.")
    if hierarchy_schema_version == 2:
        required_source = {
            "dataset",
            "release_id",
            "sheet",
            "source_url",
            "published_date",
            "retrieved_at",
            "raw_sha256",
            "generator_policy_version",
            "catalogue_sha256",
            "county_count",
            "locality_count",
        }
        if set(source) != required_source:
            raise SirutaRefreshError("Metadatele release-ului SIRUTA schema 2 sunt incomplete.")
        string_fields = required_source - {"county_count", "locality_count"}
        if (
            not all(isinstance(source[field], str) and source[field] for field in string_fields)
            or not all(
                isinstance(source[field], int)
                and not isinstance(source[field], bool)
                and source[field] > 0
                for field in ("county_count", "locality_count")
            )
            or len(source["raw_sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in source["raw_sha256"])
            or len(source["catalogue_sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in source["catalogue_sha256"]
            )
            or source["generator_policy_version"] != "siruta-localities-v2"
            or source["dataset"] != f"SIRUTA S1 {source['release_id']}"
            or not source["source_url"].startswith(("https://", "http://"))
        ):
            raise SirutaRefreshError("Valorile metadatelor SIRUTA schema 2 sunt invalide.")
        try:
            published_date = date.fromisoformat(source["published_date"])
            retrieved_at = datetime.fromisoformat(
                source["retrieved_at"].replace("Z", "+00:00")
            )
        except ValueError as error:
            raise SirutaRefreshError(
                "Datele metadatelor SIRUTA trebuie să fie ISO 8601."
            ) from error
        if retrieved_at.utcoffset() is None:
            raise SirutaRefreshError("retrieved_at SIRUTA trebuie să includă fusul orar.")
        if published_date > retrieved_at.date():
            raise SirutaRefreshError(
                "published_date SIRUTA nu poate fi după retrieved_at."
            )

    catalogue_index: dict[str, tuple[str, str, str]] = {}
    for county, localities in catalogue.items():
        if not isinstance(county, str) or not county or not isinstance(localities, list):
            raise SirutaRefreshError("Structura județelor din catalog este invalidă.")
        for item in localities:
            if (
                not isinstance(item, list)
                or len(item) != 3
                or not all(isinstance(value, str) and value for value in item)
            ):
                raise SirutaRefreshError(f"Intrare SIRUTA invalidă în județul {county}.")
            code, name, _label = item
            if code in catalogue_index:
                raise SirutaRefreshError(f"Cod SIRUTA duplicat în catalog: {code}.")
            catalogue_index[code] = (county, name, _label)

    if hierarchy_schema_version == 2 and (
        source["catalogue_sha256"] != catalogue_sha256
        or source["county_count"] != len(catalogue)
        or source["locality_count"] != len(catalogue_index)
    ):
        raise SirutaRefreshError("Metadatele release-ului nu corespund catalogului generat.")

    hierarchy_index: dict[str, dict] = {}
    parent_identities: dict[str, tuple[str, str, int]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(HIERARCHY_FIELDS):
            raise SirutaRefreshError("O localitate din ierarhie nu respectă schema 1.")
        code = row["siruta_code"]
        string_values = (
            code,
            row["county"],
            row["locality_name"],
            row["parent_siruta"],
            row["parent_name"],
        )
        if (
            not all(isinstance(value, str) and value for value in string_values)
            or not code.isdigit()
            or not row["parent_siruta"].isdigit()
            or not all(
                isinstance(row[field], int)
                and not isinstance(row[field], bool)
                and row[field] > 0
                for field in ("locality_tip", "parent_tip")
            )
        ):
            raise SirutaRefreshError(f"Valori SIRUTA invalide pentru codul {code!r}.")
        if code in hierarchy_index:
            raise SirutaRefreshError(f"Cod SIRUTA duplicat în ierarhie: {code}.")
        if code == row["parent_siruta"]:
            raise SirutaRefreshError(f"Localitatea {code} nu poate fi propriul părinte.")
        parent_identity = (row["county"], row["parent_name"], row["parent_tip"])
        known_parent = parent_identities.setdefault(row["parent_siruta"], parent_identity)
        if known_parent != parent_identity:
            raise SirutaRefreshError(
                f"Părintele SIRUTA {row['parent_siruta']} are identități contradictorii."
            )
        hierarchy_index[code] = row

    if set(catalogue_index) != set(hierarchy_index):
        missing_ui = sorted(set(hierarchy_index) - set(catalogue_index), key=_sort_code)
        missing_hierarchy = sorted(set(catalogue_index) - set(hierarchy_index), key=_sort_code)
        raise SirutaRefreshError(
            "Catalogul și ierarhia au coduri diferite "
            f"(lipsă UI: {missing_ui[:5]}, lipsă ierarhie: {missing_hierarchy[:5]})."
        )
    inconsistent = [
        code
        for code, (county, name, _label) in catalogue_index.items()
        if (county, name)
        != (hierarchy_index[code]["county"], hierarchy_index[code]["locality_name"])
    ]
    if inconsistent:
        first_inconsistent = sorted(inconsistent, key=_sort_code)[0]
        raise SirutaRefreshError(
            f"Catalogul și ierarhia descriu diferit codul {first_inconsistent}."
        )

    enriched_index = {
        code: {**row, "display_label": catalogue_index[code][2]}
        for code, row in hierarchy_index.items()
    }
    return SirutaSnapshot(
        catalogue_sha256=catalogue_sha256,
        hierarchy_sha256=hierarchy_sha256,
        hierarchy_schema_version=hierarchy_schema_version,
        source=source,
        county_count=len(catalogue),
        localities=enriched_index,
    )


def audit_siruta_refresh(
    *,
    current_catalogue_path: Path,
    current_hierarchy_path: Path,
    candidate_catalogue_path: Path,
    candidate_hierarchy_path: Path,
) -> SirutaRefreshAudit:
    """Compare two validated releases without changing files, caches, or database state."""

    current = load_siruta_snapshot(current_catalogue_path, current_hierarchy_path)
    candidate = load_siruta_snapshot(
        candidate_catalogue_path,
        candidate_hierarchy_path,
        require_release_metadata=True,
    )
    current_counties = {row["county"] for row in current.localities.values()}
    candidate_counties = {row["county"] for row in candidate.localities.values()}
    if candidate_counties != current_counties or candidate.county_count != current.county_count:
        raise SirutaRefreshError(
            "Candidatul nu păstrează setul național complet de județe al catalogului curent."
        )
    current_codes = set(current.localities)
    candidate_codes = set(candidate.localities)
    added = tuple(
        candidate.localities[code]
        for code in sorted(candidate_codes - current_codes, key=_sort_code)
    )
    removed = tuple(
        current.localities[code]
        for code in sorted(current_codes - candidate_codes, key=_sort_code)
    )
    changed_fields: Counter[str] = Counter()
    changed = []
    for code in sorted(current_codes & candidate_codes, key=_sort_code):
        before = current.localities[code]
        after = candidate.localities[code]
        fields = {
            field: {"from": before[field], "to": after[field]}
            for field in TRACKED_FIELDS
            if before[field] != after[field]
        }
        if fields:
            changed_fields.update(fields.keys())
            changed.append({"siruta_code": code, "fields": fields})
    return SirutaRefreshAudit(
        current=current,
        candidate=candidate,
        added=added,
        removed=removed,
        changed=tuple(changed),
        changed_fields=tuple((field, changed_fields[field]) for field in TRACKED_FIELDS),
    )
