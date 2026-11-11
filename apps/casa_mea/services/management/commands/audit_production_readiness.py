"""Pre-launch and periodic production-readiness gate; never a liveness check."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from services.locations import county_choices
from services.production_readiness import ANOMALY_CODES, audit_production_readiness


class Command(BaseCommand):
    """Audit an explicit launch area and deployment state without changing either."""

    help = "Audit public launch readiness for explicitly supplied counties."

    def add_arguments(self, parser):
        """Avoid inferring that the launch is national while its area is undecided."""

        parser.add_argument("--county", action="append", required=True, dest="counties")

    def handle(self, *args, **options):
        """Emit deterministic JSON and fail non-zero on any readiness anomaly."""

        counties = tuple(options["counties"])
        official = {name for name, _label in county_choices()}
        if len(set(counties)) != len(counties) or any(county not in official for county in counties):
            raise CommandError("Every --county must be a unique official county name.")

        migrations = MigrationExecutor(connection)
        pending_migrations = bool(
            migrations.migration_plan(migrations.loader.graph.leaf_nodes())
        )
        restore_complete = (Path(settings.MEDIA_ROOT) / ".restore-complete").is_file()
        # Current ORM queries are unsafe against an older schema. Report migration
        # drift first and leave the catalogue explicitly unchecked.
        catalogue = (
            audit_production_readiness(counties=counties).as_dict()
            if not pending_migrations
            else {
                "schema_version": 1,
                "valid": False,
                "launch_counties": len(counties),
                "ready_counties": 0,
                "anomalies": dict.fromkeys(ANOMALY_CODES, 0),
            }
        )
        report = {
            **catalogue,
            "catalogue_checked": not pending_migrations,
            "deployment": {
                "pending_migrations": pending_migrations,
                "restore_complete": restore_complete,
            },
        }
        report["valid"] = bool(
            catalogue["valid"] and not pending_migrations and restore_complete
        )
        self.stdout.write(json.dumps(report, sort_keys=True))
        if not report["valid"]:
            raise CommandError("Production launch-readiness audit failed.")
