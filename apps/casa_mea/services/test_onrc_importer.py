"""Tests for manifest-pinned ONRC auditing and conservative CAEN rules."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from .caen import CAEN_CATEGORY_CODES, CAEN_CATEGORY_INDEX, category_for_caen
from .importers.onrc import (
    APP_ROOT,
    EXPECTED_HEADERS,
    RESOURCE_KINDS,
    audit_snapshot,
    read_validated_rows,
    registered_office_match_status,
    verify_manifest,
)
from .importers.onrc_localities import build_locality_candidates
from .importers.locality_aliases import (
    HIERARCHY_PATH,
    RULES_PATH,
    _normalized_registered_office_match_with_approved_aliases,
    load_alias_rules,
    propose_siruta_alias,
    registered_office_match_with_approved_aliases,
    sha256_file,
)
from .locations import CATALOGUE_PATH
from .importers.onrc_statuses import audit_status_policy, proposed_status_decision


def write_export(path: Path, header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> None:
    """Write a minimal ONRC-shaped fixture with the official delimiter and BOM."""

    lines = ("^".join(header), *("^".join(row) for row in rows))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def write_audit_fixtures(root: Path) -> dict[str, Path]:
    """Create one internally coherent six-resource ONRC test bundle."""

    paths = {kind: root / f"{kind}.csv" for kind in RESOURCE_KINDS}
    firm_base = [""] * len(EXPECTED_HEADERS["firms"])
    registration_index = EXPECTED_HEADERS["firms"].index("COD_INMATRICULARE")
    firm_rows = []
    for registration_number in ("J12/1/2020", "J12/2/2020", "J12/1/2020"):
        row = firm_base.copy()
        row[registration_index] = registration_number
        firm_rows.append(tuple(row))
    write_export(paths["firms"], EXPECTED_HEADERS["firms"], tuple(firm_rows))
    write_export(
        paths["activities"],
        EXPECTED_HEADERS["activities"],
        (
            ("J12/1/2020", "4321", "2"),
            ("J12/2/2020", "4752", "3"),
            ("J99/9/2020", "8130", "3"),
            ("J12/1/2020", "4321", "9"),
        ),
    )
    write_export(
        paths["statuses"],
        EXPECTED_HEADERS["statuses"],
        (("J12/1/2020", "1048"), ("J99/9/2020", "1084")),
    )
    write_export(
        paths["caen_dictionary"],
        EXPECTED_HEADERS["caen_dictionary"],
        (
            ("F", "", "43", "432", "4321", "Instalații electrice", "2"),
            ("G", "", "47", "475", "4752", "Comerț", "3"),
            ("O", "", "81", "813", "8130", "Peisagistică", "3"),
        ),
    )
    write_export(
        paths["status_dictionary"],
        EXPECTED_HEADERS["status_dictionary"],
        (("1048", "funcțiune"), ("1084", "radiată")),
    )
    write_export(
        paths["caen_versions"],
        EXPECTED_HEADERS["caen_versions"],
        (
            ("0", "Versiunea 1998"),
            ("1", "Versiunea 2003"),
            ("2", "Versiunea 2008"),
            ("3", "Versiunea 2025"),
        ),
    )
    return paths


class CaenMappingTests(SimpleTestCase):
    def test_only_explicit_direct_service_codes_are_mapped(self):
        self.assertEqual(category_for_caen("4321", "2"), "instalatii")
        self.assertEqual(category_for_caen("4323", "3"), "instalatii")
        self.assertEqual(category_for_caen("4335", "3"), "constructii")
        self.assertEqual(category_for_caen("8130", "3"), "gradinarit")
        self.assertEqual(category_for_caen("1623", "2"), "tamplarie")
        self.assertEqual(category_for_caen("2512", "2"), "tamplarie")
        self.assertEqual(category_for_caen("3109", "2"), "tamplarie")
        self.assertEqual(category_for_caen("3100", "3"), "tamplarie")
        self.assertEqual(category_for_caen("4752", "3"), "")
        self.assertEqual(category_for_caen("2223", "2"), "")
        self.assertEqual(category_for_caen("1629", "2"), "")
        self.assertEqual(category_for_caen("2511", "2"), "")
        self.assertEqual(category_for_caen("3103", "2"), "")
        self.assertEqual(category_for_caen("9529", "3"), "")

    def test_no_caen_rule_can_belong_to_two_categories(self):
        rule_count = sum(
            len(codes)
            for categories in CAEN_CATEGORY_CODES.values()
            for codes in categories.values()
        )
        self.assertEqual(len(CAEN_CATEGORY_INDEX), rule_count)


class OnrcAuditTests(SimpleTestCase):
    def test_status_policy_is_conservative_and_order_independent(self):
        self.assertEqual(
            proposed_status_decision(("1048",)), "eligible_function_only"
        )
        self.assertEqual(
            proposed_status_decision(("2069", "1048")),
            "needs_review_mixed_function",
        )
        self.assertEqual(
            proposed_status_decision(("1048", "1084")), "excluded_radiated"
        )
        self.assertEqual(
            proposed_status_decision(()), "quarantined_without_function"
        )

    def test_status_audit_partitions_every_coherent_firm(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            report = audit_status_policy(
                paths["firms"],
                paths["statuses"],
                paths["status_dictionary"],
                root,
            )

        self.assertEqual(report["source_firms"]["coherent_unique_firms"], 2)
        self.assertEqual(
            report["decision_counts"],
            {
                "eligible_function_only": 1,
                "quarantined_without_function": 1,
            },
        )
        self.assertEqual(sum(report["decision_counts"].values()), 2)
        self.assertEqual(
            report["source_statuses"]["link_accounting"]["raw_rows"]["orphan"], 1
        )

    def test_status_audit_accounts_for_every_link_and_duplicate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            base = [""] * len(EXPECTED_HEADERS["firms"])
            registration = EXPECTED_HEADERS["firms"].index("COD_INMATRICULARE")
            name = EXPECTED_HEADERS["firms"].index("DENUMIRE")
            conflicting_a = base.copy()
            conflicting_a[registration], conflicting_a[name] = "J12/1/2020", "A SRL"
            conflicting_b = conflicting_a.copy()
            conflicting_b[name] = "B SRL"
            coherent = base.copy()
            coherent[registration], coherent[name] = "J12/2/2020", "C SRL"
            write_export(
                paths["firms"],
                EXPECTED_HEADERS["firms"],
                (
                    tuple(conflicting_a),
                    tuple(conflicting_b),
                    tuple(coherent),
                    tuple(coherent),
                ),
            )
            write_export(
                paths["statuses"],
                EXPECTED_HEADERS["statuses"],
                (
                    ("J12/1/2020", "1048"),
                    ("J12/2/2020", "1048"),
                    ("J12/2/2020", "1048"),
                    ("J99/9/2020", "1084"),
                ),
            )
            report = audit_status_policy(
                paths["firms"], paths["statuses"], paths["status_dictionary"], root
            )

        self.assertEqual(report["source_firms"]["coherent_unique_firms"], 1)
        self.assertEqual(report["source_firms"]["noncoherent_unique_firms"], 1)
        self.assertEqual(report["source_statuses"]["duplicate_rows"], 1)
        self.assertEqual(
            report["source_statuses"]["link_accounting"],
            {
                "raw_rows": {
                    "coherent_firm": 2,
                    "noncoherent_firm": 1,
                    "orphan": 1,
                },
                "distinct_memberships": {
                    "coherent_firm": 1,
                    "noncoherent_firm": 1,
                    "orphan": 1,
                },
                "noncoherent_unique_firms_with_status": 1,
            },
        )
        self.assertEqual(report["decision_counts"], {"eligible_function_only": 1})

    def test_status_audit_quarantines_unknown_and_extra_column_rows(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            write_export(
                paths["statuses"],
                EXPECTED_HEADERS["statuses"],
                (("J12/1/2020", "9999"), ("J12/2/2020", "1048", "EXTRA")),
            )
            report = audit_status_policy(
                paths["firms"], paths["statuses"], paths["status_dictionary"], root
            )

        self.assertEqual(
            report["source_statuses"]["rejections"],
            {"invalid_structure": 1, "unknown_status": 1},
        )
        self.assertEqual(
            report["decision_counts"], {"quarantined_without_function": 2}
        )

    def test_status_dictionary_reports_duplicates_and_rejects_conflicts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            write_export(
                paths["status_dictionary"],
                EXPECTED_HEADERS["status_dictionary"],
                (
                    ("1048", "funcțiune"),
                    ("1048", "funcțiune"),
                    ("1084", "radiată", "EXTRA"),
                ),
            )
            report = audit_status_policy(
                paths["firms"], paths["statuses"], paths["status_dictionary"], root
            )
            self.assertEqual(
                report["nomenclature"]["rejections"],
                {"identical_duplicate_code": 1, "invalid_row": 1},
            )

            write_export(
                paths["status_dictionary"],
                EXPECTED_HEADERS["status_dictionary"],
                (("1048", "funcțiune"), ("1048", "radiată")),
            )
            with self.assertRaisesRegex(ValueError, "coduri conflictuale"):
                audit_status_policy(
                    paths["firms"],
                    paths["statuses"],
                    paths["status_dictionary"],
                    root,
                )

    def test_registered_office_matching_is_exact_and_never_guesses_duplicates(self):
        self.assertEqual(registered_office_match_status("România", "Cluj", "Cluj-Napoca"), "exact")
        self.assertEqual(registered_office_match_status("România", "Cluj", "Bălcești"), "ambiguous")
        self.assertEqual(registered_office_match_status("România", "Cluj", "Localitate inventată"), "unmatched")
        self.assertEqual(registered_office_match_status("România", "", "Cluj-Napoca"), "missing")
        self.assertEqual(registered_office_match_status("Ungaria", "Cluj", "Cluj-Napoca"), "foreign")
        self.assertEqual(registered_office_match_status("", "Cluj", "Cluj-Napoca"), "missing_country")

    def test_audit_uses_nomenclatures_and_counts_unique_coherent_firms(self):
        with TemporaryDirectory() as directory:
            paths = write_audit_fixtures(Path(directory))
            report = audit_snapshot(paths, Path(directory))

        self.assertEqual(report["firms"]["rows"], 3)
        self.assertEqual(report["firms"]["unique_registration_numbers"], 2)
        self.assertEqual(report["firms"]["coherent_unique_firms"], 2)
        self.assertEqual(report["firms"]["identical_duplicate_registration_numbers"], 1)
        self.assertEqual(report["firms"]["conflicting_duplicate_registration_numbers"], 0)
        self.assertEqual(report["activities"]["orphan_rows"], 1)
        self.assertEqual(report["activities"]["rejections"]["invalid_structure"], 1)
        self.assertEqual(
            report["activities"]["rejections"]["unmapped_supported_activity"], 1
        )
        self.assertEqual(report["activities"]["caen_versions"], {"2008": 1, "2025": 2})
        self.assertEqual(
            report["activities"]["mapped_activity_rows"],
            {"gradinarit": 1, "instalatii": 1},
        )
        self.assertEqual(
            report["activities"]["unique_coherent_firms_per_category"],
            {"instalatii": 1},
        )
        self.assertEqual(report["statuses"]["orphan_rows"], 1)
        self.assertEqual(report["statuses"]["firms_with_function_status"], 1)

    def test_unknown_caen_and_status_codes_are_quarantined(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            write_export(
                paths["activities"],
                EXPECTED_HEADERS["activities"],
                (("J12/1/2020", "9999", "3"),),
            )
            write_export(
                paths["statuses"],
                EXPECTED_HEADERS["statuses"],
                (("J12/1/2020", "9999"),),
            )
            report = audit_snapshot(paths, root)

        self.assertEqual(report["activities"]["rejections"]["unknown_caen"], 1)
        self.assertEqual(report["statuses"]["rejections"]["unknown_status"], 1)

    def test_schema_drift_stops_the_audit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "changed.csv"
            write_export(path, ("COD_INMATRICULARE", "COLOANA_NOUA"), ())

            with self.assertRaisesRegex(ValueError, "Schema ONRC neașteptată"):
                tuple(read_validated_rows(path, "statuses"))

    def test_literal_quotes_in_company_names_do_not_change_row_structure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "firms.csv"
            row = [""] * len(EXPECTED_HEADERS["firms"])
            row[EXPECTED_HEADERS["firms"].index("DENUMIRE")] = 'ATELIER "CASA BUNĂ" SRL'
            row[EXPECTED_HEADERS["firms"].index("COD_INMATRICULARE")] = "J12/3/2020"
            write_export(path, EXPECTED_HEADERS["firms"], (tuple(row),))

            parsed = tuple(read_validated_rows(path, "firms"))

        self.assertEqual(parsed[0]["DENUMIRE"], 'ATELIER "CASA BUNĂ" SRL')

    def test_manifest_hash_mismatch_stops_before_audit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            resources = {}
            for kind, path in paths.items():
                resources[kind] = {
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            siruta_path = APP_ROOT / "services/data/localities.json"
            manifest = {
                "schema_version": 1,
                "resources": resources,
                "siruta_catalogue": {
                    "repository_path": "services/data/localities.json",
                    "source_date": "2025-01-01",
                    "size_bytes": siruta_path.stat().st_size,
                    "sha256": hashlib.sha256(siruta_path.read_bytes()).hexdigest(),
                },
                "siruta_hierarchy": {
                    "repository_path": "services/data/localities_hierarchy.json",
                    "source_date": "2025-01-01",
                    "size_bytes": (APP_ROOT / "services/data/localities_hierarchy.json").stat().st_size,
                    "sha256": hashlib.sha256(
                        (APP_ROOT / "services/data/localities_hierarchy.json").read_bytes()
                    ).hexdigest(),
                },
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            paths["statuses"].write_text("alterat", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Integritatea resursei statuses"):
                verify_manifest(manifest_path, root)

    def test_locality_candidates_are_aggregated_without_company_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_audit_fixtures(root)
            report = build_locality_candidates(paths["firms"], root)

        self.assertEqual(report["source_rows"], 3)
        self.assertEqual(report["coherent_unique_firms"], 2)
        self.assertEqual(report["candidate_groups"], 1)
        self.assertEqual(report["candidates"][0]["coherent_firm_count"], 2)
        self.assertNotIn("registration_number", report["candidates"][0])

    def test_alias_proposals_require_explicit_form_and_unique_siruta_target(self):
        enabled = {
            "municipality_prefix",
            "town_prefix",
            "commune_prefix",
            "village_with_parent",
            "town_locality_with_parent",
        }
        self.assertEqual(
            propose_siruta_alias(
                "românia", "cluj", "municipiul cluj-napoca", enabled
            ),
            ("54984", "municipality_prefix"),
        )
        self.assertEqual(
            propose_siruta_alias(
                "românia", "cluj", "sat bălcești, comuna beliș", enabled
            ),
            ("56032", "village_with_parent"),
        )
        self.assertIsNone(
            propose_siruta_alias("românia", "cluj", "bălcești", enabled)
        )
        self.assertIsNone(
            propose_siruta_alias(
                "ungaria", "cluj", "municipiul cluj-napoca", enabled
            )
        )

    def test_alias_proposals_never_ignore_the_official_parent(self):
        enabled = {"commune_prefix", "village_with_parent"}
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "dâmbovița", "sat mănăstirea, comuna crevedia", enabled
            )
        )
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "argeș", "comuna mioarele", enabled
            )
        )

    def test_only_application_approved_hierarchy_aliases_resolve(self):
        self.assertEqual(
            registered_office_match_with_approved_aliases(
                "România", "Iaşi", "Municipiul Iaşi"
            ),
            ("hierarchy_alias", "95079"),
        )
        self.assertEqual(
            registered_office_match_with_approved_aliases(
                "România", "Iaşi", "Loc. Hârlău, Oraş Hârlău"
            ),
            ("unmatched", ""),
        )

    def test_reviewed_neamt_spelling_alias_is_county_bound_and_hierarchy_checked(self):
        enabled = {"municipality_prefix", "town_locality_with_parent"}
        self.assertEqual(
            propose_siruta_alias(
                "românia", "neamț", "municipiul piatra neamț", enabled
            ),
            ("120735", "municipality_prefix"),
        )
        self.assertEqual(
            propose_siruta_alias(
                "românia", "neamț", "loc. târgu neamț, oraș târgu neamț", enabled
            ),
            ("121064", "town_locality_with_parent"),
        )
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "neamț", "loc. bicaz, oraș roznov", enabled
            )
        )
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "constanța", "loc. eforie sud, oraș eforie", enabled
            )
        )
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "olt", "municipiul piatra neamț", enabled
            )
        )
        self.assertEqual(
            registered_office_match_with_approved_aliases(
                "România", "Neamț", "Municipiul Piatra Neamț"
            ),
            ("hierarchy_alias", "120735"),
        )
        self.assertEqual(
            registered_office_match_with_approved_aliases(
                "România", "Neamț", "Loc. Târgu Neamț, Oraș Târgu Neamț"
            ),
            ("hierarchy_alias", "121064"),
        )
        self.assertEqual(
            registered_office_match_with_approved_aliases(
                "România", "Constanța", "Loc. Eforie Sud, Oraș Eforie"
            ),
            ("unmatched", ""),
        )

    def test_administrative_name_aliases_reject_duplicate_sources_and_cycles(self):
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        with TemporaryDirectory() as directory:
            temporary_rules = Path(directory) / "rules.json"
            duplicate = json.loads(json.dumps(rules))
            duplicate["administrative_name_aliases"].append(
                dict(duplicate["administrative_name_aliases"][0])
            )
            temporary_rules.write_text(json.dumps(duplicate), encoding="utf-8")
            with patch(
                "services.importers.locality_aliases.RULES_PATH", temporary_rules
            ):
                load_alias_rules.cache_clear()
                with self.assertRaisesRegex(ValueError, "duplicată"):
                    load_alias_rules()

            cyclic = json.loads(json.dumps(rules))
            cyclic["administrative_name_aliases"] = [
                {
                    "county": "neamț",
                    "source": "roman",
                    "target": "piatra-neamț",
                    "proposal_enabled": True,
                    "application_approved": False,
                },
                {
                    "county": "neamț",
                    "source": "piatra-neamț",
                    "target": "roman",
                    "proposal_enabled": True,
                    "application_approved": False,
                },
            ]
            temporary_rules.write_text(json.dumps(cyclic), encoding="utf-8")
            with patch(
                "services.importers.locality_aliases.RULES_PATH", temporary_rules
            ):
                load_alias_rules.cache_clear()
                with self.assertRaisesRegex(ValueError, "Ciclu"):
                    load_alias_rules()
        load_alias_rules.cache_clear()

    def test_alias_rules_and_repeated_forms_are_cached(self):
        load_alias_rules.cache_clear()
        _normalized_registered_office_match_with_approved_aliases.cache_clear()
        with patch(
            "services.importers.locality_aliases.sha256_file",
            wraps=sha256_file,
        ) as digest:
            first = registered_office_match_with_approved_aliases(
                "România", "Iaşi", "Municipiul Iaşi"
            )
            second = registered_office_match_with_approved_aliases(
                "România", "Iași", "Municipiul Iași"
            )

        self.assertEqual(first, second)
        self.assertEqual(digest.call_count, 2)
        self.assertEqual(
            {call.args[0] for call in digest.call_args_list},
            {HIERARCHY_PATH, CATALOGUE_PATH},
        )

    def test_alias_proposals_require_matching_parent_and_locality_types(self):
        enabled = {"town_prefix", "village_with_parent"}
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "cluj", "oraș bălcești", enabled
            )
        )
        self.assertIsNone(
            propose_siruta_alias(
                "românia", "timiș", "sat sinmihaiu roman, comuna sânmihaiu român", enabled
            )
        )
