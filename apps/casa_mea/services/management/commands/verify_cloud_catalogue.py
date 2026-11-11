"""Read-only deployment readiness: persistence is not publication approval."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from services.catalogue_activation import audit_run_for_catalogue, catalogue_state
from services.locations import county_choices
from services.models import CatalogueScope, RegisteredBusinessSnapshot


class Command(BaseCommand):
    """Refuse a missing national catalogue without changing visibility."""

    help = "Verify the restored national catalogue; report persistence and public visibility separately."

    def handle(self, *args, **options):
        """Check the complete county set and emit identity-free deployment totals."""
        scopes = list(CatalogueScope.objects.filter(provider="ONRC").select_related("current_run"))
        if {scope.county for scope in scopes} != {name for name, _ in county_choices()}:
            raise CommandError("The restored database does not contain all 42 ONRC county scopes.")
        if any(not scope.current_run or scope.current_run.state != "succeeded" for scope in scopes):
            raise CommandError("Every county must retain a completed current import run.")
        for scope in scopes:
            if scope.current_run.county != scope.county:
                raise CommandError("County pointer and current run disagree.")
            try:
                audit_run_for_catalogue(scope.current_run)
            except ValueError as exc:
                raise CommandError(f"Restored catalogue integrity failed for {scope.county}: {exc}") from exc
        totals = dict(RegisteredBusinessSnapshot.objects.filter(
            import_run_id__in=[scope.current_run_id for scope in scopes]
        ).values_list("import_run_id").annotate(total=Count("pk")))
        if not sum(totals.values()):
            raise CommandError("The restored current catalogue contains no firms.")
        public = sum(catalogue_state(scope.county).status == "active" for scope in scopes)
        self.stdout.write(json.dumps({
            "counties": len(scopes), "current_registry_rows": sum(totals.values()),
            "readable_counties_in_this_environment": public,
            "internal_preview_counties": sum(scope.visibility == "internal_preview" for scope in scopes),
        }, sort_keys=True))
        if public != len(scopes):
            self.stderr.write("Catalogue copied, NOT publicly approved: production keeps internal previews hidden.")
