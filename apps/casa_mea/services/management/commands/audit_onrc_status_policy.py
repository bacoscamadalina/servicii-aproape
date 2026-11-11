"""Generate a manifest-pinned audit of ONRC company status combinations."""

import csv
import json
import resource
import shutil
import sqlite3
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.onrc import verify_manifest
from services.importers.onrc_statuses import audit_status_policy
from services.reporting import write_text_atomically


class Command(BaseCommand):
    help = "Inventariază combinațiile de stare ONRC fără staging sau publicare."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)
        parser.add_argument("--output", required=True, type=Path)

    def handle(self, *args, **options):
        """Verify sources, audit status sets, and atomically write the report."""

        scratch_dir = options["scratch_dir"] or Path("/tmp")
        try:
            manifest, paths, verified = verify_manifest(
                options["manifest"], options["input_dir"]
            )
            required_bytes = (
                paths["firms"].stat().st_size + paths["statuses"].stat().st_size
            ) * 2
            available_bytes = shutil.disk_usage(scratch_dir).free
            if available_bytes < required_bytes:
                raise ValueError(
                    f"Spațiu temporar insuficient: {available_bytes} < {required_bytes}"
                )
            started = time.perf_counter()
            results = audit_status_policy(
                paths["firms"],
                paths["statuses"],
                paths["status_dictionary"],
                scratch_dir,
            )
            report = {
                "report_schema_version": 1,
                "snapshot_date": manifest["snapshot_date"],
                "dataset_url": manifest["dataset_url"],
                "license": manifest["license"],
                "verified_sources": {
                    key: verified[key]
                    for key in ("firms", "statuses", "status_dictionary")
                },
                "runtime": {
                    "elapsed_seconds": round(time.perf_counter() - started, 2),
                    "maximum_resident_memory_kib": resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss,
                    "minimum_scratch_bytes": required_bytes,
                    "available_scratch_before_bytes": available_bytes,
                },
                "results": results,
            }
            rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            write_text_atomically(options["output"], f"{rendered}\n")
            self.stdout.write(self.style.SUCCESS(f"Raport scris: {options['output']}"))
        except (csv.Error, json.JSONDecodeError, OSError, sqlite3.Error, ValueError) as error:
            raise CommandError(str(error)) from error
