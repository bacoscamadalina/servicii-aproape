"""Deterministic, reviewable proposals from ONRC locality forms to SIRUTA."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from services.importers.onrc import normalize_administrative_name
from services.locations import CATALOGUE_PATH, read_locations_catalogue


RULES_PATH = Path(__file__).resolve().parents[1] / "data/onrc/locality_alias_rules.json"
HIERARCHY_PATH = Path(__file__).resolve().parents[1] / "data/localities_hierarchy.json"


def sha256_file(path: Path) -> str:
    """Return a bounded-memory SHA-256 digest for provenance checks."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _siruta_alias_index() -> dict[str, list[dict[str, object]]]:
    """Index official locality and parent hierarchy under each county."""

    hierarchy = json.loads(HIERARCHY_PATH.read_text(encoding="utf-8"))
    if hierarchy.get("schema_version") != 1:
        raise ValueError("Versiunea ierarhiei SIRUTA nu este suportată")
    index: dict[str, list[dict[str, object]]] = {}
    for entry in hierarchy["localities"]:
        county = normalize_administrative_name(entry["county"])
        index.setdefault(county, []).append(
            {
                "siruta_code": entry["siruta_code"],
                "locality_name": normalize_administrative_name(entry["locality_name"]),
                "locality_tip": entry["locality_tip"],
                "parent_name": normalize_administrative_name(entry["parent_name"]),
                "parent_tip": entry["parent_tip"],
            }
        )
    return index


@lru_cache(maxsize=1)
def load_alias_rules() -> dict[str, object]:
    """Load the versioned proposal rules committed with the application."""

    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    if rules.get("schema_version") != 1:
        raise ValueError("Versiunea regulilor de aliasuri nu este suportată")
    if sha256_file(HIERARCHY_PATH) != rules.get("source_siruta_hierarchy_sha256"):
        raise ValueError("Ierarhia SIRUTA diferă de versiunea fixată în reguli")
    if sha256_file(CATALOGUE_PATH) != rules.get("source_siruta_sha256"):
        raise ValueError("Catalogul SIRUTA diferă de versiunea fixată în reguli")
    aliases = rules.get("administrative_name_aliases", [])
    if not isinstance(aliases, list):
        raise ValueError("Aliasurile administrative trebuie să fie o listă")
    alias_map: dict[tuple[str, str], str] = {}
    for alias in aliases:
        county, source, target = (
            alias.get("county"),
            alias.get("source"),
            alias.get("target"),
        )
        if not all(isinstance(value, str) and value for value in (county, source, target)):
            raise ValueError("Alias administrativ incomplet")
        if any(
            value != normalize_administrative_name(value)
            for value in (county, source, target)
        ):
            raise ValueError("Aliasurile administrative trebuie stocate normalizat")
        key = (county, source)
        if key in alias_map:
            raise ValueError("Sursă de alias administrativ duplicată")
        official_targets = [
            entry
            for entry in _siruta_alias_index().get(county, [])
            if entry["locality_name"] == target
        ]
        if len(official_targets) != 1:
            raise ValueError("Ținta aliasului nu este o localitate SIRUTA unică")
        alias_map[key] = target
    for county, source in alias_map:
        seen = {source}
        target = alias_map[(county, source)]
        while (county, target) in alias_map:
            if target in seen:
                raise ValueError("Ciclu în aliasurile administrative")
            seen.add(target)
            target = alias_map[(county, target)]
    return rules


