"""Contracts for the privacy-minimized managed-cloud identity seed."""

import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from django.core.exceptions import ImproperlyConfigured
from django.test import TransactionTestCase

from .managed_cloud_seed import read_identity_seed, seed_business_identities_if_empty
from .models import BusinessIdentity


class ManagedCloudSeedTests(TransactionTestCase):
    """Prove exact catalogue parity and reject partial persistent state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.snapshot = self.directory / "catalogue.snapshot"
        with sqlite3.connect(self.snapshot) as database:
            database.execute(
                "CREATE TABLE listings (business_id INTEGER, category TEXT)"
            )
            database.executemany(
                "INSERT INTO listings VALUES (?, ?)",
                [(11, ""), (11, "constructii"), (22, "")],
            )
        self.rows = [
            {"id": 11, "registration_number": "J22/11/2020"},
            {"id": 22, "registration_number": "J22/22/2020"},
        ]
        self.seed = self.directory / "identities.jsonl.gz"
        payload = "".join(
            f"{json.dumps(row, ensure_ascii=False, separators=(',', ':'))}\n"
            for row in self.rows
        ).encode()
        compressed = gzip.compress(payload, mtime=0)
        self.seed.write_bytes(compressed)
        (self.directory / "identities.json").write_text(
            json.dumps(
                {
                    "businesses": 2,
                    "schema": 1,
                    "sha256": hashlib.sha256(compressed).hexdigest(),
                    "source_snapshot_sha256": hashlib.sha256(
                        self.snapshot.read_bytes()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    def test_valid_seed_populates_once_and_is_idempotent(self):
        self.assertEqual(read_identity_seed(self.seed, self.snapshot), self.rows)
        self.assertEqual(seed_business_identities_if_empty(self.seed, self.snapshot), 2)
        self.assertEqual(seed_business_identities_if_empty(self.seed, self.snapshot), 0)
        self.assertEqual(
            list(BusinessIdentity.objects.values_list("id", "registration_number")),
            [(11, "J22/11/2020"), (22, "J22/22/2020")],
        )

    def test_seed_rejects_partial_existing_database(self):
        BusinessIdentity.objects.create(id=11, registration_number="J22/11/2020")
        with self.assertRaisesRegex(ImproperlyConfigured, "partial or differ"):
            seed_business_identities_if_empty(self.seed, self.snapshot)

    def test_seed_rejects_checksum_or_snapshot_drift(self):
        self.seed.write_bytes(self.seed.read_bytes() + b"changed")
        with self.assertRaisesRegex(ImproperlyConfigured, "missing or invalid"):
            read_identity_seed(self.seed, self.snapshot)

    def test_seed_rejects_identity_not_in_catalogue(self):
        with sqlite3.connect(self.snapshot) as database:
            database.execute("DELETE FROM listings WHERE business_id = 22")
        manifest = json.loads(
            (self.directory / "identities.json").read_text(encoding="utf-8")
        )
        manifest["source_snapshot_sha256"] = hashlib.sha256(
            self.snapshot.read_bytes()
        ).hexdigest()
        (self.directory / "identities.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(ImproperlyConfigured, "missing or invalid"):
            read_identity_seed(self.seed, self.snapshot)

    def test_seed_rejects_every_field_outside_public_identity_allowlist(self):
        rows = [{**self.rows[0], "email": "private@example.test"}, self.rows[1]]
        payload = "".join(
            f"{json.dumps(row, separators=(',', ':'))}\n" for row in rows
        ).encode()
        compressed = gzip.compress(payload, mtime=0)
        self.seed.write_bytes(compressed)
        manifest_path = self.directory / "identities.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sha256"] = hashlib.sha256(compressed).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ImproperlyConfigured, "missing or invalid"):
            read_identity_seed(self.seed, self.snapshot)
