"""Contracts for the precise electrician discovery specialty."""

from datetime import date

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    BusinessCategory,
    BusinessIdentity,
    CatalogueScope,
    ImportRun,
    PrimaryActivityEvidence,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from .registry_catalogue import catalogue_categories, registry_search


@override_settings(DEBUG=True)
class ElectricianDiscoveryTests(TestCase):
    """Keep electrical results exact without broadening every installation firm."""

    def setUp(self):
        onrc = SourceSnapshot.objects.create(
            provider="ONRC",
            snapshot_date=date(2026, 7, 8),
            manifest_sha256="a" * 64,
            dataset_url="https://data.gov.ro/onrc",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        mf = SourceSnapshot.objects.create(
            provider="MF_FINANCIAL_STATEMENTS_2024",
            snapshot_date=date(2024, 12, 31),
            manifest_sha256="b" * 64,
            dataset_url="https://data.gov.ro/mf",
            license_label="CC BY 4.0",
            verified_resources={},
        )
        base = ImportRun.objects.create(
            snapshot=onrc,
            scope_key="c" * 64,
            county="Iași",
            categories=["instalatii"],
            caen_mapping_version="2",
            caen_mapping_hash="d" * 64,
            status_policy_version="1",
            state=ImportRun.State.SUCCEEDED,
        )
        self.run = ImportRun.objects.create(
            snapshot=onrc,
            scope_key="e" * 64,
            county="Iași",
            categories=["instalatii"],
            caen_mapping_version="2",
            caen_mapping_hash="d" * 64,
            status_policy_version="1",
            scope_contract_version=2,
            refined_from_run=base,
            activity_evidence_snapshot=mf,
            activity_evidence_policy_version="1",
            activity_evidence_policy_hash="f" * 64,
            activity_evidence_year=2024,
            state=ImportRun.State.SUCCEEDED,
        )
        self._create_company("Electric Exact SRL", "4321")
        self._create_company("Instalator Termic SRL", "4322")
        CatalogueScope.objects.create(
            provider="ONRC",
            county="Iași",
            current_run=self.run,
            visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW,
        )

    def _create_company(self, name, caen):
        """Create one retained installation record with exact MF evidence."""

        identity = BusinessIdentity.objects.create(
            registration_number=f"J22/{caen}/2020"
        )
        record = RegisteredBusinessSnapshot.objects.create(
            import_run=self.run,
            business=identity,
            legal_name=name,
            registered_office_siruta="95079",
            locality_match="exact",
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint=caen * 8,
        )
        BusinessCategory.objects.create(
            business_snapshot=record, category="instalatii"
        )
        PrimaryActivityEvidence.objects.create(
            business_snapshot=record,
            resource_kind="data_bl_bs_sl",
            cui_join_fingerprint="1" * 64,
            caen_version="2",
            caen_code=caen,
            reporting_year=2024,
            source_row_fingerprint="2" * 64,
        )

    def search(self, category):
        """Search the same locality through the public registry projection."""

        return registry_search(
            run=self.run,
            county="Iași",
            allow_direct_evidence=False,
            siruta_code="95079",
            locality_label="Iași",
            category=category,
            page_number="1",
        )

    def test_electrician_filter_uses_only_exact_4321_evidence(self):
        result = self.search("electricieni")

        self.assertEqual(result.total, 1)
        self.assertEqual(result.page.object_list[0].legal_name, "Electric Exact SRL")
        self.assertEqual(result.page.object_list[0].category_labels, ("Electricitate",))

    def test_installations_filter_excludes_electrical_only_rows(self):
        installation_results = self.search("instalatii")
        self.assertEqual(installation_results.total, 1)
        self.assertEqual(installation_results.page.object_list[0].legal_name, "Instalator Termic SRL")
        self.assertEqual(installation_results.page.object_list[0].category_labels, ("Instalații",))
        self.assertIn("electricieni", catalogue_categories(self.run))

    def test_electrician_cannot_open_in_installations_scope(self):
        listing = self.search("electricieni").page.object_list[0]
        response = self.client.get(
            reverse("services:company_detail", args=(listing.business_id,)),
            {"county": "Iași", "locality": "95079", "category": "instalatii"},
        )
        self.assertEqual(response.status_code, 404)

    def test_electrician_result_opens_in_the_same_derived_search_scope(self):
        """The detail reader must accept every specialty exposed by search."""

        listing = self.search("electricieni").page.object_list[0]
        response = self.client.get(
            reverse("services:company_detail", args=(listing.business_id,)),
            {"county": "Iași", "locality": "95079", "category": "electricieni"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Electric Exact SRL")
        self.assertContains(response, "Electricitate")
        self.assertEqual(response.context["art_category"], "electricieni")
        self.assertContains(response, "category-photos/electricieni.webp")
