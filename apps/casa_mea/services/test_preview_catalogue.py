"""Parity and isolation contracts for the portable development catalogue."""

from dataclasses import asdict
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import translation

from deploy.export_preview import export_catalogue_snapshot
from . import preview_catalogue
from .catalog import CATEGORIES
from .models import (
    BusinessCategory,
    CatalogueScope,
    RegisteredBusinessSnapshot,
    ServiceCategoryPolicy,
)
from .registry_catalogue import registry_search
from . import test_service_evidence


class BundledInstallationsScopeTests(SimpleTestCase):
    """Keep older immutable snapshots aligned with today's service labels."""

    @override_settings(
        PREVIEW_CATALOGUE_PATH=Path(__file__).resolve().parents[1] / 'deploy/preview/catalogue.snapshot',
        PREVIEW_REQUIRE_COMPLETE=True,
    )
    def test_installations_excludes_electrical_rows_in_existing_snapshot(self):
        query = dict(county='Iași', siruta_code='95079', category='instalatii')
        page = preview_catalogue.registry_search(**query, page_number='1')
        self.assertGreater(page.total, 0)
        self.assertTrue(all('instalatii' in row.category_slugs for row in page.page.object_list))

        with sqlite3.connect(Path(__file__).resolve().parents[1] / 'deploy/preview/catalogue.snapshot') as db:
            electrical_row = db.execute(
                "SELECT business_id FROM listings WHERE county = ? AND siruta = ? "
                "AND category = ? AND NOT EXISTS "
                "(SELECT 1 FROM json_each(listings.payload, '$.category_slugs') "
                "WHERE value = 'instalatii') LIMIT 1",
                ('Iași', '95079', 'instalatii'),
            ).fetchone()
        if electrical_row:
            self.assertIsNone(preview_catalogue.registry_company_detail(
                **query, business_id=electrical_row[0],
            ))