def propose_siruta_alias(
    country: str,
    county: str,
    locality: str,
    enabled_rules: set[str],
    *,
    application_only: bool = False,
) -> tuple[str, str] | None:
    """Return a unique SIRUTA code and explicit method, never a fuzzy guess."""

    if country not in {"românia", "romania"}:
        return None
    entries = _siruta_alias_index().get(county, [])
    if not entries:
        return None
    rules = load_alias_rules()
    reviewed_name_aliases = {
        (entry["county"], entry["source"]): entry["target"]
        for entry in rules.get("administrative_name_aliases", [])
        if (
            entry.get("application_approved") is True
            if application_only
            else entry.get("proposal_enabled") is True
        )
    }

    def reviewed_name(name: str) -> str:
        """Apply only an explicit, county-bound administrative spelling alias."""

        return reviewed_name_aliases.get((county, name), name)

    # Each administrative prefix has one hierarchy contract. Name uniqueness
    # alone is never evidence that an ONRC locality belongs to that parent.
    prefix_patterns = (
        ("municipality_prefix", r"^municipiul (.+)$", {9}, {1, 4}),
        ("town_prefix", r"^oraș(?:ul)? (.+)$", {17}, {2}),
        ("commune_prefix", r"^comuna (.+)$", {22}, {3}),
    )
    for method, pattern, locality_tips, parent_tips in prefix_patterns:
        match = re.fullmatch(pattern, locality)
        if method in enabled_rules and match:
            target_name = reviewed_name(match.group(1).strip())
            matches = [
                entry["siruta_code"]
                for entry in entries
                if entry["locality_name"] == target_name
                and entry["parent_name"] == target_name
                and entry["locality_tip"] in locality_tips
                and entry["parent_tip"] in parent_tips
            ]
            return (matches[0], method) if len(matches) == 1 else None

    if "town_locality_with_parent" in enabled_rules:
        locality_with_parent = re.fullmatch(
            r"^loc\. (.+), (oraș(?:ul)?) (.+)$", locality
        )
        if locality_with_parent:
            target_name, parent_prefix, parent_name = (
                part.strip() for part in locality_with_parent.groups()
            )
            target_name = reviewed_name(target_name)
            parent_name = reviewed_name(parent_name)
            if target_name != parent_name:
                return None
            hierarchy_contract = {
                "oraș": ({17}, {2}),
                "orașul": ({17}, {2}),
            }
            locality_tips, parent_tips = hierarchy_contract[parent_prefix]
            matches = [
                entry["siruta_code"]
                for entry in entries
                if entry["locality_name"] == target_name
                and entry["parent_name"] == parent_name
                and entry["locality_tip"] in locality_tips
                and entry["parent_tip"] in parent_tips
            ]
            return (
                (matches[0], "town_locality_with_parent")
                if len(matches) == 1
                else None
            )

    if "village_with_parent" not in enabled_rules:
        return None
    village = re.fullmatch(
        r"^sat (.+), (comuna|oraș(?:ul)?|municipiul) (.+)$", locality
    )
    if not village:
        return None
    target_name, parent_prefix, parent_name = (
        part.strip() for part in village.groups()
    )
    target_name = reviewed_name(target_name)
    parent_name = reviewed_name(parent_name)
    hierarchy_contract = {
        "comuna": ({22, 23}, {3}),
        "oraș": ({19}, {2}),
        "orașul": ({19}, {2}),
        "municipiul": ({11}, {1, 4}),
    }
    locality_tips, parent_tips = hierarchy_contract[parent_prefix]
    matches = [
        entry["siruta_code"]
        for entry in entries
        if entry["locality_name"] == target_name
        and entry["parent_name"] == parent_name
        and entry["locality_tip"] in locality_tips
        and entry["parent_tip"] in parent_tips
    ]
    return (matches[0], "village_with_parent") if len(matches) == 1 else None


@lru_cache(maxsize=50_000)
def _normalized_registered_office_match_with_approved_aliases(
    country: str, county: str, locality: str
) -> tuple[str, str]:
    """Resolve one normalized form with bounded reuse across repeated ONRC rows."""

    from services.importers.onrc import registered_office_match

    baseline_status, baseline_code = registered_office_match(country, county, locality)
    if baseline_status != "unmatched":
        return baseline_status, baseline_code
    rules = load_alias_rules()
    approved_rules = {
        rule["id"]
        for rule in rules["rules"]
        if rule.get("application_approved") is True
        and (
            not rule.get("application_counties")
            or county in rule["application_counties"]
        )
    }
    proposed = propose_siruta_alias(
        country,
        county,
        locality,
        approved_rules,
        application_only=True,
    )
    return ("hierarchy_alias", proposed[0]) if proposed else (baseline_status, "")


