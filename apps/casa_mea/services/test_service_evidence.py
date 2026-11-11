"""Contracts for reviewed direct-service evidence and catalogue overlay."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .caen import CAEN_MAPPING_HASH, CAEN_MAPPING_VERSION
from .importers.locality_aliases import RULES_PATH, sha256_file
from .importers.onrc_statuses import POLICY_VERSION as STATUS_POLICY_VERSION
from .importers.primary_activity import POLICY_HASH, POLICY_VERSION
from .models import (
    BusinessCaen,
    BusinessCategory,
    BusinessIdentity,
    BusinessStatus,
    CatalogueScope,
    ImportRun,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
    VerifiedServiceEvidence,
)
from .registry_catalogue import registry_search
from .service_evidence import (
    EVIDENCE_ACKNOWLEDGEMENT,
    record_verified_service_evidence,
    revoke_verified_service_evidence,
    valid_service_evidence,
)
from .staging import LOCALITY_POLICY, pilot_scope_key, refined_scope_key


class VerifiedServiceEvidenceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="service-reviewer", password=None, is_staff=True
        )
        self.actor.user_permissions.add(
            Permission.objects.get(codename="verify_service_evidence")
        )
        self.onrc = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date="2026-07-08",
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/onrc",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        self.mf = SourceSnapshot.objects.create(
            provider="MF_FINANCIAL_STATEMENTS_2024",
            snapshot_date="2024-12-31",
            manifest_sha256="b" * 64,
            dataset_url="https://data.gov.ro/mf",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        key, categories = pilot_scope_key("Neamț", [
            "constructii", "instalatii", "gradinarit", "curatenie",
            "tamplarie", "reparatii",
        ])
        self.base = ImportRun.objects.create(
            snapshot=self.onrc,
            scope_key=key,
            county="Neamț",
            categories=categories,
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=STATUS_POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
            state=ImportRun.State.SUCCEEDED,
        )
        refined_key, _categories = refined_scope_key(
            self.base,
            self.mf,
            policy_version=POLICY_VERSION,
            policy_hash=POLICY_HASH,
            evidence_year=2024,
        )
        self.refined = ImportRun.objects.create(
            snapshot=self.onrc,
            scope_key=refined_key,
            county="Neamț",
            categories=categories,
            caen_mapping_version=CAEN_MAPPING_VERSION,
            caen_mapping_hash=CAEN_MAPPING_HASH,
            status_policy_version=STATUS_POLICY_VERSION,
            locality_policy=LOCALITY_POLICY,
            locality_rules_hash=sha256_file(RULES_PATH),
            scope_contract_version=2,
            refined_from_run=self.base,
            activity_evidence_snapshot=self.mf,
            activity_evidence_policy_version=POLICY_VERSION,
            activity_evidence_policy_hash=POLICY_HASH,
            activity_evidence_year=2024,
            state=ImportRun.State.SUCCEEDED,
        )
        self.identity = BusinessIdentity.objects.create(
            registration_number="J27/600/2021"
        )
        self.base_record = RegisteredBusinessSnapshot.objects.create(
            import_run=self.base,
            business=self.identity,
            legal_name="NACELA ROBU S.R.L.",
            cui="44271540",
            registered_office_siruta="124215",
            locality_match="hierarchy_alias",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="a" * 32,
        )
        BusinessStatus.objects.create(business_snapshot=self.base_record, code="1048")
        BusinessCaen.objects.create(
            business_snapshot=self.base_record, version="2", code="8130"
        )
        BusinessCategory.objects.create(
            business_snapshot=self.base_record, category="gradinarit"
        )

    def record(self, **overrides):
        arguments = {
            "business": self.identity,
            "category": "gradinarit",
            "source_url": "https://nacelarobu.ro/servicii/",
            "source_title": "Servicii — Nacela Robu",
            "identity_reference": "Nacela Robu S.R.L. · CUI 44271540 · J27/600/2021",
            "evidence_summary": "Site-ul firmei declară toaletări și defrișări arbori.",
            "coverage_counties": ["Neamț"],
            "retrieved_at": timezone.now() - timedelta(minutes=1),
            "content_sha256": "c" * 64,
            "expires_at": timezone.now() + timedelta(days=180),
            "actor_username": self.actor.username,
            "acknowledgement": EVIDENCE_ACKNOWLEDGEMENT,
        }
        arguments.update(overrides)
        return record_verified_service_evidence(**arguments)

    def search(self, **overrides):
        arguments = {
            "run": self.refined,
            "county": "Neamț",
            "allow_direct_evidence": True,
            "siruta_code": "124215",
            "locality_label": "Săbăoani",
            "category": "gradinarit",
            "page_number": "1",
        }
        arguments.update(overrides)
        return registry_search(**arguments)

    def test_record_supersede_revoke_and_expiry_are_immediate(self):
        first = self.record()
        self.assertEqual(valid_service_evidence(
            county="Neamț", categories={"gradinarit"}
        ), [first])
        second = self.record(content_sha256="d" * 64)
        first.refresh_from_db()
        self.assertEqual(first.state, VerifiedServiceEvidence.State.SUPERSEDED)
        self.assertEqual(self.search().total, 1)
        _evidence, changed = revoke_verified_service_evidence(
            evidence=second, actor_username=self.actor.username
        )
        self.assertTrue(changed)
        self.assertEqual(self.search().total, 0)

        expired = self.record(expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(valid_service_evidence(
            county="Neamț",
            categories={"gradinarit"},
            instant=expired.expires_at,
        ), [])

    def test_overlay_requires_exact_county_locality_category_and_preview(self):
        self.record()
        result = self.search()
        self.assertEqual(result.total, 1)
        listing = result.page.object_list[0]
        self.assertEqual(listing.legal_name, "NACELA ROBU S.R.L.")
        self.assertEqual(listing.evidence_kind, "direct_service")
        self.assertEqual(listing.category_labels, ("Grădină & exterior",))
        self.assertEqual(self.search(county="Iași").total, 0)
        self.assertEqual(self.search(siruta_code="120735").total, 0)
        self.assertEqual(self.search(category="constructii").total, 0)
        self.assertEqual(self.search(category="").total, 1)
        self.assertEqual(self.search(allow_direct_evidence=False).total, 0)

    def test_primary_and_direct_evidence_deduplicate_to_one_listing(self):
        self.record()
        refined_record = RegisteredBusinessSnapshot.objects.create(
            import_run=self.refined,
            business=self.identity,
            legal_name="NACELA ROBU S.R.L.",
            cui="44271540",
            registered_office_siruta="124215",
            locality_match="hierarchy_alias",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint="b" * 32,
        )
        BusinessCategory.objects.create(
            business_snapshot=refined_record, category="gradinarit"
        )
        result = self.search()
        self.assertEqual(result.total, 1)
        self.assertEqual(len(result.page.object_list), 1)
        self.assertTrue(result.page.object_list[0].evidence_source_url)

    def test_record_fails_closed_on_permission_identity_authorization_and_input(self):
        unprivileged = get_user_model().objects.create_user(
            username="unprivileged", password=None
        )
        with self.assertRaisesRegex(ValueError, "permisiunea"):
            self.record(actor_username=unprivileged.username)
        with self.assertRaisesRegex(ValueError, "identifică"):
            self.record(identity_reference="Altă firmă")
        with self.assertRaises(ValidationError):
            self.record(source_url="http://nacelarobu.ro/servicii/")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.record(content_sha256="invalid")
        with self.assertRaisesRegex(ValueError, "Acoperirea"):
            self.record(coverage_counties=[])
        with self.assertRaisesRegex(ValueError, "autorizare ONRC"):
            self.record(category="constructii")

    @override_settings(DEBUG=True)
    def test_template_discloses_direct_source_without_private_fields(self):
        self.record()
        CatalogueScope.objects.create(
            provider="ONRC",
            county="Neamț",
            current_run=self.refined,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
        )
        response = self.client.get(reverse("services:home"), {
            "county": "Neamț", "locality": "124215", "category": "gradinarit",
        })
        self.assertContains(response, "NACELA ROBU S.R.L.")
        self.assertContains(response, "Serviciu confirmat din sursă directă")
        self.assertContains(response, "https://nacelarobu.ro/servicii/")
        self.assertNotContains(response, "44271540")
        self.assertNotContains(response, "J27/600/2021")
        self.assertNotContains(response, self.actor.username)

    @override_settings(DEBUG=True)
    def test_company_detail_rechecks_direct_evidence_and_hides_private_fields(self):
        evidence = self.record()
        CatalogueScope.objects.create(
            provider="ONRC",
            county="Neamț",
            current_run=self.refined,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
        )
        url = reverse("services:company_detail", args=(self.identity.pk,))
        query = {
            "county": "Neamț", "locality": "124215", "category": "gradinarit",
        }
        response = self.client.get(url, query)

        self.assertContains(response, "NACELA ROBU S.R.L.")
        self.assertContains(response, "Dovadă publică directă")
        self.assertContains(response, evidence.evidence_summary)
        self.assertContains(response, "Arie declarată de sursă")
        self.assertNotContains(response, "44271540")
        self.assertNotContains(response, "J27/600/2021")
        self.assertNotContains(response, self.actor.username)

        revoke_verified_service_evidence(
            evidence=evidence, actor_username=self.actor.username
        )
        self.assertEqual(self.client.get(url, query).status_code, 404)
