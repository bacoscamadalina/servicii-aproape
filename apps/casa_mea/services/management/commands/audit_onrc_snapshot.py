"""Audit one manifest-pinned ONRC snapshot without publishing companies."""

import csv
import json
import resource
import shutil
import sqlite3
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.onrc import (
    IMPORTER_VERSION,
    RESOURCE_KINDS,
    audit_snapshot,
    verify_manifest,
)
from services.reporting import write_text_atomically


class Command(BaseCommand):
    help = "Validează integral un snapshot ONRC fixat prin manifest, fără publicare."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        """Verify chain of custody, run the audit, and emit a reproducible report."""

        manifest_path = options["manifest"]
        input_dir = options["input_dir"]
        scratch_dir = options["scratch_dir"] or Path("/tmp")
        if not manifest_path.is_file():
            raise CommandError(f"Manifest inexistent: {manifest_path}")
        if not input_dir.is_dir():
            raise CommandError(f"Director de intrare inexistent: {input_dir}")
        if not scratch_dir.is_dir():
            raise CommandError(f"Director temporar inexistent: {scratch_dir}")

        try:
            manifest, paths, verified = verify_manifest(manifest_path, input_dir)
            input_bytes = sum(paths[kind].stat().st_size for kind in RESOURCE_KINDS)
            minimum_scratch_bytes = input_bytes * 2
            available_scratch_bytes = shutil.disk_usage(scratch_dir).free
            if available_scratch_bytes < minimum_scratch_bytes:
                raise ValueError(
                    "Spațiu temporar insuficient: "
                    f"disponibil={available_scratch_bytes}, necesar={minimum_scratch_bytes}"
                )

            started = time.perf_counter()
            results = audit_snapshot(paths, scratch_dir)
            elapsed_seconds = round(time.perf_counter() - started, 2)
            report = {
                "report_schema_version": 2,
                "importer_version": IMPORTER_VERSION,
                "snapshot_date": manifest["snapshot_date"],
                "dataset_url": manifest["dataset_url"],
                "license": manifest["license"],
                "verified_sources": verified,
                "runtime": {
                    "elapsed_seconds": elapsed_seconds,
                    "maximum_resident_memory_kib": resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss,
                    "input_bytes": input_bytes,
                    "minimum_scratch_bytes": minimum_scratch_bytes,
                    "available_scratch_before_bytes": available_scratch_bytes,
                },
                "results": results,
            }
            rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            if options["output"]:
                write_text_atomically(options["output"], f"{rendered}\n")
                self.stdout.write(
                    self.style.SUCCESS(f"Raport verificat: {options['output']}")
                )
            else:
                self.stdout.write(rendered)
        except (csv.Error, json.JSONDecodeError, OSError, sqlite3.Error, ValueError) as error:
            raise CommandError(str(error)) from error
