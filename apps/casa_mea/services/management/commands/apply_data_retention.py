"""Audit retention by default and apply it only with explicit acknowledgement."""

import json

from django.core.management.base import BaseCommand, CommandError

from services.data_retention import apply_data_retention, data_retention_snapshot


class Command(BaseCommand):
    help = "Auditează sau aplică în loturi politica configurată de retenție."

    def add_arguments(self, parser):
        """Expose a fail-safe dry run and a deliberately noisy write contract."""

        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--acknowledgement", default="")
        parser.add_argument("--batch-size", type=int, default=250)

    def handle(self, *args, **options):
        """Emit only aggregate JSON so command logs never become a PII export."""

        if not options["apply"]:
            result = {"mode": "audit_only", **data_retention_snapshot()}
        else:
            try:
                result = {
                    "mode": "applied",
                    **apply_data_retention(
                        acknowledgement=options["acknowledgement"],
                        batch_size=options["batch_size"],
                    ),
                }
            except ValueError as error:
                raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
