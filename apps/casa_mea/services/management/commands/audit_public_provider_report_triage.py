"""Audit the public-report triage chain without repairing or exposing records."""

import json

from django.core.management.base import BaseCommand, CommandError

from services.report_integrity import audit_public_provider_report_triage


class Command(BaseCommand):
    help = (
        "Auditează read-only integritatea dosarelor și evenimentelor sesizărilor publice."
    )

    def handle(self, *args, **options):
        """Print one deterministic aggregate report and fail when drift exists."""

        audit = audit_public_provider_report_triage()
        self.stdout.write(json.dumps(audit.as_dict(), ensure_ascii=False, sort_keys=True))
        if not audit.is_valid:
            raise CommandError(
                "Auditul a detectat abateri; datele nu au fost modificate."
            )
