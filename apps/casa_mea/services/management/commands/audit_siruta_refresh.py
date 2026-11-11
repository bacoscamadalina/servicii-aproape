"""Compare a candidate SIRUTA release with the pinned application catalogue."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from services.locations import CATALOGUE_PATH
from services.siruta_refresh import SirutaRefreshError, audit_siruta_refresh


HIERARCHY_PATH = CATALOGUE_PATH.with_name("localities_hierarchy.json")


class Command(BaseCommand):
    help = (
        "Auditează read-only o pereche SIRUTA schema 2 și blochează implicit orice drift."
    )

    def add_arguments(self, parser):
        """Require both generated candidate files and allow CI to reject any drift."""

        parser.add_argument("candidate_catalogue", type=Path)
        parser.add_argument("candidate_hierarchy", type=Path)
        parser.add_argument(
            "--report-only",
            action="store_true",
            help="Raportează schimbarea cu exit 0; nu permite și nu instalează candidatul.",
        )

    def handle(self, *args, **options):
        """Print the complete deterministic report and never mutate application data."""

        try:
            audit = audit_siruta_refresh(
                current_catalogue_path=CATALOGUE_PATH,
                current_hierarchy_path=HIERARCHY_PATH,
                candidate_catalogue_path=options["candidate_catalogue"],
                candidate_hierarchy_path=options["candidate_hierarchy"],
            )
        except SirutaRefreshError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(audit.as_dict(), ensure_ascii=False, sort_keys=True)
        )
        if not options["report_only"] and audit.content_hash_changed:
            raise CommandError(
                "Candidatul schimbă pinurile SIRUTA; raportul trebuie revizuit înainte de adoptare."
            )
