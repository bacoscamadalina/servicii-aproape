"""Revoke a reviewed direct-service evidence version."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from services.models import VerifiedServiceEvidence
from services.service_evidence import revoke_verified_service_evidence


class Command(BaseCommand):
    help = "Revocă imediat o dovadă directă de serviciu."

    def add_arguments(self, parser):
        parser.add_argument("--evidence-id", required=True, type=int)
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        """Apply the audited revocation transition idempotently."""

        try:
            evidence, changed = revoke_verified_service_evidence(
                evidence=VerifiedServiceEvidence.objects.get(
                    pk=options["evidence_id"]
                ),
                actor_username=options["actor"],
            )
            self.stdout.write(
                f"evidence_id={evidence.pk} revoked={str(changed).lower()}"
            )
        except (
            VerifiedServiceEvidence.DoesNotExist,
            get_user_model().DoesNotExist,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
