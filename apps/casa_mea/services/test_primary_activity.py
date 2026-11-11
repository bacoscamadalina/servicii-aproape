"""Contracts for MF 2024 predominant-activity evidence."""

import hashlib
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, TestCase, override_settings

from .caen import CAEN_MAPPING_HASH, CAEN_MAPPING_VERSION, category_for_caen
from .catalogue_activation import audit_run_for_catalogue, catalogue_state
from .importers.locality_aliases import RULES_PATH, sha256_file
from .importers.onrc import _sha256
from .importers.onrc_statuses import POLICY_VERSION as STATUS_POLICY_VERSION
from .models import (
    BusinessCaen, BusinessCategory, BusinessIdentity, BusinessStatus,
    CatalogueScope, ImportRun, PrimaryActivityEvidence,
    RegisteredBusinessSnapshot, SourceSnapshot,
)
from .staging import LOCALITY_POLICY, pilot_scope_key, refined_scope_key

from .importers.primary_activity import (
    POLICY_NAME,
    MF_MANIFEST_PATH,
    POLICY_HASH,
    POLICY_VERSION,
    build_primary_activity_index,
    classify_primary_activity,
    normalize_cui,
    registration_year,
    refine_run_from_shadow_index,
    verify_primary_activity_manifest,
)


class PrimaryActivityEvidenceTests(SimpleTestCase):
    def _write_bundle(self, directory: Path) -> tuple[Path, dict[str, Path]]:
        data_one = directory / "one.txt"
        data_two = directory / "two.txt"
        schema_one = directory / "one.csv"
        schema_two = directory / "two.csv"
        data_one.write_text("CUI,CAEN,I1\n1,4941,0\n2,8130,0\n3,4120,0\n", encoding="utf-8")
        data_two.write_text("CUI,CAEN,I1\n2,8130,1\n3,4321,1\nX,8130,1\n", encoding="utf-8")
        schema_one.write_text("CUI;CUI\nCAEN;CAEN\nIndicator;i1\n", encoding="utf-8")
        schema_two.write_text("CUI;CUI\nCAEN;CAEN\nIndicator;i1\n", encoding="utf-8")
        files = {
            "data_bl_bs_sl": data_one,
            "schema_bl_bs_sl": schema_one,
            "data_uu": data_two,
            "schema_uu": schema_two,
        }
        resources = []
        for kind, path in files.items():
            resources.append({
                "kind": kind,
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "url": f"https://example.test/{path.name}",
            })
        manifest = {
            "schema_version": 1,
            "provider": "Ministerul Finanțelor",
            "dataset_year": 2024,
            "dataset_url": "https://example.test/mf",
            "license": "CC BY 4.0",
            "retrieved_at": "2026-08-24T10:17:00+03:00",
            "semantic_basis": {
                "url": "https://legislatie.just.ro/example",
                "meaning": POLICY_NAME,
            },
            "parser_contract": {
                "encoding": "utf-8-sig",
                "data_delimiter": ",",
                "schema_delimiter": ";",
                "required_leading_columns": ["CUI", "CAEN"],
                "caen_version": "2",
                "meaning": POLICY_NAME,
            },
            "resources": resources,
        }
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, files

    def test_manifest_pins_data_and_schema_and_detects_schema_drift(self):
        with TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest_path, files = self._write_bundle(directory)
            _manifest, paths, evidence_hash = verify_primary_activity_manifest(
                manifest_path, directory
            )
            self.assertEqual(set(paths), set(files))
            self.assertEqual(len(evidence_hash), 64)

            files["schema_uu"].write_text("CUI;CUI\nALT;ALT\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Hash sau dimensiune"):
                verify_primary_activity_manifest(manifest_path, directory)

    def test_manifest_rejects_duplicate_resource_kinds(self):
        with TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest_path, _files = self._write_bundle(directory)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["resources"].append(dict(manifest["resources"][0]))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact două date și două scheme"):
                verify_primary_activity_manifest(manifest_path, directory)

    def test_index_deduplicates_identical_and_quarantines_conflicts(self):
        with TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            manifest_path, _files = self._write_bundle(directory)
            _manifest, paths, _hash = verify_primary_activity_manifest(
                manifest_path, directory
            )
            database_path, counters = build_primary_activity_index(paths, directory / "scratch")
            with sqlite3.connect(database_path) as database:
                self.assertEqual(
                    database.execute("SELECT cui, caen FROM primary_activity ORDER BY cui").fetchall(),
                    [("1", "4941"), ("2", "8130")],
                )
                self.assertEqual(
                    database.execute("SELECT cui FROM conflicting_activity").fetchall(),
                    [("3",)],
                )
                resource, fingerprint = database.execute(
                    "SELECT resource, fingerprint FROM primary_activity WHERE cui='2'"
                ).fetchone()
                expected = hashlib.sha256(
                    (f"{resource}\0" + "2\0" + "8130").encode()
                ).hexdigest()
                self.assertEqual(fingerprint, expected)
            self.assertEqual(counters["identical_duplicate_rows"], 1)
            self.assertEqual(counters["conflicting_cui"], 1)
            self.assertEqual(counters["malformed_rows"], 1)

    def test_transport_is_excluded_and_gardening_is_included(self):
        known = {"4941", "8130"}
        self.assertEqual(
            classify_primary_activity(
                cui=normalize_cui("22813454"), duplicate_onrc_cui=False,
                conflicting_mf=False, caen="4941", known_caen_v2=known,
            ),
            ("unmapped_reported_activity", ""),
        )
        self.assertEqual(
            classify_primary_activity(
                cui="2", duplicate_onrc_cui=False, conflicting_mf=False,
                caen="8130", known_caen_v2=known,
            ),
            ("mapped_include", "gradinarit"),
        )

    def test_furniture_primary_activity_is_included_across_caen_revisions(self):
        self.assertEqual(
            classify_primary_activity(
                cui="47545942", duplicate_onrc_cui=False,
                conflicting_mf=False, caen="3109", known_caen_v2={"3109"},
            ),
            ("mapped_include", "tamplarie"),
        )
        self.assertEqual(category_for_caen("3109", "2"), "tamplarie")
        self.assertEqual(category_for_caen("3100", "3"), "tamplarie")

    def test_join_fail_closed_precedence(self):
        known = {"8130"}
        cases = (
            ({"cui": "", "caen": "8130"}, "missing_or_invalid_onrc_cui"),
            ({"cui": "1", "duplicate_onrc_cui": True, "caen": "8130"}, "duplicate_onrc_cui"),
            ({"cui": "1", "conflicting_mf": True, "caen": "8130"}, "conflicting_mf_activity"),
            ({"cui": "1", "caen": None}, "no_mf_2024_filing"),
            ({"cui": "1", "caen": "9999"}, "unknown_caen_v2"),
        )
        for overrides, expected in cases:
            arguments = {
                "cui": "1", "duplicate_onrc_cui": False,
                "conflicting_mf": False, "caen": "8130", "known_caen_v2": known,
            }
            arguments.update(overrides)
            self.assertEqual(classify_primary_activity(**arguments)[0], expected)

    def test_registration_year_supports_legacy_and_compact_numbers(self):
        self.assertEqual(registration_year(None, "J27/1561/2007"), "2007")
        self.assertEqual(registration_year(None, "F2025000012271"), "2025")
        self.assertEqual(registration_year(None, "invalid"), "unknown")


