"""Import many prepared county scopes from one national source scan."""

import csv
import json
import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.onrc import _sha256, verify_manifest
from services.importers.onrc_counties import import_onrc_counties_into_staging
from services.models import ImportRun


class Command(BaseCommand):
    help = "Scanează o dată bundle-ul ONRC și importă izolat mai multe județe."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", action="append", required=True, type=int)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)

    def handle(self, *args, **options):
        """Reverify provenance before and after the shared scan, then import."""

        try:
            manifest, paths, _verified = verify_manifest(
                options["manifest"], options["input_dir"]
            )
            runs = list(
                ImportRun.objects.select_related("snapshot").filter(
                    pk__in=options["run_id"]
                )
            )
            if len(runs) != len(set(options["run_id"])):
                raise ValueError("Un run lipsește sau lista conține duplicate")
            manifest_hash = _sha256(options["manifest"])
            for run in runs:
                if run.snapshot.manifest_sha256 != manifest_hash:
                    raise ValueError("Manifestul nu corespunde snapshotului runului")
                if str(run.snapshot.snapshot_date) != manifest["snapshot_date"]:
                    raise ValueError("Data snapshotului nu corespunde manifestului")

            def verify_sources_after_scan() -> None:
                refreshed_manifest, _paths, _verified = verify_manifest(
                    options["manifest"], options["input_dir"]
                )
                if (
                    _sha256(options["manifest"]) != manifest_hash
                    or refreshed_manifest["snapshot_date"] != manifest["snapshot_date"]
                ):
                    raise ValueError("Proveniența s-a schimbat în timpul scanării")

            results = import_onrc_counties_into_staging(
                runs,
                paths,
                verify_sources_after_scan,
                options["scratch_dir"],
            )
            payload = [dict({"run_id": run_id}, **result) for run_id, result in sorted(results.items())]
            self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            errors = [row for row in payload if row["error"]]
            if errors:
                raise CommandError(f"{len(errors)} runuri nu au fost finalizate")
        except (
            csv.Error,
            ImportRun.DoesNotExist,
            json.JSONDecodeError,
            OSError,
            sqlite3.Error,
            TypeError,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
