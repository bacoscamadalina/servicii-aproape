"""Activation, fail-closed reading, pagination, and public-copy contracts."""

from datetime import timedelta
from threading import Barrier, Thread
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.db import connection
from django.test import TestCase, override_settings
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .caen import CAEN_MAPPING_HASH, CAEN_MAPPING_VERSION
from .catalog import CATEGORIES
from .catalogue_activation import (
    ACKNOWLEDGEMENT,
    PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
    activate_catalogue_scope,
    activate_catalogue_scopes_for_preview,
    audit_run_for_catalogue,
    catalogue_state,
    deactivate_catalogue_scope,
    record_publication_approval,
    revoke_publication_approval,
)
from .importers.locality_aliases import RULES_PATH, sha256_file
from .importers.onrc_statuses import POLICY_VERSION
from .models import (
    BusinessCaen,
    BusinessCategory,
    BusinessIdentity,
    BusinessStatus,
    CatalogueActivationEvent,
    CatalogueScope,
    ImportRun,
    PublicationApproval,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from .registry_catalogue import registry_search
from .staging import LOCALITY_POLICY, pilot_scope_key


class CatalogueFixtureMixin:
    """Build a complete miniature run that satisfies activation invariants."""

    def build_catalogue(self, total: int = 25):
        self.actor = get_user_model().objects.create_user(
            username="catalogue-operator", password=None, is_staff=True
        )
        self.snapshot = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date="2026-07-08",
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/dataset/firme-test",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        scope_key, categories = pilot_scope_key(
            "Iași", ["constructii", "instalatii"]
        )
        self.run = ImportRun.objects.create(
            snapshot=self.snapshot,
            scope_key=scope_key,
            county="Iași",
            categories=categories,
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
            state=ImportRun.State.SUCCEEDED,
        )
        records = []
        for index in range(total):
            identity = BusinessIdentity.objects.create(
                registration_number=f"J22/{index + 1}/2026"
            )
            records.append(
                RegisteredBusinessSnapshot.objects.create(
                    import_run=self.run,
                    business=identity,
                    legal_name=f"FIRMA {index:03d} SRL",
                    cui=f"RO{index:06d}",
                    registered_country_raw="România",
                    registered_county_raw="Iași",
                    registered_locality_raw="Municipiul Iaşi",
                    registered_office_siruta="95079",
                    locality_match="hierarchy_alias",
                    status_eligibility=(
                        RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE
                    ),
                    source_fingerprint=f"{index:032x}",
                )
            )
        BusinessStatus.objects.bulk_create(
            [BusinessStatus(business_snapshot=row, code="1048") for row in records]
        )
        BusinessCaen.objects.bulk_create(
            [
                BusinessCaen(business_snapshot=row, version="3", code="4100")
                for row in records
            ]
        )
        categories_to_create = [
            BusinessCategory(business_snapshot=row, category="constructii")
            for row in records
        ] + [
            BusinessCategory(business_snapshot=row, category="instalatii")
            for row in records[:5]
        ]
        BusinessCategory.objects.bulk_create(categories_to_create)
        self.run.counters = {
            "staged_businesses": total,
            "staged_statuses": total,
            "staged_caen": total,
            "staged_categories": total + min(total, 5),
            "quarantine_records": 0,
        }
        self.run.save(update_fields=("counters",))
        return records

    def activate_preview(self):
        return activate_catalogue_scope(
            run=self.run,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
            actor_username=self.actor.username,
            expected_scope_key=self.run.scope_key,
            acknowledgement=ACKNOWLEDGEMENT,
        )