class RefinedCatalogueContractTests(TestCase):
    def setUp(self):
        self.onrc = SourceSnapshot.objects.create(
            provider="ONRC", snapshot_date="2026-07-08",
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/onrc", license_label="CC BY 4.0",
            verified_resources={},
        )
        self.mf = SourceSnapshot.objects.create(
            provider="MF_FINANCIAL_STATEMENTS_2024", snapshot_date="2024-12-31",
            manifest_sha256=_sha256(MF_MANIFEST_PATH),
            dataset_url="https://data.gov.ro/mf", license_label="CC BY 4.0",
            verified_resources={
                "data_bl_bs_sl": {"sha256": "b" * 64},
                "data_uu": {"sha256": "c" * 64},
            },
        )
        base_key, categories = pilot_scope_key("Cluj", [
            "constructii", "instalatii", "gradinarit", "curatenie",
            "tamplarie", "reparatii",
        ])
        self.base = ImportRun.objects.create(
            snapshot=self.onrc, scope_key=base_key, county="Cluj",
            categories=categories, caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=STATUS_POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
            state=ImportRun.State.SUCCEEDED,
        )
        refined_key, _categories = refined_scope_key(
            self.base, self.mf, policy_version=POLICY_VERSION,
            policy_hash=POLICY_HASH, evidence_year=2024,
        )
        self.run = ImportRun.objects.create(
            snapshot=self.onrc, scope_key=refined_key, county="Cluj",
            categories=categories, caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=STATUS_POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
            scope_contract_version=2, refined_from_run=self.base,
            activity_evidence_snapshot=self.mf,
            activity_evidence_policy_version=POLICY_VERSION,
            activity_evidence_policy_hash=POLICY_HASH,
            activity_evidence_year=2024, state=ImportRun.State.SUCCEEDED,
        )
        identity = BusinessIdentity.objects.create(registration_number="J12/1/2020")
        self.record = RegisteredBusinessSnapshot.objects.create(
            import_run=self.run, business=identity, legal_name="CASA CLUJ SRL",
            cui="2", registered_office_siruta="54984", locality_match="exact",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="f" * 32,
        )
        BusinessStatus.objects.create(business_snapshot=self.record, code="1048")
        BusinessCaen.objects.create(
            business_snapshot=self.record, version="2", code="4120"
        )
        BusinessCategory.objects.create(
            business_snapshot=self.record, category="constructii"
        )
        resource = "data_bl_bs_sl"
        PrimaryActivityEvidence.objects.create(
            business_snapshot=self.record, resource_kind=resource,
            cui_join_fingerprint=hashlib.sha256(b"2").hexdigest(),
            caen_version="2", caen_code="4120", reporting_year=2024,
            source_row_fingerprint=hashlib.sha256(
                (f"{resource}\0" + "2\0" + "4120").encode()
            ).hexdigest(),
        )
        self.run.counters = {
            "staged_businesses": 1, "staged_statuses": 1,
            "staged_caen": 1, "staged_categories": 1,
            "staged_activity_evidence": 1, "quarantine_records": 0,
        }
        self.run.save(update_fields=("counters",))

    def test_v2_audit_checks_policy_authorization_and_fingerprints(self):
        self.assertEqual(audit_run_for_catalogue(self.run)["staged_businesses"], 1)

        self.run.activity_evidence_policy_hash = "0" * 64
        self.run.save(update_fields=("activity_evidence_policy_hash",))
        with self.assertRaisesRegex(ValueError, "Politica"):
            audit_run_for_catalogue(self.run)
        self.run.activity_evidence_policy_hash = POLICY_HASH
        self.run.save(update_fields=("activity_evidence_policy_hash",))

        evidence = self.record.primary_activity_evidence
        evidence.source_row_fingerprint = "0" * 64
        evidence.save(update_fields=("source_row_fingerprint",))
        with self.assertRaisesRegex(ValueError, "Fingerprintul"):
            audit_run_for_catalogue(self.run)

    @override_settings(DEBUG=True)
    def test_reader_fails_closed_when_mf_snapshot_is_rejected(self):
        CatalogueScope.objects.create(
            provider="ONRC", county="Cluj", current_run=self.run,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
        )
        self.assertEqual(catalogue_state("Cluj").status, "active")
        self.mf.state = SourceSnapshot.State.REJECTED
        self.mf.save(update_fields=("state",))
        self.assertEqual(catalogue_state("Cluj").status, "unavailable")

    def test_clone_is_atomic_in_shape_and_idempotent(self):
        identity = self.record.business
        self.run.business_snapshots.all().delete()
        self.run.state = ImportRun.State.PENDING
        self.run.counters = {}
        self.run.save(update_fields=("state", "counters"))
        source = RegisteredBusinessSnapshot.objects.create(
            import_run=self.base, business=identity, legal_name="CASA CLUJ SRL",
            cui="2", registered_office_siruta="54984", locality_match="exact",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="f" * 32,
        )
        BusinessStatus.objects.create(business_snapshot=source, code="1048")
        BusinessCaen.objects.create(business_snapshot=source, version="2", code="4120")
        BusinessCategory.objects.create(business_snapshot=source, category="constructii")
        with TemporaryDirectory() as raw_directory:
            database_path = Path(raw_directory) / "shadow.sqlite3"
            resource = "data_bl_bs_sl"
            source_fingerprint = hashlib.sha256(
                (f"{resource}\0" + "2\0" + "4120").encode()
            ).hexdigest()
            with sqlite3.connect(database_path) as database:
                database.execute(
                    "CREATE TABLE candidate (id INTEGER, county TEXT)"
                )
                database.execute(
                    "CREATE TABLE candidate_decision (candidate_id INTEGER, "
                    "decision TEXT, caen TEXT, category TEXT, resource TEXT, "
                    "source_fingerprint TEXT)"
                )
                database.execute(
                    "INSERT INTO candidate VALUES (?, 'Cluj')", (source.pk,)
                )
                database.execute(
                    "INSERT INTO candidate_decision VALUES "
                    "(?, 'mapped_include', '4120', 'constructii', ?, ?)",
                    (source.pk, resource, source_fingerprint),
                )
            counters, changed = refine_run_from_shadow_index(
                self.base, self.run, database_path
            )
            second_counters, changed_again = refine_run_from_shadow_index(
                self.base, self.run, database_path
            )
        self.assertTrue(changed)
        self.assertFalse(changed_again)
        self.assertEqual(counters, second_counters)
        self.assertEqual(counters["staged_businesses"], 1)
        cloned = self.run.business_snapshots.get()
        self.assertEqual(cloned.categories.get().category, "constructii")
        self.assertEqual(cloned.primary_activity_evidence.caen_code, "4120")
