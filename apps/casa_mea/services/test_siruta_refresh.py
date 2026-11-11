"""Tests for the generated SIRUTA provenance and refresh-audit contract."""

import hashlib
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from services.locations import CATALOGUE_PATH
from tools.build_locations_catalog import (
    _release_metadata,
    _write_new_candidate_pair,
    write_catalog,
)

from .siruta_refresh import (
    SirutaRefreshError,
    _read_json_and_sha256,
    audit_siruta_refresh,
    load_siruta_snapshot,
)


class SirutaRefreshAuditTests(TestCase):
    """A candidate must be coherent before its differences can be reviewed."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_pair(self, prefix, rows, *, source="SIRUTA S1 test"):
        """Write one minimal generated catalogue/hierarchy pair for a test."""

        catalogue = {}
        for row in rows:
            catalogue.setdefault(row["county"], []).append(
                [row["siruta_code"], row["locality_name"], row["locality_name"]]
            )
        catalogue_path = self.root / f"{prefix}-catalogue.json"
        hierarchy_path = self.root / f"{prefix}-hierarchy.json"
        catalogue_bytes = json.dumps(catalogue).encode("utf-8")
        catalogue_path.write_bytes(catalogue_bytes)
        hierarchy_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "source": {
                        "dataset": source,
                        "release_id": source.rsplit(" ", 1)[-1],
                        "sheet": "Data",
                        "source_url": "https://example.test/siruta.xlsx",
                        "published_date": "2026-01-02",
                        "retrieved_at": "2026-01-03T10:00:00Z",
                        "raw_sha256": "a" * 64,
                        "generator_policy_version": "siruta-localities-v2",
                        "catalogue_sha256": hashlib.sha256(catalogue_bytes).hexdigest(),
                        "county_count": len(catalogue),
                        "locality_count": len(rows),
                    },
                    "localities": rows,
                }
            ),
            encoding="utf-8",
        )
        return catalogue_path, hierarchy_path

    @staticmethod
    def repin_catalogue(pair):
        """Update only test metadata after deliberately changing catalogue bytes."""

        hierarchy = json.loads(pair[1].read_text(encoding="utf-8"))
        hierarchy["source"]["catalogue_sha256"] = hashlib.sha256(
            pair[0].read_bytes()
        ).hexdigest()
        pair[1].write_text(json.dumps(hierarchy), encoding="utf-8")

    @staticmethod
    def row(code, name, *, county="Iași", parent="Iași", parent_code="95060"):
        """Return one complete hierarchy row with stable administrative types."""

        return {
            "siruta_code": code,
            "county": county,
            "locality_name": name,
            "locality_tip": 9,
            "parent_siruta": parent_code,
            "parent_name": parent,
            "parent_tip": 1,
        }

    def test_identical_pair_is_unchanged(self):
        current = self.write_pair("current", [self.row("95079", "Iași")])

        report = audit_siruta_refresh(
            current_catalogue_path=current[0],
            current_hierarchy_path=current[1],
            candidate_catalogue_path=current[0],
            candidate_hierarchy_path=current[1],
        ).as_dict()

        self.assertEqual(report["status"], "unchanged")
        self.assertEqual(report["changes"]["changed_count"], 0)
        self.assertFalse(report["impact"]["requires_coordinated_rollout"])

    def test_reports_added_removed_and_changed_codes_deterministically(self):
        current = self.write_pair(
            "current",
            [self.row("95079", "Iași"), self.row("95408", "Valea Lupului")],
        )
        candidate = self.write_pair(
            "candidate",
            [
                self.row("95079", "Municipiul Iași"),
                self.row("96076", "Miroslava", parent="Miroslava", parent_code="96067"),
            ],
            source="SIRUTA S1 next",
        )

        report = audit_siruta_refresh(
            current_catalogue_path=current[0],
            current_hierarchy_path=current[1],
            candidate_catalogue_path=candidate[0],
            candidate_hierarchy_path=candidate[1],
        ).as_dict()

        self.assertEqual(report["status"], "semantic_change")
        self.assertEqual(report["changes"]["added"][0]["siruta_code"], "96076")
        self.assertEqual(report["changes"]["removed"][0]["siruta_code"], "95408")
        self.assertEqual(
            report["changes"]["changed"],
            [
                {
                    "siruta_code": "95079",
                    "fields": {
                        "locality_name": {"from": "Iași", "to": "Municipiul Iași"},
                        "display_label": {"from": "Iași", "to": "Municipiul Iași"},
                    },
                }
            ],
        )
        self.assertEqual(report["changes"]["changed_fields"]["locality_name"], 1)
        self.assertEqual(report["changes"]["changed_fields"]["display_label"], 1)
        self.assertTrue(report["impact"]["provider_source_pins_will_change"])
        self.assertFalse(report["impact"]["automatic_install_permitted"])

    def test_reformatted_semantically_equal_pair_is_hash_only_change(self):
        current = self.write_pair("current", [self.row("95079", "Iași")])
        candidate = self.write_pair("candidate", [self.row("95079", "Iași")])
        candidate[0].write_text(
            json.dumps(json.loads(candidate[0].read_text()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.repin_catalogue(candidate)

        audit = audit_siruta_refresh(
            current_catalogue_path=current[0],
            current_hierarchy_path=current[1],
            candidate_catalogue_path=candidate[0],
            candidate_hierarchy_path=candidate[1],
        )

        self.assertEqual(audit.as_dict()["status"], "hash_only_change")
        self.assertFalse(audit.has_semantic_changes)

    def test_rejects_catalogue_hierarchy_disagreement(self):
        pair = self.write_pair("broken", [self.row("95079", "Iași")])
        pair[0].write_text(json.dumps({"Iași": [["95079", "Iasi", "Iasi"]]}))
        self.repin_catalogue(pair)

        with self.assertRaisesRegex(SirutaRefreshError, "descriu diferit"):
            audit_siruta_refresh(
                current_catalogue_path=pair[0],
                current_hierarchy_path=pair[1],
                candidate_catalogue_path=pair[0],
                candidate_hierarchy_path=pair[1],
            )

    def test_command_fails_closed_on_change_and_allows_explicit_report_only(self):
        current = self.write_pair("current", [self.row("95079", "Iași")])
        candidate = self.write_pair(
            "candidate",
            [self.row("95079", "Iași"), self.row("96076", "Miroslava")],
        )
        blocked_output = StringIO()

        with (
            patch(
                "services.management.commands.audit_siruta_refresh.CATALOGUE_PATH",
                current[0],
            ),
            patch(
                "services.management.commands.audit_siruta_refresh.HIERARCHY_PATH",
                current[1],
            ),
            self.assertRaises(CommandError),
        ):
            call_command("audit_siruta_refresh", *candidate, stdout=blocked_output)
        blocked_payload = json.loads(blocked_output.getvalue())
        self.assertTrue(blocked_payload["impact"]["content_hash_changed"])

        output = StringIO()
        with (
            patch(
                "services.management.commands.audit_siruta_refresh.CATALOGUE_PATH",
                current[0],
            ),
            patch(
                "services.management.commands.audit_siruta_refresh.HIERARCHY_PATH",
                current[1],
            ),
        ):
            call_command(
                "audit_siruta_refresh",
                *candidate,
                report_only=True,
                stdout=output,
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(payload["report_schema_version"], 1)
        self.assertFalse(payload["impact"]["automatic_install_permitted"])

    def test_rejects_partial_national_candidate_and_conflicting_parent(self):
        current = self.write_pair(
            "current",
            [
                self.row("95079", "Iași"),
                self.row(
                    "54984",
                    "Cluj-Napoca",
                    county="Cluj",
                    parent="Cluj-Napoca",
                    parent_code="54975",
                ),
            ],
        )
        partial = self.write_pair("partial", [self.row("95079", "Iași")])
        with self.assertRaisesRegex(SirutaRefreshError, "setul național complet"):
            audit_siruta_refresh(
                current_catalogue_path=current[0],
                current_hierarchy_path=current[1],
                candidate_catalogue_path=partial[0],
                candidate_hierarchy_path=partial[1],
            )

        conflicting = self.write_pair(
            "conflicting",
            [
                self.row("95079", "Iași"),
                self.row("95088", "Galata", parent="Alt părinte"),
            ],
        )
        with self.assertRaisesRegex(SirutaRefreshError, "identități contradictorii"):
            load_siruta_snapshot(conflicting[0], conflicting[1], require_release_metadata=True)

    def test_invalid_utf8_is_wrapped_and_each_artifact_is_read_once(self):
        class OneRead:
            def __init__(self, content):
                self.content = content
                self.calls = 0

            def read_bytes(self):
                self.calls += 1
                return self.content

        valid = OneRead(b'{"ok":true}')
        payload, digest = _read_json_and_sha256(valid)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(digest, hashlib.sha256(valid.content).hexdigest())
        self.assertEqual(valid.calls, 1)
        with self.assertRaisesRegex(SirutaRefreshError, "nu poate fi citită"):
            _read_json_and_sha256(OneRead(b"\xff"))

    def test_checked_in_legacy_snapshot_is_complete_and_readable(self):
        snapshot = load_siruta_snapshot(
            CATALOGUE_PATH,
            CATALOGUE_PATH.with_name("localities_hierarchy.json"),
        )

        self.assertEqual(snapshot.hierarchy_schema_version, 1)
        self.assertEqual(snapshot.county_count, 42)
        self.assertEqual(len(snapshot.localities), 13_755)

    def test_builder_metadata_pins_raw_source_and_generated_catalogue(self):
        source_bytes = b"opaque official workbook"
        catalogue_bytes = b'{"Alba":[["1026","Alba Iulia","Alba Iulia"]]}'

        generated = _release_metadata(
            source_bytes=source_bytes,
            catalogue_bytes=catalogue_bytes,
            county_count=1,
            locality_count=1,
            release_id="2026",
            source_url="https://data.gov.ro/example/siruta-2026.xlsx",
            published_date="2026-01-02",
            retrieved_at="2026-01-03T10:00:00Z",
        )

        self.assertEqual(generated["release_id"], "2026")
        self.assertEqual(generated["generator_policy_version"], "siruta-localities-v2")
        self.assertEqual(
            generated["raw_sha256"], hashlib.sha256(source_bytes).hexdigest()
        )
        self.assertEqual(
            generated["catalogue_sha256"], hashlib.sha256(catalogue_bytes).hexdigest()
        )

    def test_builder_rejects_naive_time_before_touching_candidate_pair(self):
        source = self.root / "missing-source.xlsx"
        destination = self.root / "candidate-catalogue.json"
        hierarchy = self.root / "candidate-hierarchy.json"
        destination.write_bytes(b"existing catalogue")
        hierarchy.write_bytes(b"existing hierarchy")

        with self.assertRaisesRegex(ValueError, "fusul orar"):
            write_catalog(
                source,
                destination,
                hierarchy,
                release_id="2026",
                source_url="https://data.gov.ro/example/siruta-2026.xlsx",
                published_date="2026-01-02",
                retrieved_at="2026-01-03T10:00:00",
            )

        self.assertEqual(destination.read_bytes(), b"existing catalogue")
        self.assertEqual(hierarchy.read_bytes(), b"existing hierarchy")

    def test_auditor_rejects_publication_after_retrieval(self):
        pair = self.write_pair("bad-dates", [self.row("95079", "Iași")])
        hierarchy = json.loads(pair[1].read_text(encoding="utf-8"))
        hierarchy["source"]["published_date"] = "2026-01-04"
        hierarchy["source"]["retrieved_at"] = "2026-01-03T10:00:00Z"
        pair[1].write_text(json.dumps(hierarchy), encoding="utf-8")

        with self.assertRaisesRegex(SirutaRefreshError, "nu poate fi după"):
            load_siruta_snapshot(pair[0], pair[1], require_release_metadata=True)

    def test_candidate_pair_install_is_complete_and_rolls_back_second_link_failure(self):
        destination = self.root / "new" / "catalogue.json"
        hierarchy = self.root / "new" / "hierarchy.json"
        _write_new_candidate_pair(
            catalogue_bytes=b"catalogue",
            hierarchy_bytes=b"hierarchy",
            destination=destination,
            hierarchy_destination=hierarchy,
        )
        self.assertEqual(destination.read_bytes(), b"catalogue")
        self.assertEqual(hierarchy.read_bytes(), b"hierarchy")

        rollback_destination = self.root / "rollback" / "catalogue.json"
        rollback_hierarchy = self.root / "rollback" / "hierarchy.json"
        real_link = os.link

        def fail_hierarchy_link(source, target):
            if target == rollback_hierarchy:
                raise OSError("simulated second-link failure")
            return real_link(source, target)

        with (
            patch("tools.build_locations_catalog.os.link", side_effect=fail_hierarchy_link),
            self.assertRaisesRegex(OSError, "second-link"),
        ):
            _write_new_candidate_pair(
                catalogue_bytes=b"catalogue",
                hierarchy_bytes=b"hierarchy",
                destination=rollback_destination,
                hierarchy_destination=rollback_hierarchy,
            )

        self.assertFalse(rollback_destination.exists())
        self.assertFalse(rollback_hierarchy.exists())
        self.assertEqual(list((self.root / "rollback").glob(".siruta-*")), [])
