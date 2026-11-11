"""Generate reviewable SIRUTA alias proposals from an aggregated candidate report."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.importers.locality_aliases import build_alias_proposals, sha256_file
from services.reporting import write_text_atomically


class Command(BaseCommand):
    help = "Propune aliasuri deterministe ONRC→SIRUTA fără a le aplica."

    def add_arguments(self, parser):
        parser.add_argument("--candidates", required=True, type=Path)
        parser.add_argument("--output", required=True, type=Path)

    def handle(self, *args, **options):
        """Read aggregated forms and emit proposals for explicit review."""

        try:
            candidates = json.loads(options["candidates"].read_text(encoding="utf-8"))
            proposals = build_alias_proposals(
                candidates,
                source_candidates_sha256=sha256_file(options["candidates"]),
            )
            rendered = json.dumps(proposals, ensure_ascii=False, indent=2, sort_keys=True)
            write_text_atomically(options["output"], f"{rendered}\n")
            self.stdout.write(self.style.SUCCESS(f"Propuneri scrise: {options['output']}"))
        except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError) as error:
            raise CommandError(str(error)) from error
