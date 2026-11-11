"""Export only public business identities needed by the managed-cloud claim flow."""

import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from services.managed_cloud_seed import SEED_SCHEMA, snapshot_business_ids
from services.models import BusinessIdentity


class Command(BaseCommand):
    """Create a deterministic seed without accounts, claims, audit data or media."""

    help = "Export the privacy-minimized managed-cloud business identity seed."

    def add_arguments(self, parser):
        """Allow an explicit destination while keeping the packaged path conventional."""

        parser.add_argument(
            "--output-directory",
            default=str(settings.BASE_DIR / "deploy" / "managed_cloud"),
        )

    def handle(self, *args, **options):
        """Write a checksum-bound gzip JSONL file atomically."""

        snapshot_path = settings.BASE_DIR / "deploy" / "preview" / "catalogue.snapshot"
        snapshot_ids = snapshot_business_ids(snapshot_path)
        rows = list(
            BusinessIdentity.objects.filter(id__in=snapshot_ids)
            .order_by("id")
            .values("id", "registration_number")
        )
        if len(rows) != len(snapshot_ids):
            raise CommandError("The source database does not contain every packaged business identity.")

        payload = b"".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            + b"\n"
            for row in rows
        )
        destination = Path(options["output_directory"]).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        seed_path = destination / "identities.jsonl.gz"
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            with gzip.GzipFile(fileobj=temporary, mode="wb", filename="", mtime=0) as archive:
                archive.write(payload)
        compressed = temporary_path.read_bytes()
        temporary_path.replace(seed_path)
        manifest = {
            "schema": SEED_SCHEMA,
            "businesses": len(rows),
            "sha256": hashlib.sha256(compressed).hexdigest(),
            "source_snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        }
        (destination / "identities.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.stdout.write(json.dumps({"businesses": len(rows), "result": "exported"}))
