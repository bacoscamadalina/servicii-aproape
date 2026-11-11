"""Import one prepared ONRC pilot run into isolated staging tables."""

import csv
import json
import sqlite3
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.onrc import _sha256, verify_manifest
from services.importers.onrc_pilot import import_onrc_pilot_into_staging
from services.models import ImportRun


class Command(BaseCommand):
    help = "Importă atomic un run pilot ONRC pregătit, fără activare/publicare."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", required=True, type=int)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)

    def handle(self, *args, **options):
        """Reverify provenance and execute the bounded-memory pilot importer."""

        try:
            manifest, paths, _verified = verify_manifest(
                options["manifest"], options["input_dir"]
            )
            run = ImportRun.objects.select_related("snapshot").get(pk=options["run_id"])
            if run.snapshot.manifest_sha256 != _sha256(options["manifest"]):
                raise ValueError("Manifestul nu corespunde snapshotului runului")
            if str(run.snapshot.snapshot_date) != manifest["snapshot_date"]:
                raise ValueError("Data manifestului nu corespunde snapshotului runului")
            scratch_dir = options["scratch_dir"] or Path("/tmp")
            minimum_scratch_bytes = sum(
                paths[kind].stat().st_size for kind in ("firms", "activities", "statuses")
            ) * 2
            if shutil.disk_usage(scratch_dir).free < minimum_scratch_bytes:
                raise ValueError("Spațiu temporar insuficient pentru importul pilot")
            counters, changed = import_onrc_pilot_into_staging(
                run, paths, scratch_dir
            )
            self.stdout.write(
                json.dumps(
                    {
                        "changed": changed,
                        "run_id": run.pk,
                        "state": ImportRun.objects.get(pk=run.pk).state,
                        "counters": counters,
                        "publication_active": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
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
