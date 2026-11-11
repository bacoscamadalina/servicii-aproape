"""Deterministic, privacy-minimized identity seed for managed-cloud workflows."""

from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

from django.core.exceptions import ImproperlyConfigured
from django.core.management.color import no_style
from django.db import connection, transaction

from .models import BusinessIdentity


SEED_SCHEMA = 1


def snapshot_business_ids(snapshot_path: Path) -> set[int]:
    """Return the exact identities exposed by the packaged discovery snapshot."""

    uri = f"{snapshot_path.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as database:
        return {
            row[0]
            for row in database.execute(
                "SELECT business_id FROM listings WHERE category = ''"
            )
        }


def read_identity_seed(seed_path: Path, snapshot_path: Path) -> list[dict]:
    """Validate the seed checksum and its one-to-one snapshot identity contract."""

    manifest_path = seed_path.with_suffix("").with_suffix(".json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        compressed = seed_path.read_bytes()
        if manifest["schema"] != SEED_SCHEMA:
            raise ValueError("unsupported seed schema")
        if (
            hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
            != manifest["source_snapshot_sha256"]
        ):
            raise ValueError("seed targets a different discovery snapshot")
        if hashlib.sha256(compressed).hexdigest() != manifest["sha256"]:
            raise ValueError("seed checksum mismatch")
        rows = [
            json.loads(line)
            for line in gzip.decompress(compressed).decode("utf-8").splitlines()
            if line
        ]
        ids = {row["id"] for row in rows}
        registrations = {row["registration_number"] for row in rows}
        if (
            len(rows) != manifest["businesses"]
            or len(ids) != len(rows)
            or len(registrations) != len(rows)
            or ids != snapshot_business_ids(snapshot_path)
            or any(
                set(row) != {"id", "registration_number"}
                or not isinstance(row["id"], int)
                or not isinstance(row["registration_number"], str)
                or not row["registration_number"].strip()
                for row in rows
            )
        ):
            raise ValueError("identity seed differs from packaged catalogue")
        return rows
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(
            "Managed-cloud identity seed is missing or invalid."
        ) from error


@transaction.atomic
def seed_business_identities_if_empty(seed_path: Path, snapshot_path: Path) -> int:
    """Populate an empty identity table once; reject every partial database state."""

    rows = read_identity_seed(seed_path, snapshot_path)
    existing = BusinessIdentity.objects.count()
    if existing:
        expected = {row["id"]: row["registration_number"] for row in rows}
        actual = dict(
            BusinessIdentity.objects.values_list("id", "registration_number")
        )
        if existing != len(rows) or actual != expected:
            raise ImproperlyConfigured(
                "Persistent business identities are partial or differ from the packaged catalogue."
            )
        return 0

    BusinessIdentity.objects.bulk_create(
        [BusinessIdentity(**row) for row in rows], batch_size=5_000
    )
    # Explicit primary keys do not advance PostgreSQL sequences automatically.
    with connection.cursor() as cursor:
        for statement in connection.ops.sequence_reset_sql(no_style(), [BusinessIdentity]):
            cursor.execute(statement)
    return len(rows)
