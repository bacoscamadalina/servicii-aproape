"""Contract tests for private provider service and coverage declarations."""

from datetime import date, timedelta
from threading import Barrier, Thread
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .locations import SIRUTA_CATALOGUE_VERSION, siruta_catalogue_sha256
from .models import (
    BusinessCaen,
    BusinessCategory,
    BusinessIdentity,
    CatalogueScope,
    ImportRun,
    ProviderClaimRequest,
    ProviderDraftCoverage,
    ProviderDraftService,
    ProviderDevelopmentDemoGrant,
    ProviderMembership,
    ProviderProfile,
    ProviderRegistrationRequest,
    ProviderServiceAreaDraft,
    ProviderServiceAreaSubmission,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from .provider_offerings import (
    REVIEW_ACKNOWLEDGEMENT,
    provider_authorization,
    replace_provider_services_and_coverage_for_owner,
    review_provider_service_area_submission,
    submit_provider_service_area_for_review,
)


class ProviderOfferingFixtureMixin:
    """Create one provider backed by a coherent current ONRC base run."""

    def create_fixture(self):
        User = get_user_model()
        self.reviewer = User.objects.create_user(
            username="reviewer-offerings", email="reviewer@example.test", is_staff=True
        )
        self.owner = User.objects.create_user(
            username="provider-owner", email="owner@example.test", is_active=True
        )
        self.onrc = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date=date(2026, 7, 8),
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/onrc",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        self.mf = SourceSnapshot.objects.create(
            provider="MF_FINANCIAL_STATEMENTS",
            snapshot_date=date(2024, 12, 31),
            manifest_sha256="b" * 64,
            dataset_url="https://data.gov.ro/mf",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        self.base = ImportRun.objects.create(
            snapshot=self.onrc,
            scope_key="c" * 64,
            county="Iași",
            categories=["constructii", "instalatii"],
            caen_mapping_version="2",
            caen_mapping_hash="d" * 64,
            status_policy_version="1",
            locality_policy="approved_hierarchy_aliases",
            locality_rules_hash="e" * 64,
            state=ImportRun.State.SUCCEEDED,
        )
        self.current = ImportRun.objects.create(
            snapshot=self.onrc,
            scope_key="f" * 64,
            county="Iași",
            categories=["constructii", "instalatii"],
            caen_mapping_version="2",
            caen_mapping_hash="d" * 64,
            status_policy_version="1",
            locality_policy="approved_hierarchy_aliases",
            locality_rules_hash="e" * 64,
            scope_contract_version=2,
            refined_from_run=self.base,
            activity_evidence_snapshot=self.mf,
            activity_evidence_policy_version="1",
            activity_evidence_policy_hash="1" * 64,
            activity_evidence_year=2024,
            state=ImportRun.State.SUCCEEDED,
        )
        self.business = BusinessIdentity.objects.create(registration_number="J22/1/2020")
        snapshot = RegisteredBusinessSnapshot.objects.create(
            import_run=self.base,
            business=self.business,
            legal_name="Atelier Test SRL",
            registered_country_raw="ROMANIA",
            registered_county_raw="Iași",
            registered_locality_raw="Iași",
            registered_office_siruta="95079",
            locality_match="exact",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="0" * 32,
        )
        BusinessCategory.objects.create(
            business_snapshot=snapshot, category="constructii"
        )
        CatalogueScope.objects.create(
            provider="ONRC",
            county="Iași",
            current_run=self.current,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
            activated_at=timezone.now(),
        )
        now = timezone.now()
        claim = ProviderClaimRequest.objects.create(
            business=self.business,
            legal_name_at_request="Atelier Test SRL",
            contact_name="Ana Test",
            role="administrator",
            email="owner@example.test",
            status=ProviderClaimRequest.Status.APPROVED,
            token_digest="2" * 64,
            token_expires_at=now + timedelta(hours=1),
            email_verified_at=now,
            privacy_notice_version="1",
            consented_at=now,
            reviewed_at=now,
            reviewed_by=self.reviewer,
            review_note="Verificare administrativă separată.",
            approval_policy_version="1",
        )
        self.profile = ProviderProfile.objects.create(
            business=self.business,
            approved_claim=claim,
            display_name="Atelier Test",
        )
        self.membership = ProviderMembership.objects.create(
            profile=self.profile,
            user=self.owner,
            state=ProviderMembership.State.ACTIVE,
            invited_at=now,
            activated_at=now,
        )


class ProviderOfferingServiceTests(ProviderOfferingFixtureMixin, TestCase):
    def setUp(self):
        self.create_fixture()

    def test_electrical_caen_unlocks_the_precise_electrician_service(self):
        snapshot = RegisteredBusinessSnapshot.objects.get(
            import_run=self.base, business=self.business
        )
        BusinessCaen.objects.create(
            business_snapshot=snapshot, version="2", code="4321"
        )

        authorization = provider_authorization(self.profile)

        self.assertEqual(
            authorization.categories,
            frozenset({"constructii", "electricieni"}),
        )

    def save(self, **overrides):
        values = {
            "user": self.owner,
            "expected_revision": 0,
            "categories": ["constructii"],
            "coverage_pairs": [("Iași", "95079")],
        }
        values.update(overrides)
        return replace_provider_services_and_coverage_for_owner(**values)

    def _replace_real_authorization_with_demo_grant(self):
        """Build synthetic provenance without mutating the active ONRC scope."""

        self.business.snapshot_records.filter(import_run=self.base).delete()
        demo_source = SourceSnapshot.objects.create(
            provider="SERVICIIAPROAPE_DEMO",
            snapshot_date=date(2000, 1, 1),
            manifest_sha256="9" * 64,
            dataset_url="https://localhost.invalid/provider-demo",
            license_label="Date sintetice pentru dezvoltare",
            verified_resources={"synthetic": True},
        )
        demo_run = ImportRun.objects.create(
            snapshot=demo_source,
            scope_key="8" * 64,
            county="Iași",
            categories=["constructii"],
            caen_mapping_version="demo-v1",
            caen_mapping_hash="7" * 64,
            status_policy_version="demo-v1",
            locality_policy="development_demo_only",
            locality_rules_hash="6" * 64,
            state=ImportRun.State.SUCCEEDED,
        )
        snapshot = RegisteredBusinessSnapshot.objects.create(
            import_run=demo_run,
            business=self.business,
            legal_name="Atelier demonstrativ SRL",
            registered_county_raw="Iași",
            registered_locality_raw="Iași",
            registered_office_siruta="95079",
            locality_match="exact",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="5" * 32,
        )
        BusinessCategory.objects.create(
            business_snapshot=snapshot, category="constructii"
        )
        ProviderDevelopmentDemoGrant.objects.create(
            profile=self.profile,
            authorization_run=demo_run,
            catalogue_run=self.current,
            enabled=True,
            internal_note="Demonstrație explicită, fără date ONRC și fără plată.",
            created_by=self.reviewer,
        )
        return demo_run

    @override_settings(PROVIDER_DEVELOPMENT_DEMO_ENABLED=True)
    def test_explicit_development_grant_unlocks_only_its_synthetic_categories(self):
        demo_run = self._replace_real_authorization_with_demo_grant()

        authorization = provider_authorization(self.profile)

        self.assertEqual(authorization.run, demo_run)
        self.assertEqual(authorization.catalogue_run, self.current)
        self.assertEqual(authorization.categories, frozenset({"constructii"}))
        self.assertTrue(authorization.is_demo)

    @override_settings(PROVIDER_DEVELOPMENT_DEMO_ENABLED=False)
    def test_development_grant_is_ignored_when_environment_disables_it(self):
        self._replace_real_authorization_with_demo_grant()

        with self.assertRaisesMessage(ValueError, "nu pot fi determinate"):
            provider_authorization(self.profile)

    def test_atomic_save_pins_sources_and_normalizes_children(self):
        draft, changed = self.save(
            categories=["constructii", "constructii"],
            coverage_pairs=[("Iași", "95079"), ("Iași", "95079")],
        )
        self.assertTrue(changed)
        self.assertEqual(draft.revision, 1)
        self.assertEqual(draft.authorization_run, self.base)
        self.assertEqual(draft.siruta_catalogue_version, SIRUTA_CATALOGUE_VERSION)
        self.assertEqual(draft.siruta_catalogue_sha256, siruta_catalogue_sha256())
        self.assertEqual(
            list(ProviderDraftService.objects.values_list("category", flat=True)),
            ["constructii"],
        )
        self.assertEqual(
            list(ProviderDraftCoverage.objects.values_list("county", "siruta_code")),
            [("Iași", "95079")],
        )

    def test_unauthorized_category_and_wrong_siruta_fail_without_writes(self):
        with self.assertRaisesMessage(ValueError, "autorizate ONRC"):
            self.save(categories=["gradinarit"])
        with self.assertRaisesMessage(ValueError, "SIRUTA invalidă"):
            self.save(coverage_pairs=[("Neamț", "95079")])
        self.assertFalse(ProviderServiceAreaDraft.objects.exists())

    def test_empty_sets_are_rejected(self):
        with self.assertRaises(ValueError):
            self.save(categories=[])
        with self.assertRaises(ValueError):
            self.save(coverage_pairs=[])

    def test_identical_save_is_noop_and_stale_revision_is_rejected(self):
        draft, _changed = self.save()
        same, changed = self.save(expected_revision=1)
        self.assertFalse(changed)
        self.assertEqual(same.revision, 1)
        with self.assertRaisesMessage(ValueError, "altă sesiune"):
            self.save(expected_revision=0)
        draft.refresh_from_db()
        self.assertEqual(draft.revision, 1)

    def test_source_drift_fails_closed_and_preserves_existing_draft(self):
        draft, _changed = self.save()
        self.base.state = ImportRun.State.FAILED
        self.base.save(update_fields=("state",))
        with self.assertRaisesMessage(ValueError, "nu pot fi determinate"):
            self.save(expected_revision=1)
        draft.refresh_from_db()
        self.assertEqual(draft.revision, 1)
        self.assertEqual(draft.services.get().category, "constructii")

    def test_revision_change_invalidates_review_state(self):
        draft, _changed = self.save()
        draft.review_state = ProviderServiceAreaDraft.ReviewState.APPROVED
        draft.reviewed_revision = 1
        draft.save(update_fields=("review_state", "reviewed_revision"))
        updated, changed = self.save(
            expected_revision=1,
            coverage_pairs=[("Iași", "95079"), ("Iași", "96076")],
        )
        self.assertTrue(changed)
        self.assertEqual(updated.review_state, ProviderServiceAreaDraft.ReviewState.DRAFT)
        self.assertIsNone(updated.reviewed_revision)


class ProviderOfferingModerationTests(ProviderOfferingFixtureMixin, TestCase):
    def setUp(self):
        self.create_fixture()
        self.permission = Permission.objects.get(
            codename="review_provider_service_area"
        )
        self.reviewer.user_permissions.add(self.permission)
        self.draft, _changed = replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )

    def submit(self):
        return submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )

    def decide(self, submission, **overrides):
        values = {
            "submission_id": submission.pk,
            "reviewer": self.reviewer,
            "decision": ProviderServiceAreaSubmission.Decision.APPROVED,
            "internal_note": "Revizie verificată față de sursele fixate.",
            "provider_feedback": "",
            "acknowledgement": REVIEW_ACKNOWLEDGEMENT,
        }
        values.update(overrides)
        return review_provider_service_area_submission(**values)

    def test_submit_creates_canonical_snapshot_and_is_idempotent(self):
        submission, created = self.submit()
        self.assertTrue(created)
        self.assertEqual(submission.services_snapshot, ["constructii"])
        self.assertEqual(submission.coverage_snapshot, [["Iași", "95079"]])
        self.assertEqual(len(submission.contract_sha256), 64)
        self.assertEqual(submission.authorization_run, self.base)
        self.assertEqual(submission.catalogue_run, self.current)
        self.draft.refresh_from_db()
        self.assertEqual(
            self.draft.review_state, ProviderServiceAreaDraft.ReviewState.PENDING
        )
        same, repeated = self.submit()
        self.assertFalse(repeated)
        self.assertEqual(same.pk, submission.pk)

    def test_submit_fails_closed_on_source_drift(self):
        self.base.state = ImportRun.State.FAILED
        self.base.save(update_fields=("state",))
        with self.assertRaisesMessage(ValueError, "nu pot fi determinate"):
            self.submit()
        self.assertFalse(ProviderServiceAreaSubmission.objects.exists())

    def test_approval_is_private_audited_and_idempotent(self):
        submission, _created = self.submit()
        decided, changed = self.decide(submission)
        self.assertTrue(changed)
        self.assertEqual(
            decided.decision, ProviderServiceAreaSubmission.Decision.APPROVED
        )
        self.assertEqual(decided.reviewed_by, self.reviewer)
        self.assertTrue(decided.review_policy_version)
        self.draft.refresh_from_db()
        self.assertEqual(
            self.draft.review_state, ProviderServiceAreaDraft.ReviewState.APPROVED
        )
        same, repeated = self.decide(submission)
        self.assertFalse(repeated)
        self.assertEqual(same.pk, submission.pk)

    def test_changes_required_separates_internal_note_from_provider_feedback(self):
        submission, _created = self.submit()
        decided, _changed = self.decide(
            submission,
            decision=ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
            internal_note="Acoperirea trebuie clarificată în auditul intern.",
            provider_feedback="Elimină localitatea în care firma nu se deplasează.",
        )
        self.assertEqual(
            decided.decision,
            ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
        )
        self.assertNotEqual(decided.internal_review_note, decided.provider_feedback)
        self.draft.refresh_from_db()
        self.assertEqual(
            self.draft.review_state,
            ProviderServiceAreaDraft.ReviewState.CHANGES_REQUIRED,
        )

    def test_real_edit_supersedes_history_but_noop_does_not(self):
        submission, _created = self.submit()
        self.decide(submission)
        _same, changed = replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=1,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        self.assertFalse(changed)
        submission.refresh_from_db()
        self.assertIsNone(submission.superseded_at)
        updated, changed = replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=1,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079"), ("Iași", "96076")],
        )
        self.assertTrue(changed)
        submission.refresh_from_db()
        self.assertEqual(
            submission.decision, ProviderServiceAreaSubmission.Decision.APPROVED
        )
        self.assertEqual(submission.superseded_by_revision, 2)
        self.assertEqual(submission.superseded_by, self.owner)
        self.assertEqual(updated.review_state, ProviderServiceAreaDraft.ReviewState.DRAFT)

    def test_permission_self_review_and_different_terminal_decision_fail(self):
        submission, _created = self.submit()
        self.reviewer.user_permissions.remove(self.permission)
        with self.assertRaises(PermissionError):
            self.decide(submission)
        self.reviewer.user_permissions.add(self.permission)
        self.reviewer = get_user_model().objects.get(pk=self.reviewer.pk)
        self.owner.is_staff = True
        self.owner.save(update_fields=("is_staff",))
        self.owner.user_permissions.add(self.permission)
        with self.assertRaisesMessage(ValueError, "propria declarație"):
            self.decide(submission, reviewer=self.owner)
        self.decide(submission)
        with self.assertRaisesMessage(ValueError, "deja o decizie"):
            self.decide(
                submission,
                decision=ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
                provider_feedback="Este necesară o modificare distinctă.",
            )

    def test_source_swap_blocks_approval_but_allows_changes_required(self):
        submission, _created = self.submit()
        CatalogueScope.objects.filter(provider="ONRC", county="Iași").update(
            current_run=None, visibility="off", activated_at=None
        )
        with self.assertRaisesMessage(ValueError, "Catalogul ONRC s-a actualizat"):
            self.decide(submission)
        decided, changed = self.decide(
            submission,
            decision=ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
            provider_feedback="Salvează din nou declarația după actualizarea sursei.",
        )
        self.assertTrue(changed)
        self.assertEqual(
            decided.decision,
            ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
        )