def registered_office_match_with_approved_aliases(
    country: str, county: str, locality: str
) -> tuple[str, str]:
    """Normalize once, then resolve exact or explicitly approved hierarchy aliases."""

    return _normalized_registered_office_match_with_approved_aliases(
        normalize_administrative_name(country),
        normalize_administrative_name(county),
        normalize_administrative_name(locality),
    )


def build_alias_proposals(
    candidate_report: dict[str, object],
    source_candidates_sha256: str | None = None,
) -> dict[str, object]:
    """Propose aliases and quantify deterministic uplift without applying them."""

    rules = load_alias_rules()
    if (
        candidate_report["source_siruta"]["sha256"]
        != rules["source_siruta_sha256"]
    ):
        raise ValueError("Regulile și inventarul folosesc versiuni SIRUTA diferite")
    enabled_rules = {
        rule["id"]
        for rule in rules["rules"]
        if rule.get("proposal_enabled") is True
    }
    rationale = {rule["id"]: rule["rationale"] for rule in rules["rules"]}
    labels_by_code = {
        code: label
        for localities in read_locations_catalogue().values()
        for code, _name, label in localities
    }
    method_groups = {method: 0 for method in sorted(enabled_rules)}
    method_firms = {method: 0 for method in sorted(enabled_rules)}
    proposals = []
    unresolved_groups = 0
    unresolved_firms = 0

    for candidate in candidate_report["results"]["candidates"]:
        if candidate["baseline_status"] != "unmatched":
            continue
        proposed = propose_siruta_alias(
            candidate["country"],
            candidate["county"],
            candidate["locality"],
            enabled_rules,
        )
        if not proposed:
            unresolved_groups += 1
            unresolved_firms += candidate["coherent_firm_count"]
            continue
        siruta_code, method = proposed
        method_groups[method] += 1
        method_firms[method] += candidate["coherent_firm_count"]
        proposals.append(
            {
                "candidate_id": candidate["candidate_id"],
                "country": candidate["country"],
                "county": candidate["county"],
                "locality": candidate["locality"],
                "sector": candidate["sector"],
                "coherent_firm_count": candidate["coherent_firm_count"],
                "siruta_code": siruta_code,
                "siruta_label": labels_by_code[siruta_code],
                "method": method,
                "rationale": rationale[method],
                "decision": rules["review_state"],
            }
        )

    baseline_exact = candidate_report["results"]["baseline_status_unique_firms"]["exact"]
    proposed_firms = sum(method_firms.values())
    return {
        "report_schema_version": 1,
        "snapshot_date": candidate_report["snapshot_date"],
        "source_candidates_sha256": source_candidates_sha256,
        "source_firms": candidate_report["source_firms"],
        "source_siruta": candidate_report["source_siruta"],
        "source_siruta_hierarchy": {
            "sha256": rules["source_siruta_hierarchy_sha256"],
            "size_bytes": HIERARCHY_PATH.stat().st_size,
        },
        "rules_sha256": sha256_file(RULES_PATH),
        "rules_schema_version": rules["schema_version"],
        "rules_review_state": rules["review_state"],
        "validation_state": rules["review_state"],
        "validated_at": rules["reviewed_at"],
        "validated_by": rules["reviewed_by"],
        "rules_application_approved": {
            rule["id"]: rule.get("application_approved") is True
            for rule in rules["rules"]
        },
        "baseline_exact_unique_firms": baseline_exact,
        "proposed_additional_exact_unique_firms": proposed_firms,
        "projected_if_all_proposals_approved_unique_firms": baseline_exact + proposed_firms,
        "proposal_groups_by_method": method_groups,
        "proposal_firms_by_method": method_firms,
        "unresolved_unmatched_groups": unresolved_groups,
        "unresolved_unmatched_firms": unresolved_firms,
        "proposals": proposals,
    }
