"""Report privacy drift in retained customer projects without changing data."""

import json

from django.core.management.base import BaseCommand, CommandError

from services.retention_integrity import audit_retention_integrity


class Command(BaseCommand):
    help = "Auditează read-only integritatea solicitărilor anonimizate."

    def handle(self, *args, **options):
        """Print one aggregate report and fail closed when drift is detected."""

        audit = audit_retention_integrity()
        self.stdout.write(json.dumps(audit.as_dict(), ensure_ascii=False, sort_keys=True))
        if not audit.is_valid:
            raise CommandError("Auditul retenției a detectat abateri; datele nu au fost modificate.")
