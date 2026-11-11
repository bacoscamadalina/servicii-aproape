"""Record one reviewed direct-service evidence version."""

from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from services.models import BusinessIdentity
from services.service_evidence import record_verified_service_evidence


class Command(BaseCommand):
    help = "Înregistrează o dovadă directă, versionată, pentru un serviciu."

    def add_arguments(self, parser):
        parser.add_argument("--registration-number", required=True)
        parser.add_argument("--category", required=True)
        parser.add_argument("--source-url", required=True)
        parser.add_argument("--source-title", required=True)
        parser.add_argument("--identity-reference", required=True)
        parser.add_argument("--summary", required=True)
        parser.add_argument("--coverage-county", action="append", required=True)
        parser.add_argument("--retrieved-at", required=True)
        parser.add_argument("--content-sha256", required=True)
        parser.add_argument("--expires-at", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--acknowledgement", required=True)

    def handle(self, *args, **options):
        """Validate authorization, reviewer and expiry before appending evidence."""

        try:
            retrieved_at = datetime.fromisoformat(options["retrieved_at"])
            expires_at = datetime.fromisoformat(options["expires_at"])
            if retrieved_at.tzinfo is None or expires_at.tzinfo is None:
                raise ValueError("Datele dovezii trebuie să includă fusul orar")
            evidence = record_verified_service_evidence(
                business=BusinessIdentity.objects.get(
                    registration_number=options["registration_number"]
                ),
                category=options["category"],
                source_url=options["source_url"],
                source_title=options["source_title"],
                identity_reference=options["identity_reference"],
                evidence_summary=options["summary"],
                coverage_counties=options["coverage_county"],
                retrieved_at=retrieved_at,
                content_sha256=options["content_sha256"],
                expires_at=expires_at,
                actor_username=options["actor"],
                acknowledgement=options["acknowledgement"],
            )
            self.stdout.write(
                f"evidence_id={evidence.pk} version={evidence.evidence_version}"
            )
        except (
            BusinessIdentity.DoesNotExist,
            ValidationError,
            get_user_model().DoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
