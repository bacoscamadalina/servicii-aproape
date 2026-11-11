"""Atomically activate a JSON plan of county runs for internal preview."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from services.catalogue_activation import activate_catalogue_scopes_for_preview


class Command(BaseCommand):
    help = "Activează all-or-nothing mai multe județe exclusiv în preview intern."

    def add_arguments(self, parser):
        parser.add_argument("--plan", required=True, type=Path)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--acknowledgement", required=True)

    def handle(self, *args, **options):
        """Validate the explicit predecessor plan and swap all pointers atomically."""

        try:
            plans = json.loads(options["plan"].read_text(encoding="utf-8"))
            if not isinstance(plans, list) or not all(
                isinstance(plan, dict) for plan in plans
            ):
                raise ValueError("Planul trebuie să fie o listă JSON de obiecte")
            changed = activate_catalogue_scopes_for_preview(
                plans=plans,
                actor_username=options["actor"],
                acknowledgement=options["acknowledgement"],
            )
            self.stdout.write(
                json.dumps(
                    {
                        "changed_count": len(changed),
                        "counties": sorted(scope.county for scope in changed),
                        "visibility": "internal_preview",
                        "publication_active": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except (
            get_user_model().DoesNotExist,
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