@override_settings(DEBUG=True)
class PreviewCatalogueTests(TransactionTestCase):
    """Use actual source projection gates against an independent SQLite artifact."""

    def setUp(self):
        """Create direct-only and MF+direct variants containing private canaries."""
        # TransactionTestCase flushes data-migration rows between methods.
        ServiceCategoryPolicy.objects.bulk_create(
            [
                ServiceCategoryPolicy(category=slug, display_order=index * 10)
                for index, (slug, _label, _description) in enumerate(
                    CATEGORIES, start=1
                )
            ],
            ignore_conflicts=True,
        )
        self.addCleanup(translation.activate, translation.get_language())
        test_service_evidence.VerifiedServiceEvidenceTests.setUp(self)
        self.evidence = test_service_evidence.VerifiedServiceEvidenceTests.record(self)
        primary = RegisteredBusinessSnapshot.objects.create(
            import_run=self.refined, business=self.identity, legal_name='NACELA ROBU S.R.L.',
            cui='PRIVATE-CUI', registered_office_siruta='124215', locality_match='hierarchy_alias',
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            source_fingerprint='b' * 32,
        )
        BusinessCategory.objects.create(business_snapshot=primary, category='constructii')
        CatalogueScope.objects.create(provider='ONRC', county='Neamț', current_run=self.refined,
                                      visibility=CatalogueScope.Visibility.INTERNAL_PREVIEW)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'preview'
        self.manifest = export_catalogue_snapshot(self.output, counties=['Neamț'], audit=False)
        self.settings_override = override_settings(PREVIEW_CATALOGUE_PATH=self.output / 'catalogue.snapshot',
                                                  PREVIEW_REQUIRE_COMPLETE=False)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(preview_catalogue.read_snapshot_metadata.cache_clear)

    def test_exact_category_projection_and_order_parity(self):
        for language in ('ro', 'en'):
            with translation.override(language):
                for category in ('', 'gradinarit', 'constructii', 'instalatii'):
                    with self.subTest(language=language, category=category):
                        query = dict(county='Neamț', siruta_code='124215', category=category,
                                     page_number='1', run=self.refined, allow_direct_evidence=True,
                                     locality_label='Săbăoani')
                        live = registry_search(**query)
                        frozen = preview_catalogue.registry_search(**query)
                        self.assertEqual(live.total, frozen.total)
                        self.assertEqual(live.contains_direct_service_evidence, frozen.contains_direct_service_evidence)
                        self.assertEqual([asdict(item) for item in live.page.object_list],
                                         [asdict(item) for item in frozen.page.object_list])

    def test_county_wide_search_and_detail_work_without_a_locality_filter(self):
        query = dict(
            county='Neamț', siruta_code=None, category='constructii',
            page_number='1', run=self.refined, allow_direct_evidence=True,
            locality_label='',
        )
        live = registry_search(**query)
        frozen = preview_catalogue.registry_search(**query)

        self.assertEqual(live.total, 1)
        self.assertEqual([asdict(item) for item in live.page.object_list],
                         [asdict(item) for item in frozen.page.object_list])
        self.assertEqual(frozen.page.object_list[0].registered_office_label, 'Săbăoani')
        self.assertIsNotNone(preview_catalogue.registry_company_detail(
            county='Neamț', siruta_code=None, category='constructii',
            business_id=self.identity.pk,
        ))

    def test_snapshot_retains_historical_evidence_after_source_changes(self):
        self.evidence.delete()
        page = preview_catalogue.registry_search(county='Neamț', siruta_code='124215',
                                                category='gradinarit', page_number='1')
        self.assertEqual(page.total, 1)
        self.assertEqual(page.page.object_list[0].evidence_kind, 'direct_service')

    def test_snapshot_whitelist_excludes_private_source_fields(self):
        content = (self.output / 'catalogue.snapshot').read_bytes()
        for value in (b'PRIVATE-CUI', b'44271540', b'J27/600/2021', b'service-reviewer',
                      b'identity_reference', b'password', b'source_fingerprint'):
            self.assertNotIn(value, content)
        with sqlite3.connect(self.output / 'catalogue.snapshot') as db:
            self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                             {'listings', 'metadata'})

    def test_detail_requires_matching_context(self):
        query = dict(county='Neamț', siruta_code='124215', category='gradinarit', business_id=self.identity.pk)
        self.assertIsNotNone(preview_catalogue.registry_company_detail(**query))
        for changed in ({'siruta_code': '120735'}, {'category': 'tamplarie'}, {'business_id': 999999}):
            self.assertIsNone(preview_catalogue.registry_company_detail(**(query | changed)))
        self.assertEqual(preview_catalogue.catalogue_state('Iași').status, 'unavailable')

    def test_invalid_page_numbers_use_existing_paginator_contract(self):
        for number in ('abc', '-1', '999999'):
            result = preview_catalogue.registry_search(county='Neamț', siruta_code='124215',
                                                      category='', page_number=number)
            self.assertEqual(result.page.number, 1)
            self.assertEqual(result.total, 1)

    def test_missing_and_corrupt_artifacts_fail_closed(self):
        with self.assertRaises(ImproperlyConfigured):
            preview_catalogue.read_snapshot_metadata(str(self.output / 'missing.snapshot'))
        with (self.output / 'catalogue.snapshot').open('ab') as stream:
            stream.write(b'corruption')
        with self.assertRaises(ImproperlyConfigured):
            preview_catalogue.snapshot_metadata()

    def test_export_refuses_existing_destination_and_provider_publications(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            export_catalogue_snapshot(self.output, counties=['Neamț'], audit=False)
        with patch('services.models.ProviderPublicationScope.objects.exclude') as scopes:
            scopes.return_value.exists.return_value = True
            with self.assertRaisesRegex(ValueError, 'Provider publications exist'):
                export_catalogue_snapshot(Path(self.temp.name) / 'another', counties=['Neamț'], audit=False)
        self.assertFalse((Path(self.temp.name) / 'another').exists())

    def test_locality_pin_mismatch_is_rejected(self):
        with patch('services.preview_catalogue.siruta_catalogue_sha256', return_value='wrong'):
            with self.assertRaises(ImproperlyConfigured):
                preview_catalogue.snapshot_metadata()

    def test_national_runtime_rejects_valid_partial_snapshot(self):
        with override_settings(PREVIEW_REQUIRE_COMPLETE=True):
            with self.assertRaises(ImproperlyConfigured):
                preview_catalogue.snapshot_metadata()

    def test_reader_never_accesses_orm(self):
        with self.assertNumQueries(0):
            preview_catalogue.catalogue_state('Neamț')
            preview_catalogue.registry_search(county='Neamț', siruta_code='124215', category='', page_number='1')

    def test_preview_routes_hide_workflows_and_reject_writes(self):
        from config import preview
        with override_settings(READ_ONLY_PREVIEW=True, DEBUG=False, ROOT_URLCONF='config.preview_urls',
                               MIDDLEWARE=preview.MIDDLEWARE, TEMPLATES=preview.TEMPLATES):
            query = {'county': 'Neamț', 'locality': '124215', 'category': 'gradinarit'}
            for prefix in ('', '/en'):
                with self.assertNumQueries(0):
                    response = self.client.get(f'{prefix}/', query)
                self.assertContains(response, 'NACELA ROBU S.R.L.')
                self.assertNotContains(response, 'class="snapshot-notice"')
                self.assertNotContains(response, '/cont/')
                self.assertNotContains(response, 'pentru-profesionisti')
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow, noarchive')
                detail = self.client.get(f'{prefix}/firme/{self.identity.pk}/', query)
                self.assertEqual(detail.status_code, 200)
                self.assertContains(detail, 'class="snapshot-notice"')
                self.assertNotContains(detail, '/revendica/')
                for path in ('admin/', 'cont/profil/', 'pentru-profesionisti/', f'firme/{self.identity.pk}/revendica/'):
                    self.assertEqual(self.client.get(f'{prefix}/{path}').status_code, 404)
                self.assertEqual(self.client.post(f'{prefix}/', query).status_code, 405)
                self.assertEqual(self.client.get(f'{prefix}/api/localitati/', {'county': 'Neamț'}).status_code, 200)

    def test_managed_cloud_catalogue_keeps_provider_and_claim_workflows(self):
        """The packaged reader must not turn the persistent product read-only."""

        with override_settings(
            PACKAGED_CATALOGUE=True,
            READ_ONLY_PREVIEW=False,
            DEBUG=True,
            ROOT_URLCONF="config.urls",
        ):
            query = {
                "county": "Neamț",
                "locality": "124215",
                "category": "gradinarit",
            }
            home = self.client.get("/", query)
            self.assertEqual(home.status_code, 200)
            self.assertContains(home, "/pentru-profesionisti/")
            detail = self.client.get(f"/firme/{self.identity.pk}/", query)
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, f"/firme/{self.identity.pk}/revendica/")
            self.assertContains(detail, "Revendică firma")
            claim = self.client.get(f"/firme/{self.identity.pk}/revendica/", query)
            self.assertEqual(claim.status_code, 200)
            self.assertContains(claim, "Revendică profilul")
