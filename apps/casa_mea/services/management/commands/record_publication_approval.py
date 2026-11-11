"""Record a permission-gated publication approval version."""

import json
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from services.catalogue_activation import record_publication_approval
from services.models import ImportRun


class Command(BaseCommand):
    help = "Înregistrează o aprobare juridică/confidențialitate versionată."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--review-reference", required=True)
        parser.add_argument("--review-due-at", required=True)
        parser.add_argument("--acknowledgement", required=True)

    def handle(self, *args, **options):
        """Validate the review deadline and append one approval version."""

        try:
            due_at = datetime.fromisoformat(options["review_due_at"])
            if timezone.is_naive(due_at):
                due_at = timezone.make_aware(due_at)
            approval = record_publication_approval(
                run=ImportRun.objects.get(pk=options["run_id"]),
                actor_username=options["actor"],
                review_reference=options["review_reference"],
                review_due_at=due_at,
                acknowledgement=options["acknowledgement"],
            )
        except (
            ImportRun.DoesNotExist,
            get_user_model().DoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "approval_id": approval.pk,
                    "approval_version": approval.approval_version,
                    "run_id": approval.import_run_id,
                    "review_due_at": approval.review_due_at.isoformat(),
                    "state": approval.state,
                },
                sort_keys=True,
            )
        )
