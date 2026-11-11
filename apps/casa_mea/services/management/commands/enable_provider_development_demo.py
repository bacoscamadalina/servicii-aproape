"""Enable one explicit, auditable provider journey in development only."""

from datetime import date
import hashlib
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from services.catalog import CATEGORIES
from services.models import (
    BusinessCategory,
    CatalogueScope,
    ImportRun,
    ProviderDevelopmentDemoGrant,
    ProviderMembership,
    ProviderRegistrationRequest,
    ProviderServiceAreaDraft,
    ProviderSubscription,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from services.provider_subscriptions import (
    SUBSCRIPTION_ACKNOWLEDGEMENT,
    activate_or_extend_provider_subscription,
    provider_subscription_state,
)
from services.provider_offerings import replace_provider_services_and_coverage_for_owner


DEMO_ACKNOWLEDGEMENT = "SERVICIIAPROAPE_DEVELOPMENT_DEMO_ONLY"


class Command(BaseCommand):
    help = "Activează autorizarea și abonamentul de test pentru un furnizor demo."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--category", action="append", dest="categories")
        parser.add_argument("--acknowledgement", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        """Create isolated demo provenance and activate one 30-day entitlement."""

        if not settings.PROVIDER_DEVELOPMENT_DEMO_ENABLED:
            raise CommandError("Modul demonstrativ este dezactivat în acest mediu.")
        if options["acknowledgement"] != DEMO_ACKNOWLEDGEMENT:
            raise CommandError("Confirmarea explicită a modului demonstrativ lipsește.")

        User = get_user_model()
        try:
            actor = User.objects.get(username=options["actor"], is_active=True)
            memberships = list(
                ProviderMembership.objects.select_related("profile__business", "user")
                .filter(user__email__iexact=options["email"], state="active")[:2]
            )
            if len(memberships) != 1:
                raise CommandError("Adresa trebuie să aibă exact un profil activ.")
            profile = memberships[0].profile
            registration = ProviderRegistrationRequest.objects.get(
                converted_claim=profile.approved_claim,
                linked_business=profile.business,
                status=ProviderRegistrationRequest.Status.CONVERTED,
            )
        except (User.DoesNotExist, ProviderRegistrationRequest.DoesNotExist) as error:
            raise CommandError("Profilul demo sau înscrierea verificată nu există.") from error

        required_permissions = (
            "services.manage_provider_development_demo",
            "services.manage_provider_subscription",
        )
        if not actor.is_staff or any(
            not actor.has_perm(permission) for permission in required_permissions
        ):
            raise CommandError("Operatorul nu are permisiunile necesare demonstrației.")

        known_categories = {slug for slug, _label, _description in CATEGORIES}
        categories = sorted(set(options["categories"] or ("constructii",)))
        if not categories or set(categories) - known_categories:
            raise CommandError("Categoria demonstrativă nu este recunoscută.")

        try:
            scope = CatalogueScope.objects.select_for_update().select_related(
                "current_run"
            ).get(
                provider="ONRC",
                county=registration.registered_county,
                current_run__isnull=False,
            )
        except CatalogueScope.DoesNotExist as error:
            raise CommandError("Județul firmei nu are un catalog ONRC activ.") from error

        manifest = hashlib.sha256(b"serviciiaproape-provider-demo-v1").hexdigest()
        snapshot, _created = SourceSnapshot.objects.get_or_create(
            provider="SERVICIIAPROAPE_DEMO",
            snapshot_date=date(2000, 1, 1),
            defaults={
                "manifest_sha256": manifest,
                "dataset_url": "https://localhost.invalid/serviciiaproape-provider-demo",
                "license_label": "Date sintetice pentru dezvoltare",
                "verified_resources": {"synthetic": True, "schema_version": 1},
            },
        )
        scope_payload = json.dumps(
            {"profile_id": profile.pk, "categories": categories},
            sort_keys=True,
            separators=(",", ":"),
        )
        scope_key = hashlib.sha256(scope_payload.encode()).hexdigest()
        authorization_run, _created = ImportRun.objects.get_or_create(
            snapshot=snapshot,
            scope_key=scope_key,
            defaults={
                "county": registration.registered_county,
                "categories": categories,
                "caen_mapping_version": "demo-v1",
                "caen_mapping_hash": hashlib.sha256(
                    ",".join(categories).encode()
                ).hexdigest(),
                "status_policy_version": "demo-v1",
                "locality_policy": "development_demo_only",
                "locality_rules_hash": hashlib.sha256(b"demo-exact-siruta").hexdigest(),
                "state": ImportRun.State.SUCCEEDED,
                "attempt_count": 1,
                "counters": {"synthetic_provider_records": 1},
            },
        )
        business_snapshot, _created = RegisteredBusinessSnapshot.objects.get_or_create(
            import_run=authorization_run,
            business=profile.business,
            defaults={
                "legal_name": registration.legal_name,
                "cui": registration.cui,
                "registered_country_raw": "ROMÂNIA",
                "registered_county_raw": registration.registered_county,
                "registered_locality_raw": registration.registered_office_siruta,
                "registered_office_siruta": registration.registered_office_siruta,
                "locality_match": "exact",
                "status_eligibility": RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
                "source_fingerprint": hashlib.sha256(
                    f"demo:{profile.business_id}".encode()
                ).hexdigest()[:32],
            },
        )
        BusinessCategory.objects.bulk_create(
            (
                BusinessCategory(business_snapshot=business_snapshot, category=category)
                for category in categories
            ),
            ignore_conflicts=True,
        )
        ProviderDevelopmentDemoGrant.objects.update_or_create(
            profile=profile,
            defaults={
                "authorization_run": authorization_run,
                "catalogue_run": scope.current_run,
                "enabled": True,
                "internal_note": (
                    "Acces sintetic exclusiv pentru testarea fluxului complet în development; "
                    "nu reprezintă o autorizare ONRC și nu dovedește o plată."
                ),
                "created_by": actor,
            },
        )

        # Preserve an already prepared private draft, but repin it to the newly
        # explicit demo authorization so the owner can submit it immediately.
        draft = ProviderServiceAreaDraft.objects.filter(profile=profile).first()
        if draft and draft.revision:
            services = list(draft.services.values_list("category", flat=True))
            coverage = list(draft.coverage.values_list("county", "siruta_code"))
            if services and coverage:
                replace_provider_services_and_coverage_for_owner(
                    user=memberships[0].user,
                    expected_revision=draft.revision,
                    categories=services,
                    coverage_pairs=coverage,
                )

        subscription_state = provider_subscription_state(profile, lock=True)
        if not subscription_state.is_active:
            activate_or_extend_provider_subscription(
                profile_id=profile.pk,
                actor=actor,
                expected_revision=subscription_state.revision,
                internal_note=(
                    "Abonament demonstrativ pentru verificarea manuală a fluxului; "
                    "nicio plată nu a fost procesată."
                ),
                acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
            )

        subscription = ProviderSubscription.objects.get(profile=profile)
        self.stdout.write(
            self.style.SUCCESS(
                " ".join(
                    (
                        f"profile_id={profile.pk}",
                        f"authorization_run_id={authorization_run.pk}",
                        f"catalogue_run_id={scope.current_run_id}",
                        f"subscription_ends_at={subscription.period_ends_at.isoformat()}",
                    )
                )
            )
        )
