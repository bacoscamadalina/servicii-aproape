"""Explicitly deactivate one county catalogue pointer."""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from services.catalogue_activation import deactivate_catalogue_scope
from services.models import CatalogueScope


class Command(BaseCommand):
    help = "Dezactivează atomic catalogul ONRC al unui județ."

    def add_arguments(self, parser):
        parser.add_argument("--county", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--acknowledgement", required=True)

    def handle(self, *args, **options):
        """Disable the pointer without deleting imported facts or audit history."""

        try:
            scope, changed = deactivate_catalogue_scope(
                county=options["county"],
                actor_username=options["actor"],
                acknowledgement=options["acknowledgement"],
            )
        except (
            CatalogueScope.DoesNotExist,
            get_user_model().DoesNotExist,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "changed": changed,
                    "county": scope.county,
                    "run_id": scope.current_run_id,
                    "visibility": scope.visibility,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
