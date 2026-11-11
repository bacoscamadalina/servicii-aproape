"""Report unresolved request notification delivery without exposing identities."""

import json

from django.core.management.base import BaseCommand, CommandError

from services.delivery_audit import audit_request_delivery


class Command(BaseCommand):
    """An operator can schedule this read-only check without mailing anyone."""

    help = "Audit active request delivery using identity-free aggregate counts."

    def handle(self, *args, **options):
        """Emit machine-readable evidence and fail when intervention is needed."""

        report = audit_request_delivery()
        self.stdout.write(json.dumps(report, sort_keys=True))
        if not report["valid"]:
            raise CommandError("Unresolved request delivery needs operator review.")