class CatalogueActivationTests(CatalogueFixtureMixin, TestCase):
    def setUp(self):
        self.records = self.build_catalogue()

    def test_preview_activation_is_audited_idempotent_and_deactivatable(self):
        scope, changed = self.activate_preview()
        same_scope, changed_again = self.activate_preview()

        self.assertTrue(changed)
        self.assertFalse(changed_again)
        self.assertEqual(scope.pk, same_scope.pk)
        self.assertEqual(CatalogueActivationEvent.objects.count(), 1)
        self.assertEqual(
            scope.activation_events.get().audited_counters["staged_businesses"], 25
        )

        disabled, deactivated = deactivate_catalogue_scope(
            county="Iași",
            actor_username=self.actor.username,
            acknowledgement=ACKNOWLEDGEMENT,
        )
        self.assertTrue(deactivated)
        self.assertEqual(disabled.visibility, CatalogueScope.Visibility.OFF)
        self.assertEqual(CatalogueActivationEvent.objects.count(), 2)

    def test_batch_preview_activation_requires_expected_predecessor(self):
        plan = {
            "run_id": self.run.pk,
            "expected_scope_key": self.run.scope_key,
            "expected_previous_run_id": None,
        }
        changed = activate_catalogue_scopes_for_preview(
            plans=[plan],
            actor_username=self.actor.username,
            acknowledgement=ACKNOWLEDGEMENT,
        )
        self.assertEqual([scope.county for scope in changed], ["Iași"])
        with self.assertRaisesRegex(ValueError, "predecessor"):
            activate_catalogue_scopes_for_preview(
                plans=[plan],
                actor_username=self.actor.username,
                acknowledgement=ACKNOWLEDGEMENT,
            )
        scope = CatalogueScope.objects.get(county="Iași")
        self.assertEqual(scope.current_run, self.run)
        self.assertEqual(scope.visibility, CatalogueScope.Visibility.INTERNAL_PREVIEW)

    def test_batch_preview_rolls_back_all_scopes_when_second_audit_fails(self):
        scope_key, categories = pilot_scope_key(
            "Neamț", ["constructii", "instalatii"]
        )
        second_run = ImportRun.objects.create(
            snapshot=self.snapshot,
            scope_key=scope_key,
            county="Neamț",
            categories=categories,
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
            state=ImportRun.State.SUCCEEDED,
            counters={
                "staged_businesses": 1,
                "staged_statuses": 1,
                "staged_caen": 1,
                "staged_categories": 1,
                "quarantine_records": 0,
            },
        )
        identity = BusinessIdentity.objects.create(registration_number="J27/1/2026")
        row = RegisteredBusinessSnapshot.objects.create(
            import_run=second_run,
            business=identity,
            legal_name="NEAMT TEST SRL",
            registered_country_raw="România",
            registered_county_raw="Neamț",
            registered_locality_raw="Piatra-Neamț",
            registered_office_siruta="120735",
            locality_match="exact",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="e" * 32,
        )
        BusinessCaen.objects.create(business_snapshot=row, version="3", code="4100")
        BusinessCategory.objects.create(
            business_snapshot=row, category="constructii"
        )
        plans = [
            {
                "run_id": run.pk,
                "expected_scope_key": run.scope_key,
                "expected_previous_run_id": None,
            }
            for run in (self.run, second_run)
        ]

        with self.assertRaisesRegex(ValueError, "statusul 1048"):
            activate_catalogue_scopes_for_preview(
                plans=plans,
                actor_username=self.actor.username,
                acknowledgement=ACKNOWLEDGEMENT,
            )

        self.assertFalse(CatalogueScope.objects.exclude(current_run=None).exists())
        self.assertFalse(CatalogueActivationEvent.objects.exists())

    def test_activation_refuses_bad_acknowledgement_scope_and_invalid_relations(self):
        with self.assertRaisesRegex(ValueError, "Confirmarea"):
            activate_catalogue_scope(
                run=self.run,
                visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
                actor_username=self.actor.username,
                expected_scope_key=self.run.scope_key,
                acknowledgement="yes",
            )
        with self.assertRaisesRegex(ValueError, "Scope key"):
            activate_catalogue_scope(
                run=self.run,
                visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
                actor_username=self.actor.username,
                expected_scope_key="0" * 64,
                acknowledgement=ACKNOWLEDGEMENT,
            )
        self.records[0].statuses.update(code="1084")
        with self.assertRaisesRegex(ValueError, "statusul 1048"):
            audit_run_for_catalogue(self.run)

    def test_public_activation_requires_current_approval_for_the_same_run(self):
        with self.assertRaisesRegex(ValueError, "aprobare de publicare"):
            activate_catalogue_scope(
                run=self.run,
                visibility=CatalogueScope.Visibility.PUBLIC,
                actor_username=self.actor.username,
                expected_scope_key=self.run.scope_key,
                acknowledgement=ACKNOWLEDGEMENT,
            )
        approval = PublicationApproval.objects.create(
            import_run=self.run,
            approved_by=self.actor,
            approved_at=timezone.now(),
            review_reference="LEGAL-REVIEW-TEST",
            review_due_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ValueError, "aprobare de publicare"):
            activate_catalogue_scope(
                run=self.run,
                visibility=CatalogueScope.Visibility.PUBLIC,
                actor_username=self.actor.username,
                expected_scope_key=self.run.scope_key,
                acknowledgement=ACKNOWLEDGEMENT,
            )
        approval.review_due_at = timezone.now() + timedelta(days=1)
        approval.save(update_fields=("review_due_at",))
        scope, changed = activate_catalogue_scope(
            run=self.run,
            visibility=CatalogueScope.Visibility.PUBLIC,
            actor_username=self.actor.username,
            expected_scope_key=self.run.scope_key,
            acknowledgement=ACKNOWLEDGEMENT,
        )
        self.assertTrue(changed)
        self.assertEqual(scope.current_approval, approval)
        approval.state = PublicationApproval.State.REVOKED
        approval.revoked_at = timezone.now()
        approval.revoked_by = self.actor
        approval.save(update_fields=("state", "revoked_at", "revoked_by"))
        self.assertEqual(catalogue_state("Iași").status, "unavailable")

    def test_public_reactivation_rotates_to_the_latest_valid_approval(self):
        first = PublicationApproval.objects.create(
            import_run=self.run,
            approval_version=1,
            approved_by=self.actor,
            approved_at=timezone.now(),
            review_reference="LEGAL-REVIEW-V1",
            review_due_at=timezone.now() + timedelta(days=1),
        )
        scope, changed = activate_catalogue_scope(
            run=self.run,
            visibility=CatalogueScope.Visibility.PUBLIC,
            actor_username=self.actor.username,
            expected_scope_key=self.run.scope_key,
            acknowledgement=ACKNOWLEDGEMENT,
        )
        self.assertTrue(changed)
        self.assertEqual(scope.current_approval, first)

        first.state = PublicationApproval.State.REVOKED
        first.revoked_at = timezone.now()
        first.revoked_by = self.actor
        first.save(update_fields=("state", "revoked_at", "revoked_by"))
        second = PublicationApproval.objects.create(
            import_run=self.run,
            approval_version=2,
            approved_by=self.actor,
            approved_at=timezone.now(),
            review_reference="LEGAL-REVIEW-V2",
            review_due_at=timezone.now() + timedelta(days=2),
        )

        scope, changed = activate_catalogue_scope(
            run=self.run,
            visibility=CatalogueScope.Visibility.PUBLIC,
            actor_username=self.actor.username,
            expected_scope_key=self.run.scope_key,
            acknowledgement=ACKNOWLEDGEMENT,
        )

        self.assertTrue(changed)
        self.assertEqual(scope.current_approval, second)
        self.assertEqual(scope.activation_events.count(), 2)
        self.assertEqual(catalogue_state("Iași").status, "active")

    def test_publication_approvals_are_permission_gated_versioned_and_revocable(self):
        with self.assertRaisesRegex(ValueError, "permisiunea"):
            record_publication_approval(
                run=self.run,
                actor_username=self.actor.username,
                review_reference="LEGAL-1",
                review_due_at=timezone.now() + timedelta(days=30),
                acknowledgement=PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
            )
        permission = Permission.objects.get(
            codename="approve_catalogue_publication"
        )
        self.actor.user_permissions.add(permission)
        first = record_publication_approval(
            run=self.run,
            actor_username=self.actor.username,
            review_reference="LEGAL-1",
            review_due_at=timezone.now() + timedelta(days=30),
            acknowledgement=PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
        )
        revoked, changed = revoke_publication_approval(
            approval=first, actor_username=self.actor.username
        )
        second = record_publication_approval(
            run=self.run,
            actor_username=self.actor.username,
            review_reference="LEGAL-2",
            review_due_at=timezone.now() + timedelta(days=60),
            acknowledgement=PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
        )

        self.assertTrue(changed)
        self.assertEqual(revoked.state, PublicationApproval.State.REVOKED)
        self.assertEqual((first.approval_version, second.approval_version), (1, 2))

    @override_settings(DEBUG=True)
    def test_reader_is_preview_only_in_debug_and_fails_closed_on_stale_run(self):
        self.activate_preview()
        self.assertEqual(catalogue_state("Iași").status, "active")
        with override_settings(DEBUG=False):
            self.assertEqual(catalogue_state("Iași").status, "unavailable")
        self.run.state = ImportRun.State.FAILED
        self.run.save(update_fields=("state",))
        self.assertEqual(catalogue_state("Iași").status, "unavailable")


