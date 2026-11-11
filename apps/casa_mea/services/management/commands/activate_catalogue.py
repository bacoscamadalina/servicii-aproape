"""Activate one audited catalogue run for preview or approved publication."""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from services.catalogue_activation import (
    ACKNOWLEDGEMENT,
    activate_catalogue_scope,
)
from services.models import CatalogueScope, ImportRun


class Command(BaseCommand):
    help = "Activează atomic un run ONRC auditat pentru un singur județ."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", type=int, required=True)
        parser.add_argument("--expected-scope-key", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument(
            "--visibility",
            required=True,
            choices=(
                CatalogueScope.Visibility.INTERNAL_PREVIEW,
                CatalogueScope.Visibility.PUBLIC,
            ),
        )
        parser.add_argument("--acknowledgement", required=True)

    def handle(self, *args, **options):
        """Perform a fail-closed activation and print its auditable outcome."""

        try:
            run = ImportRun.objects.get(pk=options["run_id"])
            scope, changed = activate_catalogue_scope(
                run=run,
                visibility=options["visibility"],
                actor_username=options["actor"],
                expected_scope_key=options["expected_scope_key"],
                acknowledgement=options["acknowledgement"],
            )
        except (
            ImportRun.DoesNotExist,
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
                    "registered_office_acknowledgement": ACKNOWLEDGEMENT,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