class ProviderOfferingViewTests(ProviderOfferingFixtureMixin, TestCase):
    def setUp(self):
        self.create_fixture()

    def test_dashboard_marks_unauthorized_services_disabled(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("services:provider_dashboard"))
        self.assertContains(response, "Servicii și localități declarate")
        self.assertContains(response, 'value="gradinarit" disabled', html=False)
        self.assertContains(response, "data-load-provider-localities", html=False)
        self.assertNotContains(response, 'formmethod="get"', html=False)
        self.assertNotContains(response, "CUI")

    def test_missing_authorization_allows_private_draft_but_blocks_submission(self):
        now = timezone.now()
        ProviderRegistrationRequest.objects.create(
            legal_name="Atelier Test SRL",
            cui="12345678",
            registration_number=self.business.registration_number,
            requested_category="gradinarit",
            registered_county="Iași",
            registered_office_siruta="95079",
            contact_name="Ana Test",
            role="administrator",
            email=self.owner.email,
            status=ProviderRegistrationRequest.Status.CONVERTED,
            token_digest="9" * 64,
            token_expires_at=now,
            email_verified_at=now,
            privacy_notice_version="1",
            consented_at=now,
            linked_business=self.business,
            converted_claim=self.profile.approved_claim,
            reviewed_at=now,
            reviewed_by=self.reviewer,
            review_note="Identitate verificată administrativ.",
            review_policy_version="1",
        )
        CatalogueScope.objects.all().delete()
        self.client.force_login(self.owner)

        page = self.client.get(reverse("services:provider_dashboard"))
        self.assertContains(page, "Autorizările firmei sunt încă în verificare")
        self.assertContains(page, 'id="id_coverage_county"', html=False)
        self.assertContains(page, 'id="id_coverage_locality"', html=False)
        self.assertNotContains(page, 'value="gradinarit" disabled', html=False)
        self.assertContains(page, 'value="gradinarit" checked', html=False)

        saved = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "save_offerings",
                "expected_revision": "0",
                "services": ["gradinarit"],
                "coverage_county": "Iași",
                "coverage_locality": "95079",
            },
        )
        self.assertRedirects(saved, reverse("services:provider_dashboard"))
        draft = ProviderServiceAreaDraft.objects.get(profile=self.profile)
        self.assertEqual(draft.revision, 1)
        self.assertIsNone(draft.authorization_run_id)
        self.assertEqual(
            list(draft.coverage.values_list("county", "siruta_code")),
            [("Iași", "95079")],
        )

        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProviderServiceAreaDraft.objects.filter(pk=draft.pk).update(
                review_state=ProviderServiceAreaDraft.ReviewState.APPROVED,
                reviewed_revision=1,
            )

        blocked = self.client.post(
            reverse("services:provider_dashboard"),
            {"action": "submit_offerings_review", "expected_revision": "1"},
        )
        self.assertContains(blocked, "Autorizările ONRC", status_code=200)
        self.assertEqual(ProviderServiceAreaSubmission.objects.count(), 0)

        CatalogueScope.objects.create(
            provider="ONRC",
            county="Iași",
            current_run=self.current,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
            activated_at=timezone.now(),
        )
        unauthorized = self.client.post(
            reverse("services:provider_dashboard"),
            {"action": "submit_offerings_review", "expected_revision": "1"},
        )
        self.assertContains(unauthorized, "autorizate ONRC", status_code=200)
        self.assertEqual(ProviderServiceAreaSubmission.objects.count(), 0)

        reconciled = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "save_offerings",
                "expected_revision": "1",
                "services": ["constructii"],
                "coverage_county": "",
                "coverage_locality": "",
            },
        )
        self.assertRedirects(reconciled, reverse("services:provider_dashboard"))
        draft.refresh_from_db()
        self.assertEqual(draft.revision, 2)
        self.assertEqual(draft.authorization_run, self.base)

        submitted = self.client.post(
            reverse("services:provider_dashboard"),
            {"action": "submit_offerings_review", "expected_revision": "2"},
        )
        self.assertRedirects(submitted, reverse("services:provider_dashboard"))
        self.assertEqual(ProviderServiceAreaSubmission.objects.count(), 1)

    def test_csrf_protected_post_saves_one_private_declaration(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        page = client.get(reverse("services:provider_dashboard"))
        token = page.cookies["csrftoken"].value
        response = client.post(
            reverse("services:provider_dashboard"),
            {
                "csrfmiddlewaretoken": token,
                "action": "save_offerings",
                "expected_revision": "0",
                "services": ["constructii"],
                "coverage_county": "Iași",
                "coverage_locality": "95079",
            },
        )
        self.assertRedirects(response, reverse("services:provider_dashboard"))
        self.assertEqual(ProviderServiceAreaDraft.objects.count(), 1)

    def test_stale_dashboard_post_returns_conflict(self):
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "save_offerings",
                "expected_revision": "0",
                "services": ["constructii"],
                "coverage_county": "Iași",
                "coverage_locality": "96076",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "altă sesiune", status_code=409)

    def test_revoked_membership_cannot_open_dashboard(self):
        self.membership.state = ProviderMembership.State.REVOKED
        self.membership.revoked_at = timezone.now()
        self.membership.save(update_fields=("state", "revoked_at"))
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("services:provider_dashboard")).status_code, 403
        )

    def test_provider_can_submit_and_sees_only_safe_review_feedback(self):
        draft, _changed = replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "submit_offerings_review",
                "expected_revision": str(draft.revision),
            },
        )
        self.assertRedirects(response, reverse("services:provider_dashboard"))
        submission = ProviderServiceAreaSubmission.objects.get()
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_service_area")
        )
        review_provider_service_area_submission(
            submission_id=submission.pk,
            reviewer=self.reviewer,
            decision=ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
            internal_note="Notă internă care nu trebuie afișată furnizorului.",
            provider_feedback="Selectează numai localitățile în care te deplasezi.",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        page = self.client.get(reverse("services:provider_dashboard"))
        self.assertContains(page, "Sunt necesare modificări")
        self.assertContains(page, "Selectează numai localitățile")
        self.assertNotContains(page, "Notă internă care")

    def test_admin_review_get_is_inert_and_post_requires_csrf(self):
        draft, _changed = replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        submission, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=draft.revision
        )
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_service_area")
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        url = reverse(
            "admin:services_providerserviceareasubmission_review",
            args=(submission.pk,),
        )
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(
            submission.decision, ProviderServiceAreaSubmission.Decision.PENDING
        )
        forbidden = client.post(
            url,
            {
                "decision": "approved",
                "internal_note": "Revizie verificată administrativ.",
                "provider_feedback": "",
                "acknowledgement": "on",
            },
        )
        self.assertEqual(forbidden.status_code, 403)
        token = page.cookies["csrftoken"].value
        decided = client.post(
            url,
            {
                "csrfmiddlewaretoken": token,
                "decision": "approved",
                "internal_note": "Revizie verificată administrativ.",
                "provider_feedback": "",
                "acknowledgement": "on",
            },
        )
        self.assertEqual(decided.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(
            submission.decision, ProviderServiceAreaSubmission.Decision.APPROVED
        )


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row locks")
class ProviderOfferingConcurrencyTests(
    ProviderOfferingFixtureMixin, TransactionTestCase
):
    reset_sequences = True

    def setUp(self):
        self.create_fixture()

    def test_two_writers_to_same_revision_produce_one_complete_winner(self):
        barrier = Barrier(2)
        outcomes = []

        def writer(code):
            close_old_connections()
            user = get_user_model().objects.get(pk=self.owner.pk)
            barrier.wait()
            try:
                draft, changed = replace_provider_services_and_coverage_for_owner(
                    user=user,
                    expected_revision=0,
                    categories=["constructii"],
                    coverage_pairs=[("Iași", code)],
                )
            except ValueError:
                outcomes.append("stale")
            else:
                outcomes.append((draft.revision, changed))
            finally:
                connection.close()

        threads = [Thread(target=writer, args=(code,)) for code in ("95079", "96076")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len([value for value in outcomes if value == "stale"]), 1)
        self.assertEqual(ProviderServiceAreaDraft.objects.get().revision, 1)
        self.assertEqual(ProviderDraftCoverage.objects.count(), 1)

    def test_two_submissions_create_one_current_snapshot(self):
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        barrier = Barrier(2)
        outcomes = []

        def submitter():
            close_old_connections()
            user = get_user_model().objects.get(pk=self.owner.pk)
            barrier.wait()
            try:
                _submission, created = submit_provider_service_area_for_review(
                    user=user, expected_revision=1
                )
            except Exception as error:
                outcomes.append(type(error).__name__)
            else:
                outcomes.append(created)
            finally:
                connection.close()

        threads = [Thread(target=submitter) for _index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, [False, True])
        self.assertEqual(ProviderServiceAreaSubmission.objects.count(), 1)

    def test_two_reviewers_produce_one_terminal_decision(self):
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        submission, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )
        permission = Permission.objects.get(codename="review_provider_service_area")
        second = get_user_model().objects.create_user(
            username="reviewer-second", is_staff=True
        )
        self.reviewer.user_permissions.add(permission)
        second.user_permissions.add(permission)
        barrier = Barrier(2)
        outcomes = []

        def reviewer_task(user_id):
            close_old_connections()
            reviewer = get_user_model().objects.get(pk=user_id)
            barrier.wait()
            try:
                _result, changed = review_provider_service_area_submission(
                    submission_id=submission.pk,
                    reviewer=reviewer,
                    decision=ProviderServiceAreaSubmission.Decision.APPROVED,
                    internal_note="Revizie verificată față de sursele fixate.",
                    provider_feedback="",
                    acknowledgement=REVIEW_ACKNOWLEDGEMENT,
                )
            except ValueError:
                outcomes.append("conflict")
            else:
                outcomes.append(changed)
            finally:
                connection.close()

        threads = [
            Thread(target=reviewer_task, args=(reviewer.pk,))
            for reviewer in (self.reviewer, second)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len([value for value in outcomes if value is True]), 1)
        self.assertEqual(len([value for value in outcomes if value == "conflict"]), 1)
        submission.refresh_from_db()
        self.assertEqual(
            submission.decision, ProviderServiceAreaSubmission.Decision.APPROVED
        )
