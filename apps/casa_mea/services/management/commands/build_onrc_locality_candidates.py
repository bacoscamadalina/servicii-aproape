"""Build a privacy-minimized catalogue of ONRC locality variants for review."""

import csv
import json
import resource
import shutil
import sqlite3
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.onrc import verify_manifest
from services.importers.onrc_localities import build_locality_candidates
from services.reporting import write_text_atomically


class Command(BaseCommand):
    help = "Agregă formele de localitate ONRC fără firme, adrese sau date personale."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)
        parser.add_argument("--output", required=True, type=Path)

    def handle(self, *args, **options):
        """Verify the source bundle and write aggregated locality candidates."""

        scratch_dir = options["scratch_dir"] or Path("/tmp")
        if not scratch_dir.is_dir():
            raise CommandError(f"Director temporar inexistent: {scratch_dir}")
        try:
            manifest, paths, verified = verify_manifest(
                options["manifest"], options["input_dir"]
            )
            available_scratch = shutil.disk_usage(scratch_dir).free
            required_scratch = paths["firms"].stat().st_size * 2
            if available_scratch < required_scratch:
                raise ValueError(
                    f"Spațiu temporar insuficient: {available_scratch} < {required_scratch}"
                )
            started = time.perf_counter()
            results = build_locality_candidates(paths["firms"], scratch_dir)
            report = {
                "report_schema_version": 1,
                "snapshot_date": manifest["snapshot_date"],
                "source_firms": verified["firms"],
                "source_siruta": verified["siruta_catalogue"],
                "runtime": {
                    "elapsed_seconds": round(time.perf_counter() - started, 2),
                    "maximum_resident_memory_kib": resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss,
                    "available_scratch_before_bytes": available_scratch,
                    "minimum_scratch_bytes": required_scratch,
                },
                "results": results,
            }
            rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            write_text_atomically(options["output"], f"{rendered}\n")
            self.stdout.write(
                self.style.SUCCESS(f"Candidați agregați: {options['output']}")
            )
        except (csv.Error, json.JSONDecodeError, OSError, sqlite3.Error, ValueError) as error:
            raise CommandError(str(error)) from error
