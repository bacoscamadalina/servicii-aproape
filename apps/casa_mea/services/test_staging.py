"""Persistence and visibility contracts for the isolated ONRC pilot staging area."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from unittest.mock import patch
from unittest import skipUnless

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from .caen import CAEN_MAPPING_HASH, CAEN_MAPPING_VERSION
from .importers.onrc_statuses import POLICY_VERSION
from .importers.onrc_pilot import claim_import_run, import_onrc_pilot_into_staging
from .importers.onrc_counties import import_onrc_counties_into_staging
from .importers.locality_aliases import RULES_PATH, sha256_file
from .models import (
    BusinessIdentity,
    ImportQuarantine,
    ImportRun,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from .staging import LOCALITY_POLICY, pilot_scope_key, prepare_pilot_import_run
from .test_onrc_importer import EXPECTED_HEADERS, write_audit_fixtures, write_export


class StagingModelTests(TestCase):
    def setUp(self):
        self.snapshot = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date="2026-07-08",
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/dataset/firme-08-07-2026",
            license_label="CC BY 4.0",
            verified_resources={},
        )

    def create_run(self, scope_key: str, state: str) -> ImportRun:
        return ImportRun.objects.create(
            snapshot=self.snapshot,
            scope_key=scope_key,
            county="Cluj",
            categories=["constructii", "instalatii"],
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=POLICY_VERSION,
            state=state,
        )

    def create_record(
        self,
        run: ImportRun,
        business: BusinessIdentity,
        eligibility: str,
    ) -> RegisteredBusinessSnapshot:
        return RegisteredBusinessSnapshot.objects.create(
            import_run=run,
            business=business,
            legal_name="CASA TEST SRL",
            registered_country_raw="România",
            registered_county_raw="Cluj",
            registered_locality_raw="Cluj-Napoca",
            registered_office_siruta="54984",
            locality_match="exact",
            status_eligibility=eligibility,
            source_fingerprint="f" * 32,
        )

    def test_scope_key_is_order_independent_and_policy_pinned(self):
        first, categories = pilot_scope_key(
            "Cluj", ["instalatii", "constructii", "instalatii"]
        )
        second, _ = pilot_scope_key("Cluj", ["constructii", "instalatii"])

        self.assertEqual(first, second)
        self.assertEqual(categories, ["constructii", "instalatii"])
        self.assertEqual(len(first), 64)

    def test_one_business_can_belong_to_overlapping_runs_but_not_twice_to_one(self):
        business = BusinessIdentity.objects.create(registration_number="J12/1/2020")
        first = self.create_run("1" * 64, ImportRun.State.SUCCEEDED)
        second = self.create_run("2" * 64, ImportRun.State.SUCCEEDED)
        self.create_record(
            first, business, RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE
        )
        self.create_record(
            second, business, RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_record(
                first, business, RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE
            )

    def test_staging_candidates_exclude_incomplete_and_noneligible_runs(self):
        eligible = BusinessIdentity.objects.create(registration_number="J12/1/2020")
        mixed = BusinessIdentity.objects.create(registration_number="J12/2/2020")
        incomplete = BusinessIdentity.objects.create(registration_number="J12/3/2020")
        succeeded = self.create_run("1" * 64, ImportRun.State.SUCCEEDED)
        running = self.create_run("2" * 64, ImportRun.State.RUNNING)
        expected = self.create_record(
            succeeded,
            eligible,
            RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
        )
        self.create_record(
            succeeded,
            mixed,
            RegisteredBusinessSnapshot.StatusEligibility.NEEDS_REVIEW,
        )
        self.create_record(
            running,
            incomplete,
            RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
        )

        self.assertEqual(
            list(RegisteredBusinessSnapshot.objects.staging_candidates(succeeded)),
            [expected],
        )

        self.snapshot.state = SourceSnapshot.State.REJECTED
        self.snapshot.save(update_fields=("state",))
        self.assertFalse(
            RegisteredBusinessSnapshot.objects.staging_candidates(succeeded).exists()
        )

    def test_quarantine_key_is_idempotent_within_one_run(self):
        run = self.create_run("1" * 64, ImportRun.State.RUNNING)
        fields = {
            "import_run": run,
            "resource_kind": "firms",
            "reason": "conflicting_payload",
            "record_key_hash": "b" * 64,
        }
        ImportQuarantine.objects.create(**fields)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ImportQuarantine.objects.create(**fields)


class PilotPreparationTests(TestCase):
    def test_preparation_is_idempotent_and_never_activates_publication(self):
        with TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            manifest = {
                "snapshot_date": "2026-07-08",
                "dataset_url": "https://data.gov.ro/dataset/firme-08-07-2026",
                "license": "CC BY 4.0",
            }
            first, created = prepare_pilot_import_run(
                manifest,
                manifest_path,
                {"firms": {"sha256": "a" * 64}},
                "Cluj",
                ["instalatii", "constructii"],
            )
            second, created_again = prepare_pilot_import_run(
                manifest,
                manifest_path,
                {"firms": {"sha256": "a" * 64}},
                "Cluj",
                ["constructii", "instalatii"],
            )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.state, ImportRun.State.PENDING)
        self.assertFalse(
            RegisteredBusinessSnapshot.objects.staging_candidates(first).exists()
        )

    def test_preparation_rejects_rejected_snapshot_and_scope_drift(self):
        with TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            manifest = {
                "snapshot_date": "2026-07-08",
                "dataset_url": "https://data.gov.ro/dataset/firme-08-07-2026",
                "license": "CC BY 4.0",
            }
            run, _ = prepare_pilot_import_run(
                manifest, manifest_path, {}, "Cluj", ["constructii"]
            )
            run.caen_mapping_hash = "0" * 64
            run.save(update_fields=("caen_mapping_hash",))
            with self.assertRaisesRegex(ValueError, "contractului scope-ului"):
                prepare_pilot_import_run(
                    manifest, manifest_path, {}, "Cluj", ["constructii"]
                )

            run.caen_mapping_hash = CAEN_MAPPING_HASH
            run.save(update_fields=("caen_mapping_hash",))
            run.snapshot.state = SourceSnapshot.State.REJECTED
            run.snapshot.save(update_fields=("state",))
            with self.assertRaisesRegex(ValueError, "starea verificată"):
                prepare_pilot_import_run(
                    manifest, manifest_path, {}, "Cluj", ["constructii"]
                )


class PilotImportTests(TestCase):
    def build_fixture_and_run(self, root: Path):
        paths = write_audit_fixtures(root)
        indexes = {name: EXPECTED_HEADERS["firms"].index(name) for name in (
            "DENUMIRE",
            "COD_INMATRICULARE",
            "ADR_TARA",
            "ADR_JUDET",
            "ADR_LOCALITATE",
        )}

        def firm(registration: str, name: str, county: str, locality: str):
            row = [""] * len(EXPECTED_HEADERS["firms"])
            row[indexes["DENUMIRE"]] = name
            row[indexes["COD_INMATRICULARE"]] = registration
            row[indexes["ADR_TARA"]] = "România"
            row[indexes["ADR_JUDET"]] = county
            row[indexes["ADR_LOCALITATE"]] = locality
            return tuple(row)

        write_export(
            paths["firms"],
            EXPECTED_HEADERS["firms"],
            (
                firm("J22/1/2020", "ELIGIBIL SRL", "Iași", "Municipiul Iaşi"),
                firm("J22/2/2020", "RADIAT SRL", "Iași", "Iași"),
                firm("J22/3/2020", "CONFLICT A SRL", "Iași", "Iași"),
                firm("J22/3/2020", "CONFLICT B SRL", "Iași", "Iași"),
                firm("J22/4/2020", "FĂRĂ STARE SRL", "Iași", "Iași"),
                firm("J12/1/2020", "ALT JUDEȚ SRL", "Cluj", "Cluj-Napoca"),
            ),
        )
        write_export(
            paths["activities"],
            EXPECTED_HEADERS["activities"],
            (
                ("J22/1/2020", "4321", "2"),
                ("J22/1/2020", "4321", "2"),
                ("J22/1/2020", "4321", "2", "EXTRA"),
                ("J22/1/2020", "4321"),
                ("J22/1/2020", "9999", "2"),
                ("J22/2/2020", "4321", "2"),
                ("J22/3/2020", "4321", "2"),
                ("J22/4/2020", "4321", "2"),
                ("J12/1/2020", "4321", "2"),
            ),
        )
        write_export(
            paths["statuses"],
            EXPECTED_HEADERS["statuses"],
            (
                ("J22/1/2020", "1048"),
                ("J22/1/2020", "1048"),
                ("J22/1/2020", "1048", "EXTRA"),
                ("J22/2/2020", "1048"),
                ("J22/2/2020", "1084"),
                ("J22/3/2020", "1048"),
                ("J22/4/2020", "9999"),
                ("J12/1/2020", "1048"),
            ),
        )
        snapshot = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date="2026-07-08",
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/dataset/test",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        scope_key, categories = pilot_scope_key(
            "Iași", ["constructii", "instalatii"]
        )
        run = ImportRun.objects.create(
            snapshot=snapshot,
            scope_key=scope_key,
            county="Iași",
            categories=categories,
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
        )
        return paths, run

    def test_import_stages_only_exact_function_only_candidates_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, run = self.build_fixture_and_run(root)
            counters, changed = import_onrc_pilot_into_staging(run, paths, root)
            unchanged_counters, changed_again = import_onrc_pilot_into_staging(
                ImportRun.objects.get(pk=run.pk), paths, root
            )

        run.refresh_from_db()
        self.assertTrue(changed)
        self.assertFalse(changed_again)
        self.assertEqual(counters, unchanged_counters)
        self.assertEqual(run.state, ImportRun.State.SUCCEEDED)
        self.assertEqual(counters["candidate_coherent_firms"], 3)
        self.assertEqual(counters["candidate_conflicting_firms"], 1)
        self.assertEqual(counters["staged_businesses"], 1)
        self.assertEqual(counters["invalid_activity_rows"], 2)
        self.assertEqual(counters["unknown_caen_rows"], 1)
        self.assertEqual(counters["invalid_status_rows"], 1)
        self.assertEqual(counters["unknown_status_rows"], 1)
        self.assertEqual(counters["staged_statuses"], 1)
        self.assertEqual(counters["staged_caen"], 1)
        self.assertEqual(counters["staged_categories"], 1)
        record = run.business_snapshots.get()
        self.assertEqual(record.legal_name, "ELIGIBIL SRL")
        self.assertEqual(record.registered_office_siruta, "95079")
        self.assertEqual(record.locality_match, "hierarchy_alias")
        self.assertEqual(list(record.statuses.values_list("code", flat=True)), ["1048"])
        self.assertEqual(
            list(record.categories.values_list("category", flat=True)), ["instalatii"]
        )
        self.assertEqual(run.quarantine_records.count(), 1)

    def test_multi_county_import_scans_once_and_isolates_county_rows(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, iasi = self.build_fixture_and_run(root)
            scope_key, categories = pilot_scope_key(
                "Cluj", ["constructii", "instalatii"]
            )
            cluj = ImportRun.objects.create(
                snapshot=iasi.snapshot,
                scope_key=scope_key,
                county="Cluj",
                categories=categories,
                caen_mapping_version=CAEN_MAPPING_VERSION,
                caen_mapping_hash=CAEN_MAPPING_HASH,
                status_policy_version=POLICY_VERSION,
                locality_policy=LOCALITY_POLICY,
                locality_rules_hash=sha256_file(RULES_PATH),
            )
            results = import_onrc_counties_into_staging(
                [iasi, cluj], paths, lambda: None, root
            )

        self.assertEqual(results[iasi.pk]["counters"]["staged_businesses"], 1)
        self.assertEqual(results[cluj.pk]["counters"]["staged_businesses"], 1)
        self.assertEqual(
            iasi.business_snapshots.get().registered_county_raw, "Iași"
        )
        self.assertEqual(
            cluj.business_snapshots.get().registered_county_raw, "Cluj"
        )
        self.assertEqual(
            results[iasi.pk]["counters"]["source_firm_rows"],
            results[cluj.pk]["counters"]["source_firm_rows"],
        )

    def test_multi_county_post_scan_drift_leaves_every_run_unclaimed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, run = self.build_fixture_and_run(root)
            with self.assertRaisesRegex(ValueError, "source drift"):
                import_onrc_counties_into_staging(
                    [run],
                    paths,
                    lambda: (_ for _ in ()).throw(
                        ValueError("source drift")
                    ),
                    root,
                )

        run.refresh_from_db()
        self.assertEqual(run.state, ImportRun.State.PENDING)
        self.assertIsNone(run.claim_token)
        self.assertFalse(run.business_snapshots.exists())

    def test_multi_county_failure_isolated_and_next_county_continues(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, iasi = self.build_fixture_and_run(root)
            scope_key, categories = pilot_scope_key(
                "Cluj", ["constructii", "instalatii"]
            )
            cluj = ImportRun.objects.create(
                snapshot=iasi.snapshot,
                scope_key=scope_key,
                county="Cluj",
                categories=categories,
                caen_mapping_version=CAEN_MAPPING_VERSION,
                caen_mapping_hash=CAEN_MAPPING_HASH,
                status_policy_version=POLICY_VERSION,
                locality_policy=LOCALITY_POLICY,
                locality_rules_hash=sha256_file(RULES_PATH),
            )
            original_bulk_create = RegisteredBusinessSnapshot.objects.bulk_create
            calls = 0

            def fail_first(rows, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("first county failed")
                return original_bulk_create(rows, **kwargs)

            with patch.object(
                RegisteredBusinessSnapshot.objects,
                "bulk_create",
                side_effect=fail_first,
            ):
                results = import_onrc_counties_into_staging(
                    [iasi, cluj], paths, lambda: None, root
                )

        iasi.refresh_from_db()
        cluj.refresh_from_db()
        self.assertEqual(iasi.state, ImportRun.State.FAILED)
        self.assertIn("first county failed", results[iasi.pk]["error"])
        self.assertEqual(cluj.state, ImportRun.State.SUCCEEDED)
        self.assertEqual(cluj.business_snapshots.count(), 1)

    def test_multi_county_conflict_cross_county_is_quarantined_in_both(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, iasi = self.build_fixture_and_run(root)
            indexes = {
                name: EXPECTED_HEADERS["firms"].index(name)
                for name in (
                    "DENUMIRE",
                    "COD_INMATRICULARE",
                    "ADR_TARA",
                    "ADR_JUDET",
                    "ADR_LOCALITATE",
                )
            }

            def firm(county, locality):
                row = [""] * len(EXPECTED_HEADERS["firms"])
                row[indexes["DENUMIRE"]] = "CONFLICT JUDEȚ SRL"
                row[indexes["COD_INMATRICULARE"]] = "J00/1/2020"
                row[indexes["ADR_TARA"]] = "România"
                row[indexes["ADR_JUDET"]] = county
                row[indexes["ADR_LOCALITATE"]] = locality
                return tuple(row)

            write_export(
                paths["firms"],
                EXPECTED_HEADERS["firms"],
                (firm("Iași", "Iași"), firm("Cluj", "Cluj-Napoca")),
            )
            write_export(
                paths["activities"],
                EXPECTED_HEADERS["activities"],
                (("J00/1/2020", "4321", "2"),),
            )
            write_export(
                paths["statuses"],
                EXPECTED_HEADERS["statuses"],
                (("J00/1/2020", "1048"),),
            )
            scope_key, categories = pilot_scope_key(
                "Cluj", ["constructii", "instalatii"]
            )
            cluj = ImportRun.objects.create(
                snapshot=iasi.snapshot,
                scope_key=scope_key,
                county="Cluj",
                categories=categories,
                caen_mapping_version=CAEN_MAPPING_VERSION,
                caen_mapping_hash=CAEN_MAPPING_HASH,
                status_policy_version=POLICY_VERSION,
                locality_policy=LOCALITY_POLICY,
                locality_rules_hash=sha256_file(RULES_PATH),
            )
            results = import_onrc_counties_into_staging(
                [iasi, cluj], paths, lambda: None, root
            )

        for run in (iasi, cluj):
            run.refresh_from_db()
            self.assertEqual(run.state, ImportRun.State.SUCCEEDED)
            self.assertFalse(run.business_snapshots.exists())
            self.assertEqual(run.quarantine_records.count(), 1)
            self.assertEqual(
                results[run.pk]["counters"]["candidate_conflicting_firms"], 1
            )

    def test_multi_county_lost_claim_reports_concurrent_failed_state_as_error(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, run = self.build_fixture_and_run(root)

            def concurrent_failure(_run):
                ImportRun.objects.filter(pk=run.pk).update(state=ImportRun.State.FAILED)
                raise ValueError("claim lost")

            with patch(
                "services.importers.onrc_counties.claim_import_run",
                side_effect=concurrent_failure,
            ):
                results = import_onrc_counties_into_staging(
                    [run], paths, lambda: None, root
                )

        self.assertEqual(results[run.pk]["state"], ImportRun.State.FAILED)
        self.assertIn("claim lost", results[run.pk]["error"])

    def test_import_failure_rolls_back_rows_and_marks_run_failed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, run = self.build_fixture_and_run(root)
            with patch.object(
                RegisteredBusinessSnapshot.objects,
                "bulk_create",
                side_effect=RuntimeError("write failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "write failed"):
                    import_onrc_pilot_into_staging(run, paths, root)
            run.refresh_from_db()
            self.assertEqual(run.state, ImportRun.State.FAILED)
            self.assertFalse(run.business_snapshots.exists())
            self.assertFalse(run.quarantine_records.exists())
            self.assertFalse(BusinessIdentity.objects.exists())
            counters, changed = import_onrc_pilot_into_staging(run, paths, root)

        run.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(run.state, ImportRun.State.SUCCEEDED)
        self.assertEqual(run.attempt_count, 2)
        self.assertEqual(counters["staged_businesses"], 1)

    def test_import_refuses_every_provenance_drift_before_claim(self):
        drift = {
            "scope_key": "0" * 64,
            "categories": ["instalatii", "constructii"],
            "caen_mapping_version": "old",
            "caen_mapping_hash": "0" * 64,
            "status_policy_version": "old",
            "locality_policy": "aliases",
            "locality_rules_hash": "0" * 64,
        }
        for field, value in drift.items():
            with self.subTest(field=field), TemporaryDirectory() as directory:
                root = Path(directory)
                paths, run = self.build_fixture_and_run(root)
                setattr(run, field, value)
                run.save(update_fields=(field,))
                with self.assertRaisesRegex(ValueError, "politicilor curente"):
                    import_onrc_pilot_into_staging(run, paths, root)
                run.refresh_from_db()
                self.assertEqual(run.state, ImportRun.State.PENDING)
                self.assertEqual(run.attempt_count, 0)
                snapshot = run.snapshot
                run.delete()
                snapshot.delete()


@skipUnless(connection.vendor == "postgresql", "Necesită PostgreSQL real")
class PostgresRunClaimTests(TransactionTestCase):
    reset_sequences = True

    def test_only_one_concurrent_worker_claims_the_run(self):
        snapshot = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date="2026-07-08",
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/dataset/test",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        scope_key, categories = pilot_scope_key("Iași", ["constructii"])
        run = ImportRun.objects.create(
            snapshot=snapshot,
            scope_key=scope_key,
            county="Iași",
            categories=categories,
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=POLICY_VERSION,
        )
        barrier = Barrier(2)
        outcomes = []

        def worker():
            connection.close()
            local_run = ImportRun.objects.get(pk=run.pk)
            barrier.wait()
            try:
                outcomes.append(("claimed", claim_import_run(local_run)))
            except ValueError:
                outcomes.append(("refused", None))
            finally:
                connection.close()

        workers = [Thread(target=worker), Thread(target=worker)]
        for worker_thread in workers:
            worker_thread.start()
        for worker_thread in workers:
            worker_thread.join()

        run.refresh_from_db()
        self.assertEqual(sorted(state for state, _token in outcomes), ["claimed", "refused"])
        self.assertEqual(run.state, ImportRun.State.RUNNING)
        self.assertEqual(run.attempt_count, 1)
        self.assertIsNotNone(run.claim_token)
