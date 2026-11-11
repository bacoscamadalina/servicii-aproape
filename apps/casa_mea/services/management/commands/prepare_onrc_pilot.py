"""Prepare one idempotent ONRC pilot scope without importing or publishing data."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.onrc import verify_manifest
from services.staging import prepare_pilot_import_run


class Command(BaseCommand):
    help = "Pregătește un scope pilot ONRC verificat, fără import sau publicare."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--county", required=True)
        parser.add_argument("--category", action="append", required=True)

    def handle(self, *args, **options):
        """Verify the complete bundle and create one pending run idempotently."""

        try:
            manifest, _paths, verified = verify_manifest(
                options["manifest"], options["input_dir"]
            )
            run, created = prepare_pilot_import_run(
                manifest,
                options["manifest"],
                verified,
                options["county"],
                options["category"],
            )
            payload = {
                "created": created,
                "run_id": run.pk,
                "state": run.state,
                "county": run.county,
                "categories": run.categories,
                "scope_key": run.scope_key,
                "publication_active": False,
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise CommandError(str(error)) from error
