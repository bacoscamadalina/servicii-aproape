"""Audit personal-data request chains without repairing or exposing records."""

import json

from django.core.management.base import BaseCommand, CommandError

from services.data_subject_integrity import audit_data_subject_requests


class Command(BaseCommand):
    help = "Auditează read-only integritatea cererilor privind datele personale."

    def handle(self, *args, **options):
        """Print one identity-free aggregate report and fail when drift exists."""

        audit = audit_data_subject_requests()
        self.stdout.write(json.dumps(audit.as_dict(), ensure_ascii=False, sort_keys=True))
        if not audit.is_valid:
            raise CommandError(
                "Auditul a detectat abateri; datele nu au fost modificate."
            )
