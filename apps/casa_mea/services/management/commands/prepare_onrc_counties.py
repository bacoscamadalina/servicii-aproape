"""Prepare deterministic county scopes in one all-or-nothing operation."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from services.importers.onrc import verify_manifest
from services.locations import read_locations_catalogue
from services.staging import prepare_pilot_import_run


class Command(BaseCommand):
    help = "Pregătește atomic runuri ONRC pentru toate județele cerute."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--county", action="append")
        parser.add_argument("--exclude-county", action="append", default=[])
        parser.add_argument("--category", action="append", required=True)

    def handle(self, *args, **options):
        """Verify the bundle, then prepare every scope in one DB transaction."""

        try:
            manifest, _paths, verified = verify_manifest(
                options["manifest"], options["input_dir"]
            )
            catalogue = read_locations_catalogue()
            requested = options["county"] or list(catalogue)
            excluded = set(options["exclude_county"])
            unknown_requested = set(requested) - set(catalogue)
            unknown_excluded = excluded - set(catalogue)
            if unknown_requested or unknown_excluded:
                unknown = unknown_requested | unknown_excluded
                raise ValueError(f"Județe necunoscute: {', '.join(sorted(unknown))}")
            counties = sorted(set(requested) - excluded)
            if not counties:
                raise ValueError("Scope-ul rezultat nu conține niciun județ")
            rows = []
            with transaction.atomic():
                for county in counties:
                    run, created = prepare_pilot_import_run(
                        manifest,
                        options["manifest"],
                        verified,
                        county,
                        options["category"],
                    )
                    rows.append(
                        {
                            "county": county,
                            "run_id": run.pk,
                            "scope_key": run.scope_key,
                            "state": run.state,
                            "created": created,
                        }
                    )
            self.stdout.write(json.dumps(rows, ensure_ascii=False, sort_keys=True))
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise CommandError(str(error)) from error