@skipUnless(connection.vendor == "postgresql", "Necesită blocare PostgreSQL reală")
class CatalogueActivationConcurrencyTests(CatalogueFixtureMixin, TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        records = self.build_catalogue(total=2)
        snapshot = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date="2026-08-08",
            manifest_sha256="b" * 64,
            dataset_url="https://data.gov.ro/dataset/firme-test-2",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        self.second_run = ImportRun.objects.create(
            snapshot=snapshot,
            scope_key=self.run.scope_key,
            county=self.run.county,
            categories=self.run.categories,
            caen_mapping_version=self.run.caen_mapping_version,
            caen_mapping_hash=self.run.caen_mapping_hash,
            status_policy_version=self.run.status_policy_version,
            locality_policy=self.run.locality_policy,
            locality_rules_hash=self.run.locality_rules_hash,
            state=ImportRun.State.SUCCEEDED,
        )
        second_records = []
        for index, record in enumerate(records):
            second_records.append(
                RegisteredBusinessSnapshot.objects.create(
                    import_run=self.second_run,
                    business=record.business,
                    legal_name=f"NOUA FIRMA {index} SRL",
                    registered_country_raw="România",
                    registered_county_raw="Iași",
                    registered_locality_raw="Municipiul Iaşi",
                    registered_office_siruta="95079",
                    locality_match="hierarchy_alias",
                    status_eligibility=(
                        RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE
                    ),
                    source_fingerprint=f"{index + 20:032x}",
                )
            )
        BusinessStatus.objects.bulk_create(
            [BusinessStatus(business_snapshot=row, code="1048") for row in second_records]
        )
        BusinessCaen.objects.bulk_create(
            [
                BusinessCaen(business_snapshot=row, version="3", code="4100")
                for row in second_records
            ]
        )
        BusinessCategory.objects.bulk_create(
            [
                BusinessCategory(business_snapshot=row, category="constructii")
                for row in second_records
            ]
            + [
                BusinessCategory(business_snapshot=row, category="instalatii")
                for row in second_records
            ]
        )
        self.second_run.counters = {
            "staged_businesses": 2,
            "staged_statuses": 2,
            "staged_caen": 2,
            "staged_categories": 4,
            "quarantine_records": 0,
        }
        self.second_run.save(update_fields=("counters",))

    def test_two_activations_serialize_on_the_county_pointer(self):
        barrier = Barrier(2)
        errors = []

        def activate(run_id):
            connection.close()
            try:
                run = ImportRun.objects.get(pk=run_id)
                barrier.wait()
                activate_catalogue_scope(
                    run=run,
                    visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
                    actor_username=self.actor.username,
                    expected_scope_key=run.scope_key,
                    acknowledgement=ACKNOWLEDGEMENT,
                )
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)
            finally:
                connection.close()

        threads = [
            Thread(target=activate, args=(self.run.pk,)),
            Thread(target=activate, args=(self.second_run.pk,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        scope = CatalogueScope.objects.get(provider="ONRC", county="Iași")
        self.assertIn(scope.current_run_id, (self.run.pk, self.second_run.pk))
        self.assertEqual(scope.activation_events.count(), 2)


class RegistryReaderTests(CatalogueFixtureMixin, TestCase):
    def setUp(self):
        self.build_catalogue()

    def test_all_categories_are_deduplicated_and_paginated_stably(self):
        first = registry_search(
            run=self.run,
            county="Iași",
            allow_direct_evidence=False,
            siruta_code="95079",
            locality_label="Iași",
            category="",
            page_number="1",
        )
        second = registry_search(
            run=self.run,
            county="Iași",
            allow_direct_evidence=False,
            siruta_code="95079",
            locality_label="Iași",
            category="",
            page_number="2",
        )
        installations = registry_search(
            run=self.run,
            county="Iași",
            allow_direct_evidence=False,
            siruta_code="95079",
            locality_label="Iași",
            category="instalatii",
            page_number="1",
        )

        self.assertEqual(first.total, 25)
        self.assertEqual(len(first.page.object_list), 20)
        self.assertEqual(len(second.page.object_list), 5)
        self.assertEqual(installations.total, 5)
        self.assertEqual(first.page.object_list[0].legal_name, "FIRMA 000 SRL")
        self.assertFalse(hasattr(first.page.object_list[0], "cui"))

    def test_county_search_does_not_require_a_locality(self):
        result = registry_search(
            run=self.run,
            county="Iași",
            allow_direct_evidence=False,
            siruta_code=None,
            locality_label="",
            category="constructii",
            page_number="1",
        )

        self.assertEqual(result.total, 25)
        self.assertEqual(result.page.object_list[0].registered_office_label, "Iași")


@override_settings(DEBUG=True)
class RegistryHomeTests(CatalogueFixtureMixin, TestCase):
    def setUp(self):
        self.build_catalogue()
        self.activate_preview()

    def test_real_results_use_registry_copy_and_whitelisted_projection(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Iași", "locality": "95079", "category": "constructii"},
        )

        self.assertContains(response, "25 înregistrări")
        self.assertContains(response, "FIRMA 000 SRL")
        self.assertContains(response, "Sediu social · Iași")
        self.assertContains(response, "Pagina 1 din 2")
        self.assertContains(response, "previzualizare internă ONRC")
        self.assertNotContains(response, "RO000000")
        self.assertNotContains(response, "Experiență declarată")
        self.assertNotContains(response, "Timp de răspuns declarat")
        self.assertNotContains(response, ">disponibili<", html=True)
        self.assertNotContains(response, "lucrează în zona ta")

    def test_county_only_search_lists_results_and_opens_their_company_page(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Iași", "locality": "", "category": "constructii"},
        )

        record = RegisteredBusinessSnapshot.objects.get(
            import_run=self.run, legal_name="FIRMA 000 SRL"
        )
        detail_url = reverse("services:company_detail", args=(record.business_id,))
        self.assertContains(response, "25 înregistrări")
        self.assertContains(response, "Județul Iași")
        self.assertContains(response, "Sediu social · Iași")
        self.assertContains(response, f'{detail_url}?county=Ia%C8%99i&amp;locality=&amp;category=constructii')

        detail = self.client.get(
            detail_url,
            {"county": "Iași", "locality": "", "category": "constructii"},
        )
        self.assertContains(detail, "FIRMA 000 SRL")
        self.assertContains(detail, "Iași, Iași", count=2)

    def test_active_scope_never_falls_back_to_demo(self):
        self.run.state = ImportRun.State.FAILED
        self.run.save(update_fields=("state",))
        response = self.client.get(
            reverse("services:home"),
            {"county": "Iași", "locality": "95079", "category": "instalatii"},
        )

        self.assertContains(response, "momentan indisponibil")
        self.assertNotContains(response, "Instal Pro Iași")

    def test_outside_active_scope_keeps_a_clearly_marked_demo(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Cluj", "locality": "54984", "category": "constructii"},
        )

        self.assertContains(response, "Nord Construct")
        self.assertContains(response, "exemple demonstrative")

    def test_unsupported_category_does_not_leak_other_results(self):
        response = self.client.get(
            reverse("services:home"),
            {"county": "Iași", "locality": "95079", "category": "gradinarit"},
        )

        self.assertContains(response, "Categoria nu este încă inclusă")
        self.assertNotContains(response, "FIRMA 000 SRL")

    def test_company_detail_is_whitelisted_and_bound_to_active_search_scope(self):
        record = RegisteredBusinessSnapshot.objects.get(
            import_run=self.run, legal_name="FIRMA 000 SRL"
        )
        url = reverse("services:company_detail", args=(record.business_id,))
        response = self.client.get(url, {
            "county": "Iași",
            "locality": "95079",
            "category": "constructii",
        })

        self.assertContains(response, "FIRMA 000 SRL")
        self.assertContains(response, "Servicii identificate")
        self.assertContains(response, "Construcții")
        self.assertContains(response, "Sediu social")
        self.assertContains(response, "Iași, Iași", count=2)
        self.assertContains(response, "Este firma ta?")
        self.assertContains(response, "Vezi sursele datelor")
        self.assertEqual(response.context["art_category"], "constructii")
        self.assertEqual(response.context["art_photo"], "services/category-photos/constructii.webp")
        self.assertContains(response, "category-photos/constructii.webp")
        self.assertContains(response, "Fotografie ilustrativă")
        self.assertNotContains(response, "Important:")
        self.assertNotContains(response, "RO000000")
        self.assertNotContains(response, "J22/1/2026")
        self.assertNotContains(response, "registered_locality_raw")

        wrong_locality = self.client.get(url, {
            "county": "Iași",
            "locality": "95408",
            "category": "constructii",
        })
        self.assertEqual(wrong_locality.status_code, 404)

    def test_registry_firm_can_be_saved_from_detail_and_removed(self):
        """Registry bookmarks remain scoped, session-only and visible on the saved page."""

        record = RegisteredBusinessSnapshot.objects.get(
            import_run=self.run, legal_name="FIRMA 000 SRL"
        )
        query = {"county": "Iași", "locality": "", "category": "constructii"}
        toggle = reverse("services:company_shortlist_toggle", args=(record.business_id,))
        home = self.client.get(reverse("services:home"), query)
        self.assertNotContains(home, "Salvează firma")
        detail_url = reverse("services:company_detail", args=(record.business_id,))
        detail_before = self.client.get(detail_url, query)
        self.assertContains(detail_before, f"{toggle}?county=Ia%C8%99i&amp;locality=&amp;category=constructii")
        self.assertContains(detail_before, 'aria-label="Salvează firma"')

        self.assertEqual(self.client.get(toggle, query).status_code, 405)
        saved = self.client.post(toggle + "?county=Ia%C8%99i&locality=&category=constructii", {"return_to": "detail"})
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self.client.session["registry_shortlist_v1"][0]["business_id"], record.business_id)
        detail = self.client.get(detail_url, query)
        self.assertContains(detail, 'aria-label="Elimină din lista salvată"')
        shortlist = self.client.get(reverse("services:provider_shortlist"))
        self.assertContains(shortlist, "FIRMA 000 SRL")
        self.assertContains(shortlist, "Fișă publică ONRC")
        self.assertIn("no-store", shortlist.headers["Cache-Control"])

        removed = self.client.post(toggle + "?county=Ia%C8%99i&locality=&category=constructii", {"return_to": "shortlist"})
        self.assertRedirects(removed, reverse("services:provider_shortlist"))
        self.assertEqual(self.client.session["registry_shortlist_v1"], [])

    def test_registry_shortlist_revalidates_scope_and_active_catalogue(self):
        """A bookmark cannot rescue an unavailable record or bypass its search scope."""

        record = RegisteredBusinessSnapshot.objects.get(
            import_run=self.run, legal_name="FIRMA 000 SRL"
        )
        toggle = reverse("services:company_shortlist_toggle", args=(record.business_id,))
        self.assertEqual(self.client.post(toggle, {"return_to": "detail"}).status_code, 404)
        self.assertEqual(self.client.post(toggle, {"county": "Iași", "locality": "95408", "category": "constructii"}).status_code, 404)
        self.assertNotIn("registry_shortlist_v1", self.client.session)

        self.client.post(toggle + "?county=Ia%C8%99i&locality=&category=constructii")
        self.run.state = ImportRun.State.FAILED
        self.run.save(update_fields=("state",))
        shortlist = self.client.get(reverse("services:provider_shortlist"))
        self.assertNotContains(shortlist, "FIRMA 000 SRL")
        self.assertEqual(self.client.session["registry_shortlist_v1"], [])

    def test_registry_shortlist_is_bounded_and_rejects_unsafe_return_urls(self):
        """Only six scoped identities persist and redirects never use user URLs."""

        records = RegisteredBusinessSnapshot.objects.filter(import_run=self.run).order_by("legal_name")[:7]
        for record in records:
            toggle = reverse("services:company_shortlist_toggle", args=(record.business_id,))
            response = self.client.post(
                f"{toggle}?county=Ia%C8%99i&locality=&category=constructii",
                {"return_to": "https://elsewhere.invalid/"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("/?county="))
        entries = self.client.session["registry_shortlist_v1"]
        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0]["business_id"], records[6].business_id)

    def test_company_detail_uses_the_permanent_nordic_design(self):
        record = RegisteredBusinessSnapshot.objects.get(
            import_run=self.run, legal_name="FIRMA 000 SRL"
        )
        response = self.client.get(
            reverse("services:company_detail", args=(record.business_id,)),
            {
                "county": "Iași",
                "locality": "95079",
                "category": "constructii",
                "design": "steel",
            },
        )

        self.assertContains(response, "company-design-nordic")
        self.assertNotContains(response, "Previzualizare design")

        county_response = self.client.get(
            reverse("services:company_detail", args=(record.business_id,)),
            {"county": "Iași"},
        )
        self.assertEqual(county_response.context["art_category"], "constructii")

    def test_every_curated_service_has_an_editorial_photo(self):
        """The validated service slug always resolves to a packaged static asset."""

        for slug, _label, _description in CATEGORIES:
            with self.subTest(slug=slug):
                self.assertTrue(finders.find(f"services/category-photos/{slug}.webp"))

    def test_company_detail_fails_closed_when_catalogue_becomes_unavailable(self):
        record = RegisteredBusinessSnapshot.objects.filter(import_run=self.run).first()
        self.run.state = ImportRun.State.FAILED
        self.run.save(update_fields=("state",))

        response = self.client.get(
            reverse("services:company_detail", args=(record.business_id,)),
            {"county": "Iași", "locality": "95079", "category": ""},
        )

        self.assertEqual(response.status_code, 404)
