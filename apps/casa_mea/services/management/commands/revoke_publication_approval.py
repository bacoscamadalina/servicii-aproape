"""Revoke a permission-gated publication approval version."""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from services.catalogue_activation import revoke_publication_approval
from services.models import PublicationApproval


class Command(BaseCommand):
    help = "Revocă o aprobare de publicare; readerul activ eșuează imediat închis."

    def add_arguments(self, parser):
        parser.add_argument("--approval-id", type=int, required=True)
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        """Revoke without deleting the approval or its prior activation events."""

        try:
            approval, changed = revoke_publication_approval(
                approval=PublicationApproval.objects.get(pk=options["approval_id"]),
                actor_username=options["actor"],
            )
        except (
            PublicationApproval.DoesNotExist,
            get_user_model().DoesNotExist,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "approval_id": approval.pk,
                    "approval_version": approval.approval_version,
                    "changed": changed,
                    "state": approval.state,
                },
                sort_keys=True,
            )
        )
