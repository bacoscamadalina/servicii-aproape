"""Controlled provider publication, private media, and reader contract tests."""

from io import BytesIO, StringIO
from datetime import timedelta
import json
import re
import shutil
import tempfile
from threading import Barrier, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import (
    PublicProviderReport,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
    ProviderPortfolioAsset,
    ProviderEngagementEvent,
    ProviderProfile,
    ProviderPublicationEvent,
    ProviderPublicationScope,
    ProviderPublicationSubmission,
    ProviderServiceAreaSubmission,
    ProviderSubscription,
    ProviderSubscriptionEvent,
)
from .provider_offerings import (
    REVIEW_ACKNOWLEDGEMENT as OFFERING_ACKNOWLEDGEMENT,
    replace_provider_services_and_coverage_for_owner,
    review_provider_service_area_submission,
    submit_provider_service_area_for_review,
)
from .provider_publication import (
    REVIEW_ACKNOWLEDGEMENT,
    add_portfolio_image_for_owner,
    add_portfolio_images_for_owner,
    published_provider_search,
    review_provider_publication,
    save_provider_profile_for_owner,
    submit_provider_publication_for_review,
    unpublish_provider_profile,
)
from .provider_reports import create_public_provider_report
from .provider_subscriptions import (
    SUBSCRIPTION_ACKNOWLEDGEMENT,
    activate_or_extend_provider_subscription,
    deactivate_provider_subscription,
)
from .report_triage import (
    TRIAGE_ACKNOWLEDGEMENT,
    TRIAGE_POLICY_VERSION,
    close_public_provider_report_case,
    start_public_provider_report_review,
)
from .report_insights import public_report_insights
from .report_integrity import audit_public_provider_report_triage
from .test_provider_offerings import ProviderOfferingFixtureMixin


@override_settings(DEBUG=True)
class ProviderPublicationTests(ProviderOfferingFixtureMixin, TestCase):
    """Exercise the exact snapshot from owner draft through controlled preview."""

    def setUp(self):
        self.private_media = tempfile.mkdtemp(prefix="servicii-aproape-media-")
        self.settings_override = override_settings(MEDIA_ROOT=self.private_media)
        self.settings_override.enable()
        self.create_fixture()
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_service_area"),
            Permission.objects.get(codename="review_provider_publication"),
            Permission.objects.get(codename="publish_provider_profile"),
            Permission.objects.get(codename="triage_public_provider_report"),
            Permission.objects.get(codename="view_publicproviderreport"),
            Permission.objects.get(codename="view_public_provider_report_insights"),
            Permission.objects.get(codename="manage_provider_subscription"),
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.private_media, ignore_errors=True)

    @staticmethod
    def image_upload(name="lucrare.jpg"):
        rendered = BytesIO()
        Image.new("RGB", (640, 480), "#d59b47").save(rendered, format="JPEG")
        return SimpleUploadedFile(name, rendered.getvalue(), content_type="image/jpeg")

    def prepare_approved_offerings(self):
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        submission, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )
        review_provider_service_area_submission(
            submission_id=submission.pk,
            reviewer=self.reviewer,
            decision=ProviderServiceAreaSubmission.Decision.APPROVED,
            internal_note="Serviciile și acoperirea au fost verificate.",
            provider_feedback="",
            acknowledgement=OFFERING_ACKNOWLEDGEMENT,
        )
        return submission

    def prepare_publication(self):
        self.prepare_approved_offerings()
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Test Aproape",
                "description": (
                    "Executăm lucrări de construcții pentru locuințe, cu evaluare "
                    "prealabilă, ofertă clară și acoperire declarată în municipiul Iași."
                ),
                "public_address": "Strada Atelierului 12, Iași",
                "public_phone": "0712 345 678",
                "public_email": "contact@atelier.example",
                "website": "https://atelier.example",
                "availability": ProviderProfile.Availability.ACCEPTING,
                "contact_preference": ProviderProfile.ContactPreference.PHONE,
            },
        )
        item = add_portfolio_image_for_owner(
            user=self.owner,
            upload=self.image_upload(),
            caption="Renovare interioară finalizată",
        )
        submission, created = submit_provider_publication_for_review(user=self.owner)
        self.assertTrue(created)
        return submission, item.asset

    def decide(self, submission, visibility=ProviderPublicationScope.Visibility.INTERNAL_PREVIEW):
        state = ProviderSubscription.objects.filter(profile=self.profile).first()
        if state is None or state.status != ProviderSubscription.Status.ACTIVE:
            activate_or_extend_provider_subscription(
                profile_id=self.profile.pk,
                actor=self.reviewer,
                expected_revision=state.revision if state else 0,
                internal_note="Activare de test pentru verificarea publicării.",
                acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
            )
        return review_provider_publication(
            submission_id=submission.pk,
            reviewer=self.reviewer,
            decision=ProviderPublicationSubmission.Decision.APPROVED,
            visibility=visibility,
            internal_note="Identitatea, conținutul și portofoliul au fost verificate.",
            provider_feedback="",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )

    def prepare_report_case(self, *, details="Datele publice necesită verificare factuală."):
        """Create a visible immutable snapshot and its stable report case."""

        submission, _asset = self.prepare_publication()
        self.decide(submission)
        report, created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.INCORRECT_INFORMATION,
            details=details,
            session_key="triage-test-session",
        )
        self.assertTrue(created)
        return report, report.triage_case

    def test_approval_requires_an_active_subscription(self):
        """Content approval cannot activate professional data without entitlement."""

        submission, _asset = self.prepare_publication()
        with self.assertRaisesMessage(ValueError, "abonament activ"):
            review_provider_publication(
                submission_id=submission.pk,
                reviewer=self.reviewer,
                decision=ProviderPublicationSubmission.Decision.APPROVED,
                visibility=ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
                internal_note="Snapshotul complet a fost verificat administrativ.",
                provider_feedback="",
                acknowledgement=REVIEW_ACKNOWLEDGEMENT,
            )
        submission.refresh_from_db()
        self.assertEqual(submission.decision, ProviderPublicationSubmission.Decision.PENDING)

    def test_expiry_hides_and_reactivation_restores_the_approved_snapshot(self):
        """Entitlement changes visibility without rewriting the reviewed snapshot."""

        submission, _asset = self.prepare_publication()
        self.decide(submission)
        self.assertEqual(
            len(
                published_provider_search(
                    county="Iași", siruta_code="95079", category="constructii"
                )
            ),
            1,
        )

        subscription = ProviderSubscription.objects.get(profile=self.profile)
        subscription.period_started_at = timezone.now() - timedelta(days=30, minutes=1)
        subscription.period_ends_at = timezone.now() - timedelta(minutes=1)
        subscription.save(
            update_fields=("period_started_at", "period_ends_at", "updated_at")
        )
        self.assertEqual(
            published_provider_search(
                county="Iași", siruta_code="95079", category="constructii"
            ),
            (),
        )
        self.client.force_login(self.owner)
        expired = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(expired.context["publication_checklist"][3]["status"], "action")
        self.assertEqual(
            expired.context["publication_checklist"][4]["status"],
            "subscription_inactive",
        )

        activate_or_extend_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=subscription.revision,
            internal_note="Reactivare de test după expirarea perioadei.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )
        self.assertEqual(
            len(
                published_provider_search(
                    county="Iași", siruta_code="95079", category="constructii"
                )
            ),
            1,
        )
        self.assertEqual(
            list(ProviderSubscriptionEvent.objects.values_list("action", flat=True)),
            ["activate", "activate"],
        )

    def test_manual_deactivation_hides_professional_data(self):
        """A staff revocation immediately closes every public reader."""

        submission, _asset = self.prepare_publication()
        self.decide(submission)
        subscription = ProviderSubscription.objects.get(profile=self.profile)
        deactivate_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=subscription.revision,
            internal_note="Dezactivare manuală pentru control administrativ.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )
        self.assertEqual(
            published_provider_search(
                county="Iași", siruta_code="95079", category="constructii"
            ),
            (),
        )
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, ProviderSubscription.Status.INACTIVE)
        self.assertIsNone(subscription.period_ends_at)

    def test_dashboard_checklist_tracks_real_publication_prerequisites(self):
        """Guide the owner from missing content to review and visible publication."""

        self.client.force_login(self.owner)
        initial = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(initial.context["publication_checklist_complete"], 0)
        self.assertContains(initial, "Drumul spre un profil vizibil")
        self.assertContains(initial, 'href="#date-profil"')
        self.assertContains(initial, 'href="#servicii"')
        self.assertContains(initial, 'href="#portofoliu"')
        self.assertContains(initial, 'href="#publicare"')
        self.assertEqual(
            [step["status"] for step in initial.context["publication_checklist"]],
            ["action", "action", "action", "action", "blocked"],
        )

        self.prepare_approved_offerings()
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Test Aproape",
                "description": (
                    "Executăm lucrări de construcții pentru locuințe, cu evaluare "
                    "prealabilă, ofertă clară și acoperire declarată în municipiul Iași."
                ),
                "public_phone": "0712 345 678",
                "public_email": "",
                "website": "",
                "availability": ProviderProfile.Availability.ACCEPTING,
                "contact_preference": ProviderProfile.ContactPreference.PHONE,
            },
        )
        add_portfolio_image_for_owner(
            user=self.owner,
            upload=self.image_upload(),
            caption="Renovare interioară finalizată",
        )
        activate_or_extend_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=0,
            internal_note="Activare de test pentru ghidul de publicare.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )
        ready = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(ready.context["publication_checklist_complete"], 4)
        self.assertEqual(
            [step["status"] for step in ready.context["publication_checklist"]],
            ["complete", "complete", "complete", "complete", "action"],
        )

        submission, _created = submit_provider_publication_for_review(user=self.owner)
        pending = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(pending.context["publication_checklist"][4]["status"], "waiting")

        self.decide(submission)
        visible = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(visible.context["publication_checklist_complete"], 5)
        self.assertEqual(visible.context["publication_checklist"][4]["status"], "preview")
        self.assertContains(visible, "Preview intern")

        with patch(
            "services.views.provider_publication_effective_visibility",
            return_value=ProviderPublicationScope.Visibility.PUBLIC,
        ):
            public = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(public.context["publication_checklist"][4]["status"], "public")
        self.assertContains(public, "Versiunea aprobată este vizibilă public.")

        self.current.state = self.current.State.FAILED
        self.current.save(update_fields=("state",))
        invalid = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(invalid.context["publication_checklist"][4]["status"], "invalid")
        self.assertContains(invalid, "Vizibilitate suspendată")
        self.current.state = self.current.State.SUCCEEDED
        self.current.save(update_fields=("state",))

        self.assertTrue(unpublish_provider_profile(user=self.owner))
        withdrawn = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(
            withdrawn.context["publication_checklist"][4]["status"], "withdrawn"
        )
        self.assertContains(withdrawn, "Editează o versiune nouă")

    def test_owner_can_save_an_optional_normalized_professional_address(self):
        """The draft names the privacy boundary and persists only normalized text."""

        self.client.force_login(self.owner)
        page = self.client.get(reverse("services:provider_dashboard"))
        self.assertContains(page, "Adresă profesională publică (opțional)")
        self.assertContains(page, "Localitățile deservite se declară separat.")

        response = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "save_profile",
                "display_name": "Atelier Test",
                "description": "Descriere privată de test.",
                "public_address": "  Strada   Atelierului 12,   Iași  ",
                "public_phone": "0712 345 678",
                "public_email": "",
                "website": "",
                "availability": ProviderProfile.Availability.ACCEPTING,
                "contact_preference": ProviderProfile.ContactPreference.PHONE,
            },
        )

        self.assertRedirects(response, reverse("services:provider_dashboard"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.public_address, "Strada Atelierului 12, Iași")

    def test_dashboard_checklist_names_the_exact_missing_profile_requirement(self):
        """Do not ask again for a prerequisite that is already satisfied."""

        self.client.force_login(self.owner)
        ProviderProfile.objects.filter(pk=self.profile.pk).update(
            description=(
                "Descriere suficient de lungă pentru prezentarea serviciilor oferite "
                "și a modului în care firma lucrează cu beneficiarii locali."
            ),
            public_phone="",
        )
        contact_missing = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(
            contact_missing.context["publication_checklist"][0]["detail"],
            "Adaugă cel puțin o metodă publică de contact.",
        )

        ProviderProfile.objects.filter(pk=self.profile.pk).update(
            description="", public_phone="0712 345 678"
        )
        content_missing = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(
            content_missing.context["publication_checklist"][0]["detail"],
            "Completează numele public și o descriere de minimum 60 de caractere.",
        )

    def test_dashboard_checklist_exposes_service_changes_required(self):
        """Keep service feedback in an explicit actionable state."""

        self.client.force_login(self.owner)
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        service_submission, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )
        review_provider_service_area_submission(
            submission_id=service_submission.pk,
            reviewer=self.reviewer,
            decision=ProviderServiceAreaSubmission.Decision.CHANGES_REQUIRED,
            internal_note="Acoperirea declarată necesită clarificări suplimentare.",
            provider_feedback="Clarifică localitatea deservită înainte de retrimitere.",
            acknowledgement=OFFERING_ACKNOWLEDGEMENT,
        )
        service_changes = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(
            service_changes.context["publication_checklist"][1]["status"], "attention"
        )
        self.assertEqual(
            service_changes.context["publication_checklist"][1]["detail"],
            "Aplică observațiile primite și trimite o revizie nouă.",
        )
        self.assertEqual(
            service_changes.context["publication_checklist"][1]["anchor"], "servicii"
        )
        self.assertContains(
            service_changes,
            "Clarifică localitatea deservită înainte de retrimitere.",
        )

    def test_dashboard_checklist_exposes_publication_changes_required(self):
        """Keep publication feedback in an explicit actionable state."""

        self.client.force_login(self.owner)
        publication, _asset = self.prepare_publication()
        review_provider_publication(
            submission_id=publication.pk,
            reviewer=self.reviewer,
            decision=ProviderPublicationSubmission.Decision.CHANGES_REQUIRED,
            visibility=ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
            internal_note="Descrierea publică necesită clarificări înainte de activare.",
            provider_feedback="Clarifică descrierea lucrărilor înainte de retrimitere.",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        publication_changes = self.client.get(reverse("services:provider_dashboard"))
        self.assertEqual(
            publication_changes.context["publication_checklist"][4]["status"],
            "attention",
        )
        self.assertEqual(
            publication_changes.context["publication_checklist"][4]["detail"],
            "Aplică feedbackul publicării înainte de o nouă trimitere.",
        )
        self.assertEqual(
            publication_changes.context["publication_checklist"][4]["anchor"],
            "publicare",
        )
        self.assertContains(
            publication_changes,
            "Clarifică descrierea lucrărilor înainte de retrimitere.",
        )

    def test_upload_is_private_sanitized_and_bounded(self):
        asset_item = add_portfolio_image_for_owner(
            user=self.owner,
            upload=self.image_upload("original.jpg"),
            caption="  Lucrare   reală  ",
        )
        asset = asset_item.asset
        self.assertEqual(asset.mime_type, "image/webp")
        self.assertTrue(asset.image.name.endswith(".webp"))
        self.assertEqual(asset_item.caption, "Lucrare reală")
        anonymous = Client().get(
            reverse("services:provider_portfolio_image", args=(asset.opaque_id,))
        )
        self.assertEqual(anonymous.status_code, 404)
        owner_client = Client()
        owner_client.force_login(self.owner)
        owner_response = owner_client.get(
            reverse("services:provider_portfolio_image", args=(asset.opaque_id,))
        )
        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(owner_response["X-Content-Type-Options"], "nosniff")

    def test_invalid_upload_leaves_no_database_asset(self):
        invalid = SimpleUploadedFile("fals.jpg", b"nu este imagine", "image/jpeg")
        with self.assertRaisesMessage(ValueError, "imagine validă"):
            add_portfolio_image_for_owner(
                user=self.owner, upload=invalid, caption="Fișier invalid"
            )
        self.assertFalse(ProviderPortfolioAsset.objects.exists())

    def test_batch_upload_adds_every_image_with_one_content_revision(self):
        items = add_portfolio_images_for_owner(
            user=self.owner,
            uploads=(self.image_upload("fatada.jpg"), self.image_upload("interior.jpg")),
            caption="  Renovare   completă  ",
        )

        self.profile.refresh_from_db()
        self.assertEqual(len(items), 2)
        self.assertEqual([item.position for item in items], [1, 2])
        self.assertEqual([item.caption for item in items], ["Renovare completă"] * 2)
        self.assertEqual(self.profile.public_content_revision, 1)
        self.assertEqual(ProviderPortfolioAsset.objects.count(), 2)

    def test_invalid_batch_upload_leaves_no_partial_assets(self):
        invalid = SimpleUploadedFile("fals.jpg", b"nu este imagine", "image/jpeg")

        with self.assertRaisesMessage(ValueError, "imagine validă"):
            add_portfolio_images_for_owner(
                user=self.owner,
                uploads=(self.image_upload("valid.jpg"), invalid),
                caption="Lot invalid",
            )

        self.assertFalse(ProviderPortfolioAsset.objects.exists())

    def test_dashboard_accepts_several_portfolio_files_in_one_request(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "add_portfolio",
                "images": [
                    self.image_upload("prima.jpg"),
                    self.image_upload("a-doua.jpg"),
                ],
                "caption": "Șantier finalizat",
                "rights_confirmation": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 fotografii au fost adăugate")
        self.assertEqual(ProviderPortfolioAsset.objects.count(), 2)

    def test_submission_is_idempotent_and_copies_normalized_content(self):
        submission, asset = self.prepare_publication()
        same, created = submit_provider_publication_for_review(user=self.owner)
        self.assertFalse(created)
        self.assertEqual(same.pk, submission.pk)
        self.assertEqual(
            list(submission.services.values_list("category", flat=True)),
            ["constructii"],
        )
        self.assertEqual(
            list(submission.coverage.values_list("county", "siruta_code")),
            [("Iași", "95079")],
        )
        self.assertEqual(submission.portfolio_items.get().asset_sha256, asset.sha256)
        self.assertEqual(
            submission.availability, ProviderProfile.Availability.ACCEPTING
        )
        self.assertEqual(
            submission.contact_preference,
            ProviderProfile.ContactPreference.PHONE,
        )
        self.assertEqual(submission.public_address, "Strada Atelierului 12, Iași")
        self.assertEqual(submission.snapshot_schema_version, 3)
        self.assertEqual(len(submission.contract_sha256), 64)

    def test_preview_is_searchable_and_public_is_refused_without_legal_approval(self):
        submission, asset = self.prepare_publication()
        with self.assertRaisesMessage(ValueError, "aprobarea juridică"):
            self.decide(submission, ProviderPublicationScope.Visibility.PUBLIC)
        submission.refresh_from_db()
        self.assertEqual(submission.decision, ProviderPublicationSubmission.Decision.PENDING)

        decided, changed = self.decide(submission)
        self.assertTrue(changed)
        self.assertEqual(decided.decision, ProviderPublicationSubmission.Decision.APPROVED)
        results = published_provider_search(
            county="Iași", siruta_code="95079", category="constructii"
        )
        self.assertEqual([item.public_id for item in results], [self.profile.public_id])
        self.assertTrue(results[0].preview)
        self.assertEqual(results[0].availability_label, "Acceptă solicitări noi")
        self.assertEqual(results[0].contact_preference_label, "Telefon")
        self.assertEqual(results[0].public_address, "Strada Atelierului 12, Iași")
        self.assertEqual(results[0].portfolio[0].opaque_id, asset.opaque_id)
        self.assertEqual(ProviderPublicationEvent.objects.count(), 1)

        county_results = published_provider_search(
            county="Iași", siruta_code=None, category="constructii"
        )
        self.assertEqual([item.public_id for item in county_results], [self.profile.public_id])
        self.assertEqual(county_results[0].searched_locality_label, "Iași")
        self.assertEqual(county_results[0].searched_locality_code, "95079")

        county_page = Client().get(
            reverse("services:home"),
            {"county": "Iași", "locality": "", "category": "constructii"},
        )
        profile_url = reverse(
            "services:provider_public_detail", args=(self.profile.public_id,)
        )
        self.assertContains(
            county_page,
            f'{profile_url}?county=Ia%C8%99i&amp;locality=95079&amp;category=constructii',
        )

        response = Client().get(
            reverse("services:provider_public_detail", args=(self.profile.public_id,)),
            {"county": "Iași", "locality": "95079", "category": "constructii"},
        )
        self.assertContains(response, "Atelier Test Aproape")
        self.assertContains(response, "Previzualizare internă")
        self.assertNotContains(response, "Fișă revendicată")
        self.assertNotContains(response, "revendicarea")
        self.assertNotContains(response, "revizuite administrativ")
        self.assertNotContains(response, "Disponibilitate declarată")
        self.assertNotContains(response, "Contact preferat")
        self.assertContains(response, "Adresă profesională declarată")
        self.assertContains(response, "Strada Atelierului 12, Iași")
        self.assertContains(response, "0712 345 678")
        self.assertContains(response, "contact@atelier.example")
        self.assertContains(response, "https://atelier.example")
        self.assertContains(response, "Executăm lucrări de construcții")
        self.assertContains(response, "Construcții &amp; renovări")
        self.assertNotContains(response, "Servicii oferite")
        self.assertContains(response, 'class="provider-coverage-item"')
        self.assertContains(response, "Județ")
        self.assertContains(response, "Localitate")
        self.assertContains(response, "Renovare interioară finalizată")
        self.assertContains(
            response,
            reverse("services:provider_portfolio_image", args=(asset.opaque_id,)),
        )

        search_response = Client().get(
            reverse("services:home"),
            {"county": "Iași", "locality": "95079", "category": "constructii"},
        )
        self.assertContains(search_response, "Firme cu profil complet")
        self.assertContains(search_response, "Serviciu")
        self.assertContains(search_response, "Localitate")
        self.assertNotContains(search_response, "Previzualizare internă")
        self.assertNotContains(search_response, "Disponibilitate declarată")
        self.assertNotContains(search_response, "Contact preferat")

    def test_visible_profile_tracks_daily_engagement_without_storing_session_key(self):
        submission, _asset = self.prepare_publication()
        self.decide(submission)
        query = "county=Ia%C8%99i&locality=95079&category=constructii"
        profile_url = reverse(
            "services:provider_public_detail", args=(self.profile.public_id,)
        )
        tracker_url = reverse(
            "services:provider_engagement", args=(self.profile.public_id,)
        )
        public_client = Client()

        page = public_client.get(f"{profile_url}?{query}")
        self.assertContains(page, "provider_engagement.js")
        self.assertContains(page, 'data-provider-engagement="phone"')
        self.assertContains(page, 'data-provider-engagement="email"')
        self.assertContains(page, 'data-provider-engagement="website"')
        self.assertEqual(ProviderEngagementEvent.objects.count(), 0)

        first = public_client.post(
            f"{tracker_url}?{query}", {"event_type": "profile_view"}
        )
        duplicate = public_client.post(
            f"{tracker_url}?{query}", {"event_type": "profile_view"}
        )
        phone = public_client.post(
            f"{tracker_url}?{query}", {"event_type": "phone"}
        )
        invalid = public_client.post(
            f"{tracker_url}?{query}", {"event_type": "unknown"}
        )

        self.assertEqual(first.status_code, 204)
        self.assertEqual(duplicate.status_code, 204)
        self.assertEqual(phone.status_code, 204)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(ProviderEngagementEvent.objects.count(), 2)
        event = ProviderEngagementEvent.objects.get(
            event_type=ProviderEngagementEvent.EventType.PROFILE_VIEW
        )
        self.assertEqual(event.submission, submission)
        self.assertNotEqual(
            event.visitor_session_digest, public_client.session.session_key
        )

        self.client.force_login(self.owner)
        dashboard = self.client.get(
            reverse("services:provider_leads"), {"period": "7"}
        )
        self.assertContains(dashboard, "Performanța profilului")
        self.assertContains(dashboard, "Vizualizări profil")
        self.assertContains(dashboard, "Acțiuni de contact")
        self.assertEqual(dashboard.context["engagement_metrics"]["profile_views"], 1)
        self.assertEqual(dashboard.context["engagement_metrics"]["phone"], 1)
        self.assertEqual(dashboard.context["engagement_metrics"]["interest_rate"], 100)

    def test_visitor_can_save_and_remove_a_visible_provider_without_an_account(self):
        """The shortlist stays session-local and never bypasses publication visibility."""

        submission, _asset = self.prepare_publication()
        self.decide(submission)
        query = "county=Ia%C8%99i&locality=95079&category=constructii"
        toggle_url = reverse(
            "services:provider_shortlist_toggle", args=(self.profile.public_id,)
        )
        shortlist_url = reverse("services:provider_shortlist")
        public_client = Client()
        search = public_client.get(
            reverse("services:home"),
            {"county": "Iași", "locality": "95079", "category": "constructii"},
        )
        self.assertContains(search, "Atelier Test Aproape")
        self.assertNotContains(search, "Salvează firma")

        saved = public_client.post(
            f"{toggle_url}?{query}", {"return_to": "shortlist"}
        )
        self.assertRedirects(saved, shortlist_url)
        self.assertEqual(
            public_client.session["provider_shortlist_v1"][0]["public_id"],
            str(self.profile.public_id),
        )

        shortlist = public_client.get(shortlist_url)
        self.assertContains(shortlist, "Atelier Test Aproape")
        self.assertContains(shortlist, "Executăm lucrări de construcții")
        self.assertContains(shortlist, "Iași")
        self.assertContains(shortlist, "Elimină")
        self.assertIn("private", shortlist.headers["Cache-Control"])
        profile = public_client.get(
            reverse("services:provider_public_detail", args=(self.profile.public_id,)),
            {"county": "Iași", "locality": "95079", "category": "constructii"},
        )
        self.assertContains(profile, 'aria-label="Elimină din lista salvată"')
        self.assertContains(profile, 'aria-pressed="true"')

        removed = public_client.post(
            f"{toggle_url}?{query}", {"return_to": "shortlist"}
        )
        self.assertRedirects(removed, shortlist_url)
        empty = public_client.get(shortlist_url)
        self.assertContains(empty, "Lista este pregătită pentru prima firmă")
        self.assertNotContains(empty, "Atelier Test Aproape")

    def test_shortlist_rejects_hidden_profiles_and_prunes_expired_entries(self):
        """A saved public identifier never becomes an alternate reader for hidden data."""

        submission, _asset = self.prepare_publication()
        toggle_url = reverse(
            "services:provider_shortlist_toggle", args=(self.profile.public_id,)
        )
        query = "county=Ia%C8%99i&locality=95079&category=constructii"
        public_client = Client()
        self.assertEqual(public_client.post(f"{toggle_url}?{query}").status_code, 404)

        self.decide(submission)
        public_client.post(f"{toggle_url}?{query}")
        subscription = ProviderSubscription.objects.get(profile=self.profile)
        deactivate_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=subscription.revision,
            internal_note="Profil retras pentru testul listei salvate.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )

        shortlist = public_client.get(reverse("services:provider_shortlist"))
        self.assertContains(shortlist, "Lista este pregătită pentru prima firmă")
        self.assertEqual(public_client.session["provider_shortlist_v1"], [])

    def test_engagement_endpoint_rejects_get_and_hidden_profile(self):
        submission, _asset = self.prepare_publication()
        tracker_url = reverse(
            "services:provider_engagement", args=(self.profile.public_id,)
        )
        query = "county=Ia%C8%99i&locality=95079&category=constructii"

        self.assertEqual(self.client.get(f"{tracker_url}?{query}").status_code, 405)
        self.assertEqual(
            self.client.post(
                f"{tracker_url}?{query}", {"event_type": "profile_view"}
            ).status_code,
            404,
        )
        self.assertEqual(ProviderEngagementEvent.objects.count(), 0)

    def test_visible_profile_accepts_one_privacy_minimized_report_per_session(self):
        submission, _asset = self.prepare_publication()
        self.decide(submission)
        report_url = reverse("services:provider_report", args=(self.profile.public_id,))
        query = {"county": "Iași", "locality": "95079", "category": "constructii"}

        page = self.client.get(report_url, query)
        self.assertContains(page, "Semnalează o problemă în profil")
        self.assertContains(page, "Nu cerem numele, e-mailul sau telefonul tău")

        invalid = self.client.post(
            f"{report_url}?county=Ia%C8%99i&locality=95079&category=constructii",
            {"reason": PublicProviderReport.Reason.INCORRECT_INFORMATION},
        )
        self.assertContains(invalid, "Descrie problema observată.")
        self.assertContains(invalid, 'id="id_details_helptext"')
        self.assertContains(invalid, 'id="id_details_error"')
        self.assertContains(invalid, "autofocus")

        response = self.client.post(
            f"{report_url}?county=Ia%C8%99i&locality=95079&category=constructii",
            {
                "reason": PublicProviderReport.Reason.INCORRECT_INFORMATION,
                "details": "  Datele despre serviciile prestate nu corespund profilului văzut.  ",
                "website": "",
            },
        )
        self.assertContains(response, "Sesizarea a fost înregistrată")
        report = PublicProviderReport.objects.get()
        self.assertEqual(report.submission, submission)
        self.assertEqual(
            report.details,
            "Datele despre serviciile prestate nu corespund profilului văzut.",
        )
        self.assertNotEqual(
            report.reporter_session_digest,
            self.client.session.session_key,
        )

        duplicate = self.client.post(
            f"{report_url}?county=Ia%C8%99i&locality=95079&category=constructii",
            {
                "reason": PublicProviderReport.Reason.OTHER,
                "details": "Încerc să trimit încă o sesizare pentru aceeași versiune publică.",
                "website": "",
            },
        )
        self.assertContains(duplicate, "Ai sesizat deja această versiune")
        self.assertEqual(PublicProviderReport.objects.count(), 1)
        report.refresh_from_db()
        self.assertEqual(
            report.reason,
            PublicProviderReport.Reason.INCORRECT_INFORMATION,
        )

    def test_report_route_fails_closed_after_profile_withdrawal(self):
        submission, _asset = self.prepare_publication()
        self.decide(submission)
        report_url = reverse("services:provider_report", args=(self.profile.public_id,))
        self.assertTrue(unpublish_provider_profile(user=self.owner))

        response = self.client.get(
            report_url,
            {"county": "Iași", "locality": "95079", "category": "constructii"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(PublicProviderReport.objects.exists())

    def test_legacy_publication_does_not_invent_provider_declarations(self):
        """Schema-1 defaults are storage compatibility, not historical declarations."""

        submission, _asset = self.prepare_publication()
        self.decide(submission)
        ProviderPublicationSubmission.objects.filter(pk=submission.pk).update(
            snapshot_schema_version=1,
            availability=ProviderProfile.Availability.NOT_SPECIFIED,
            contact_preference=ProviderProfile.ContactPreference.ANY,
        )

        result = published_provider_search(
            county="Iași", siruta_code="95079", category="constructii"
        )[0]
        unavailable = "Nedeclarată în versiunea profilului publicat"
        self.assertEqual(result.availability_label, unavailable)
        self.assertEqual(result.contact_preference_label, unavailable)

    def test_profile_edit_immediately_unpublishes_and_supersedes_snapshot(self):
        submission, _asset = self.prepare_publication()
        self.decide(submission)
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Test Modificat",
                "description": submission.description,
                "public_address": submission.public_address,
                "public_phone": submission.public_phone,
                "public_email": submission.public_email,
                "website": submission.website,
                "availability": ProviderProfile.Availability.LIMITED,
                "contact_preference": submission.contact_preference,
            },
        )
        submission.refresh_from_db()
        scope = ProviderPublicationScope.objects.get(profile=self.profile)
        self.assertIsNotNone(submission.superseded_at)
        self.assertEqual(scope.visibility, ProviderPublicationScope.Visibility.OFF)
        self.assertIsNone(scope.current_submission)
        self.assertFalse(
            published_provider_search(
                county="Iași", siruta_code="95079", category="constructii"
            )
        )

    def test_preferred_contact_must_have_a_public_value(self):
        with self.assertRaisesMessage(ValueError, "trebuie completată"):
            save_provider_profile_for_owner(
                user=self.owner,
                values={
                    "display_name": "Atelier Test",
                    "description": "Descriere privată de test.",
                    "public_phone": "",
                    "public_email": "contact@atelier.example",
                    "website": "",
                    "availability": ProviderProfile.Availability.LIMITED,
                    "contact_preference": ProviderProfile.ContactPreference.PHONE,
                },
            )

    def test_legacy_snapshot_never_exposes_a_migrated_address(self):
        """Schema-2 snapshots did not review an address, even if storage is altered."""

        submission, _asset = self.prepare_publication()
        self.decide(submission)
        ProviderPublicationSubmission.objects.filter(pk=submission.pk).update(
            snapshot_schema_version=2,
            public_address="Adresă care nu făcea parte din contract",
        )

        result = published_provider_search(
            county="Iași", siruta_code="95079", category="constructii"
        )[0]

        self.assertEqual(result.public_address, "")

    def test_revoked_snapshot_asset_hides_whole_profile_fail_closed(self):
        submission, asset = self.prepare_publication()
        self.decide(submission)
        ProviderPortfolioAsset.objects.filter(pk=asset.pk).update(
            state=ProviderPortfolioAsset.State.REVOKED,
            revoked_by=self.reviewer,
            revoked_at=timezone.now(),
        )
        self.assertFalse(
            published_provider_search(
                county="Iași", siruta_code="95079", category="constructii"
            )
        )

    def test_staff_reviewer_can_preview_private_image(self):
        _submission, asset = self.prepare_publication()
        reviewer_client = Client()
        reviewer_client.force_login(self.reviewer)
        response = reviewer_client.get(
            reverse("services:provider_portfolio_image", args=(asset.opaque_id,))
        )
        self.assertEqual(response.status_code, 200)

    def test_report_triage_is_audited_and_never_changes_publication(self):
        report, case = self.prepare_report_case()
        scope = ProviderPublicationScope.objects.get(profile=self.profile)
        original_scope = (scope.visibility, scope.current_submission_id)

        start_public_provider_report_review(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Am verificat sesizarea și snapshotul indicat.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        case.refresh_from_db()
        self.assertEqual(case.state, PublicProviderReportCase.State.IN_REVIEW)
        self.assertEqual(case.revision, 1)
        with self.assertRaisesMessage(ValueError, "modificat de alt administrator"):
            start_public_provider_report_review(
                case_id=case.pk,
                reviewer=self.reviewer,
                expected_revision=0,
                internal_note="O încercare concurentă nu trebuie acceptată.",
                acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
            )

        close_public_provider_report_case(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.SEPARATE_FOLLOW_UP_REQUIRED,
            internal_note="Este necesară o verificare separată a datelor publicate.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        case.refresh_from_db()
        report.refresh_from_db()
        scope.refresh_from_db()
        self.assertEqual(case.state, PublicProviderReportCase.State.CLOSED)
        self.assertEqual(case.revision, 2)
        self.assertEqual(case.events.count(), 2)
        self.assertEqual(PublicProviderReportTriageEvent.objects.count(), 2)
        self.assertEqual(report.details, "Datele publice necesită verificare factuală.")
        self.assertEqual((scope.visibility, scope.current_submission_id), original_scope)

    def test_report_triage_blocks_snapshot_drift_and_provider_conflict(self):
        report, case = self.prepare_report_case()
        ProviderPublicationSubmission.objects.filter(pk=report.submission_id).update(
            display_name="Snapshot modificat nepermis"
        )
        with self.assertRaisesMessage(ValueError, "Integritatea snapshotului"):
            start_public_provider_report_review(
                case_id=case.pk,
                reviewer=self.reviewer,
                expected_revision=0,
                internal_note="Am încercat să verific snapshotul raportat.",
                acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
            )
        self.assertFalse(PublicProviderReportTriageEvent.objects.exists())
        client = Client()
        client.force_login(self.reviewer)
        blocked = client.get(
            reverse("admin:services_publicproviderreport_triage", args=(report.pk,))
        )
        self.assertContains(blocked, "Acțiunile de analiză sunt indisponibile")
        self.assertNotContains(blocked, "Preia sesizarea")

        report.submission.refresh_from_db()
        ProviderPublicationSubmission.objects.filter(pk=report.submission_id).update(
            display_name="Atelier Test Aproape"
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=("is_staff",))
        self.owner.user_permissions.add(
            Permission.objects.get(codename="triage_public_provider_report")
        )
        with self.assertRaisesMessage(PermissionError, "propriul profil"):
            start_public_provider_report_review(
                case_id=case.pk,
                reviewer=self.owner,
                expected_revision=0,
                internal_note="Conflictul de interese trebuie blocat.",
                acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
            )

    def test_admin_report_triage_requires_permission_csrf_and_escapes_details(self):
        report, case = self.prepare_report_case(details="<script>alert('x')</script> Date false.")
        url = reverse("admin:services_publicproviderreport_triage", args=(report.pk,))

        view_only = get_user_model().objects.create_user(
            username="report-view-only", is_staff=True
        )
        view_only.user_permissions.add(
            Permission.objects.get(codename="view_publicproviderreport")
        )
        view_client = Client()
        view_client.force_login(view_only)
        self.assertEqual(view_client.get(url).status_code, 403)

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        self.assertEqual(
            client.post(
                url,
                {
                    "expected_revision": 0,
                    "internal_note": "Sesizarea a fost preluată pentru verificare.",
                    "acknowledgement": "on",
                },
            ).status_code,
            403,
        )
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<label for="id_internal_note"><strong>Notă internă</strong></label>', html=True)
        self.assertContains(page, "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", html=False)
        self.assertNotContains(page, "<script>alert('x')</script>", html=False)
        csrf_token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()
        ).group(1)
        response = client.post(
            url,
            {
                "csrfmiddlewaretoken": csrf_token,
                "expected_revision": case.revision,
                "internal_note": "Sesizarea a fost preluată pentru verificare.",
                "acknowledgement": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.state, PublicProviderReportCase.State.IN_REVIEW)

    def test_report_insights_use_four_bounded_aggregate_queries_and_exact_window(self):
        now = timezone.now()
        window_start = now - timedelta(days=30)
        first_report, first_case = self.prepare_report_case()
        submission = first_report.submission
        PublicProviderReport.objects.filter(pk=first_report.pk).update(
            created_at=window_start
        )

        closed_report, _created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.WRONG_SERVICE,
            details="Categoria trebuie verificată în raport cu snapshotul.",
            session_key="insight-closed-session",
        )
        start_public_provider_report_review(
            case_id=closed_report.triage_case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Am preluat dosarul pentru verificarea categoriei.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=closed_report.triage_case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.DUPLICATE,
            internal_note="Sesizarea dublează un dosar operațional deja verificat.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        in_window_timestamp = now - timedelta(seconds=1)
        PublicProviderReport.objects.filter(pk=closed_report.pk).update(
            created_at=in_window_timestamp
        )
        PublicProviderReportTriageEvent.objects.filter(
            case=closed_report.triage_case
        ).update(created_at=in_window_timestamp)

        old_report, _created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.OTHER,
            details="Raport istoric în afara ferestrei de analiză.",
            session_key="insight-old-session",
        )
        start_public_provider_report_review(
            case_id=old_report.triage_case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Dosar istoric preluat înaintea ferestrei curente.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        old_timestamp = window_start - timedelta(seconds=1)
        PublicProviderReport.objects.filter(pk=old_report.pk).update(
            created_at=old_timestamp
        )
        PublicProviderReportTriageEvent.objects.filter(
            case=old_report.triage_case
        ).update(created_at=old_timestamp)

        missing_case_report, _created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.UNREACHABLE_CONTACT,
            details="Raport de integritate fără dosar operațional.",
            session_key="insight-missing-case-session",
        )
        missing_case_report.triage_case.delete()
        PublicProviderReport.objects.filter(pk=missing_case_report.pk).update(
            created_at=now
        )

        with self.assertNumQueries(4):
            insights = public_report_insights(window_days=30, calculated_at=now)

        self.assertEqual(
            {item.value: item.count for item in insights.current_states},
            {"new": 1, "in_review": 1, "closed": 1},
        )
        self.assertEqual(
            {item.value: item.count for item in insights.intake_reasons},
            {
                "incorrect_information": 1,
                "wrong_service": 1,
                "unreachable_contact": 0,
                "inappropriate_portfolio": 0,
                "other": 0,
            },
        )
        self.assertEqual(insights.started_transitions, 1)
        self.assertEqual(insights.closed_transitions, 1)
        self.assertEqual(
            dict((item.value, item.count) for item in insights.closed_outcomes)[
                "duplicate"
            ],
            1,
        )
        self.assertEqual(insights.reports_without_case, 1)
        self.assertEqual(insights.window_start, window_start)
        self.assertEqual(insights.window_end, now)
        self.assertEqual(first_case.state, PublicProviderReportCase.State.NEW)

    def test_admin_report_insights_are_least_privilege_get_only_and_identity_free(self):
        report, _case = self.prepare_report_case(
            details="DETALIU-PRIVAT-NU-TREBUIE-AFIȘAT"
        )
        url = reverse("admin:services_publicproviderreport_insights")
        self.assertEqual(Client().get(url).status_code, 302)

        view_only = get_user_model().objects.create_user(
            username="insights-view-only", is_staff=True
        )
        view_only.user_permissions.add(
            Permission.objects.get(codename="view_publicproviderreport")
        )
        blocked_client = Client()
        blocked_client.force_login(view_only)
        self.assertEqual(blocked_client.get(url).status_code, 403)

        observer = get_user_model().objects.create_user(
            username="insights-observer", is_staff=True
        )
        observer.user_permissions.add(
            Permission.objects.get(codename="view_publicproviderreport"),
            Permission.objects.get(
                codename="view_public_provider_report_insights"
            ),
        )
        observer_client = Client()
        observer_client.force_login(observer)
        page = observer_client.get(f"{url}?days=7")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["report_insights"].window_days, 7)
        self.assertContains(page, "arată numai agregate despre coada administrativă")
        for title_id in (
            "queue-state-title",
            "intake-reasons-title",
            "transitions-title",
            "outcomes-title",
        ):
            self.assertContains(page, f'<table aria-labelledby="{title_id}">')
        self.assertNotContains(page, report.details)
        fallback = observer_client.get(f"{url}?days=365")
        self.assertEqual(fallback.context["report_insights"].window_days, 30)

        before = (
            PublicProviderReport.objects.count(),
            PublicProviderReportCase.objects.count(),
            PublicProviderReportTriageEvent.objects.count(),
            ProviderPublicationScope.objects.get(profile=self.profile).visibility,
        )
        self.assertEqual(observer_client.post(url).status_code, 405)
        after = (
            PublicProviderReport.objects.count(),
            PublicProviderReportCase.objects.count(),
            PublicProviderReportTriageEvent.objects.count(),
            ProviderPublicationScope.objects.get(profile=self.profile).visibility,
        )
        self.assertEqual(after, before)

    def test_report_insights_have_a_complete_zero_data_state(self):
        now = timezone.now()
        with self.assertNumQueries(4):
            insights = public_report_insights(window_days="invalid", calculated_at=now)
        self.assertEqual(insights.window_days, 30)
        self.assertEqual(sum(item.count for item in insights.current_states), 0)
        self.assertEqual(sum(item.count for item in insights.intake_reasons), 0)
        self.assertEqual(insights.started_transitions, 0)
        self.assertEqual(insights.closed_transitions, 0)
        self.assertEqual(sum(item.count for item in insights.closed_outcomes), 0)
        self.assertEqual(insights.reports_without_case, 0)
        self.assertEqual(insights.current_total, 0)

    def test_report_triage_integrity_audit_accepts_valid_chains_in_one_query(self):
        first_report, _case = self.prepare_report_case()
        submission = first_report.submission
        for index in range(12):
            create_public_provider_report(
                submission=submission,
                reason=PublicProviderReport.Reason.OTHER,
                details="Sesizare suplimentară pentru auditul cu volum controlat.",
                session_key=f"integrity-valid-{index}",
            )
        reviewed_report, _created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.WRONG_SERVICE,
            details="Serviciul necesită o verificare operațională.",
            session_key="integrity-reviewed",
        )
        start_public_provider_report_review(
            case_id=reviewed_report.triage_case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Sesizarea a fost preluată pentru auditul lanțului valid.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        closed_report, _created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.UNREACHABLE_CONTACT,
            details="Contactul necesită o verificare operațională.",
            session_key="integrity-closed",
        )
        start_public_provider_report_review(
            case_id=closed_report.triage_case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Sesizarea a fost preluată înainte de închiderea controlată.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=closed_report.triage_case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.NO_ISSUE_FOUND,
            internal_note="Verificarea s-a încheiat fără confirmarea unei probleme.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )

        with self.assertNumQueries(1):
            audit = audit_public_provider_report_triage(chunk_size=3)

        self.assertTrue(audit.is_valid)
        self.assertEqual(audit.total_reports, 15)
        self.assertEqual(audit.total_cases, 15)
        self.assertEqual(audit.total_events, 3)
        self.assertFalse(any(dict(audit.anomaly_counts).values()))

    def test_report_triage_integrity_audit_reports_drift_without_mutation(self):
        report, case = self.prepare_report_case()
        report.triage_case.delete()
        before = (
            PublicProviderReport.objects.count(),
            PublicProviderReportCase.objects.count(),
            PublicProviderReportTriageEvent.objects.count(),
            report.details,
        )

        audit = audit_public_provider_report_triage()

        self.assertFalse(audit.is_valid)
        self.assertEqual(dict(audit.anomaly_counts)["report_without_case"], 1)
        report.refresh_from_db()
        after = (
            PublicProviderReport.objects.count(),
            PublicProviderReportCase.objects.count(),
            PublicProviderReportTriageEvent.objects.count(),
            report.details,
        )
        self.assertEqual(after, before)

    def test_report_triage_integrity_audit_classifies_chain_mismatches(self):
        _report, case = self.prepare_report_case()
        start_public_provider_report_review(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Sesizarea a fost preluată pentru verificarea auditului.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.NO_ISSUE_FOUND,
            internal_note="Dosarul a fost închis pentru verificarea auditului.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        PublicProviderReportCase.objects.filter(pk=case.pk).update(revision=9)
        PublicProviderReportTriageEvent.objects.filter(
            case=case, revision=1
        ).update(previous_state=PublicProviderReportCase.State.CLOSED)
        PublicProviderReportTriageEvent.objects.filter(
            case=case, revision=2
        ).update(outcome=PublicProviderReportCase.Outcome.DUPLICATE)

        audit = audit_public_provider_report_triage()
        anomalies = dict(audit.anomaly_counts)

        self.assertFalse(audit.is_valid)
        self.assertEqual(anomalies["case_revision_mismatch"], 1)
        self.assertEqual(anomalies["event_transition_mismatch"], 1)
        self.assertEqual(anomalies["event_outcome_mismatch"], 1)

    def test_report_triage_integrity_audit_classifies_revision_independently(self):
        _report, case = self.prepare_report_case()
        start_public_provider_report_review(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Sesizarea a fost preluată pentru controlul reviziilor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.NO_ISSUE_FOUND,
            internal_note="Dosarul a fost închis pentru controlul reviziilor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        PublicProviderReportTriageEvent.objects.filter(
            case=case, revision=1
        ).update(revision=3)

        anomalies = dict(audit_public_provider_report_triage().anomaly_counts)

        self.assertEqual(anomalies["event_revision_mismatch"], 1)
        self.assertEqual(anomalies["event_transition_mismatch"], 0)
        self.assertEqual(anomalies["event_outcome_mismatch"], 0)

    def test_report_triage_integrity_audit_checks_metadata_and_chronology(self):
        _report, case = self.prepare_report_case()
        start_public_provider_report_review(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Sesizarea a fost preluată pentru controlul metadatelor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.NO_ISSUE_FOUND,
            internal_note="Dosarul a fost închis pentru controlul cronologiei.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        now = timezone.now()
        PublicProviderReportTriageEvent.objects.filter(
            case=case, revision=1
        ).update(
            policy_version="versiune-neacceptată",
            acknowledgement="confirmare arbitrară",
            internal_note="scurt",
            created_at=now,
        )
        PublicProviderReportTriageEvent.objects.filter(
            case=case, revision=2
        ).update(created_at=now - timedelta(seconds=1))

        anomalies = dict(audit_public_provider_report_triage().anomaly_counts)

        self.assertEqual(anomalies["event_metadata_mismatch"], 1)
        self.assertEqual(anomalies["event_chronology_mismatch"], 1)
        self.assertEqual(anomalies["event_count_mismatch"], 0)
        self.assertEqual(anomalies["event_transition_mismatch"], 0)
        self.assertEqual(anomalies["event_revision_mismatch"], 0)
        self.assertEqual(anomalies["event_outcome_mismatch"], 0)

    def test_report_triage_integrity_audit_detects_missing_and_extra_events(self):
        first_report, first_case = self.prepare_report_case()
        start_public_provider_report_review(
            case_id=first_case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Primul dosar este preluat pentru controlul evenimentelor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=first_case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.NO_ISSUE_FOUND,
            internal_note="Primul dosar este închis pentru controlul evenimentelor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        PublicProviderReportTriageEvent.objects.filter(
            case=first_case, revision=1
        ).delete()

        second_report, _created = create_public_provider_report(
            submission=first_report.submission,
            reason=PublicProviderReport.Reason.OTHER,
            details="Al doilea dosar verifică evenimentele suplimentare.",
            session_key="integrity-extra-event",
        )
        second_case = second_report.triage_case
        start_public_provider_report_review(
            case_id=second_case.pk,
            reviewer=self.reviewer,
            expected_revision=0,
            internal_note="Al doilea dosar este preluat pentru controlul evenimentelor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        close_public_provider_report_case(
            case_id=second_case.pk,
            reviewer=self.reviewer,
            expected_revision=1,
            outcome=PublicProviderReportCase.Outcome.DUPLICATE,
            internal_note="Al doilea dosar este închis pentru controlul evenimentelor.",
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
        )
        PublicProviderReportTriageEvent.objects.create(
            case=second_case,
            previous_state=PublicProviderReportCase.State.IN_REVIEW,
            new_state=PublicProviderReportCase.State.CLOSED,
            outcome=PublicProviderReportCase.Outcome.DUPLICATE,
            revision=3,
            internal_note="Eveniment suplimentar injectat exclusiv pentru test.",
            policy_version=TRIAGE_POLICY_VERSION,
            acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
            actor=self.reviewer,
        )

        anomalies = dict(audit_public_provider_report_triage().anomaly_counts)

        self.assertEqual(anomalies["event_count_mismatch"], 2)
        self.assertEqual(anomalies["event_transition_mismatch"], 2)
        self.assertEqual(anomalies["event_revision_mismatch"], 2)
        self.assertEqual(anomalies["event_outcome_mismatch"], 2)

    def test_report_triage_integrity_command_prints_json_and_fails_on_drift(self):
        report, _case = self.prepare_report_case()
        valid_output = StringIO()
        call_command(
            "audit_public_provider_report_triage",
            stdout=valid_output,
        )
        valid_payload = json.loads(valid_output.getvalue())
        self.assertTrue(valid_payload["valid"])
        self.assertNotIn(report.details, valid_output.getvalue())

        report.triage_case.delete()
        invalid_output = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "audit_public_provider_report_triage",
                stdout=invalid_output,
            )
        invalid_payload = json.loads(invalid_output.getvalue())
        self.assertFalse(invalid_payload["valid"])
        self.assertEqual(invalid_payload["anomalies"]["report_without_case"], 1)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row locks")
@override_settings(DEBUG=True)
class ProviderPublicationConcurrencyTests(
    ProviderOfferingFixtureMixin, TransactionTestCase
):
    """Prove that two moderators cannot activate the same snapshot twice."""

    reset_sequences = True

    def setUp(self):
        self.private_media = tempfile.mkdtemp(prefix="servicii-aproape-pg-media-")
        self.settings_override = override_settings(MEDIA_ROOT=self.private_media)
        self.settings_override.enable()
        self.create_fixture()
        permissions = Permission.objects.filter(
            codename__in=("review_provider_service_area", "review_provider_publication", "publish_provider_profile", "manage_provider_subscription")
        )
        self.reviewer.user_permissions.add(*permissions)
        self.second_reviewer = get_user_model().objects.create_user(
            username="publication-reviewer-second", is_staff=True
        )
        self.second_reviewer.user_permissions.add(*permissions)

        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        service_submission, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )
        review_provider_service_area_submission(
            submission_id=service_submission.pk,
            reviewer=self.reviewer,
            decision=ProviderServiceAreaSubmission.Decision.APPROVED,
            internal_note="Serviciile și acoperirea au fost verificate.",
            provider_feedback="",
            acknowledgement=OFFERING_ACKNOWLEDGEMENT,
        )
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Concurent",
                "description": (
                    "Executăm lucrări complete de construcții pentru locuințe, "
                    "cu ofertă documentată și acoperire declarată în municipiul Iași."
                ),
                "public_phone": "0712 345 678",
                "public_email": "contact@concurent.example",
                "website": "",
            },
        )
        add_portfolio_image_for_owner(
            user=self.owner,
            upload=ProviderPublicationTests.image_upload("concurenta.jpg"),
            caption="Lucrare verificată",
        )
        activate_or_extend_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=0,
            internal_note="Activare de test pentru publicarea concurentă.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )
        self.submission, _created = submit_provider_publication_for_review(
            user=self.owner
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.private_media, ignore_errors=True)

    def test_two_reviewers_produce_one_activation_event(self):
        barrier = Barrier(2)
        outcomes = []

        def reviewer_task(reviewer_id):
            close_old_connections()
            reviewer = get_user_model().objects.get(pk=reviewer_id)
            barrier.wait()
            try:
                _submission, changed = review_provider_publication(
                    submission_id=self.submission.pk,
                    reviewer=reviewer,
                    decision=ProviderPublicationSubmission.Decision.APPROVED,
                    visibility=ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
                    internal_note="Snapshotul complet a fost verificat administrativ.",
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
            for reviewer in (self.reviewer, self.second_reviewer)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, [True, "conflict"])
        self.assertEqual(ProviderPublicationEvent.objects.count(), 1)
        scope = ProviderPublicationScope.objects.get(profile=self.profile)
        self.assertEqual(scope.current_submission, self.submission)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row locks")
@override_settings(DEBUG=True)
class PublicProviderReportTriageConcurrencyTests(
    ProviderOfferingFixtureMixin, TransactionTestCase
):
    """Prove that the stable case row serializes competing triage claims."""

    reset_sequences = True

    def setUp(self):
        self.private_media = tempfile.mkdtemp(prefix="servicii-aproape-triage-pg-")
        self.settings_override = override_settings(MEDIA_ROOT=self.private_media)
        self.settings_override.enable()
        self.create_fixture()
        permissions = Permission.objects.filter(
            codename__in=(
                "review_provider_service_area",
                "review_provider_publication",
                "publish_provider_profile",
                "triage_public_provider_report",
                "manage_provider_subscription",
            )
        )
        self.reviewer.user_permissions.add(*permissions)
        self.second_reviewer = get_user_model().objects.create_user(
            username="triage-reviewer-second", is_staff=True
        )
        self.second_reviewer.user_permissions.add(*permissions)

        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        service_submission, _created = submit_provider_service_area_for_review(
            user=self.owner, expected_revision=1
        )
        review_provider_service_area_submission(
            submission_id=service_submission.pk,
            reviewer=self.reviewer,
            decision=ProviderServiceAreaSubmission.Decision.APPROVED,
            internal_note="Serviciile și acoperirea au fost verificate.",
            provider_feedback="",
            acknowledgement=OFFERING_ACKNOWLEDGEMENT,
        )
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Sesizare Concurentă",
                "description": "Profil complet pentru verificarea concurenței administrative.",
                "public_phone": "0712 345 678",
                "public_email": "contact@concurenta.example",
                "website": "",
            },
        )
        add_portfolio_image_for_owner(
            user=self.owner,
            upload=ProviderPublicationTests.image_upload("sesizare-concurenta.jpg"),
            caption="Lucrare din snapshot",
        )
        activate_or_extend_provider_subscription(
            profile_id=self.profile.pk,
            actor=self.reviewer,
            expected_revision=0,
            internal_note="Activare de test pentru sesizarea concurentă.",
            acknowledgement=SUBSCRIPTION_ACKNOWLEDGEMENT,
        )
        submission, _created = submit_provider_publication_for_review(user=self.owner)
        review_provider_publication(
            submission_id=submission.pk,
            reviewer=self.reviewer,
            decision=ProviderPublicationSubmission.Decision.APPROVED,
            visibility=ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
            internal_note="Snapshotul complet a fost verificat administrativ.",
            provider_feedback="",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        report, _created = create_public_provider_report(
            submission=submission,
            reason=PublicProviderReport.Reason.OTHER,
            details="Sesizare concurentă pentru testarea blocării dosarului.",
            session_key="pg-triage-session",
        )
        self.case = report.triage_case

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.private_media, ignore_errors=True)

    def test_two_reviewers_create_one_first_transition(self):
        barrier = Barrier(2)
        outcomes = []

        def reviewer_task(reviewer_id):
            close_old_connections()
            reviewer = get_user_model().objects.get(pk=reviewer_id)
            barrier.wait()
            try:
                start_public_provider_report_review(
                    case_id=self.case.pk,
                    reviewer=reviewer,
                    expected_revision=0,
                    internal_note="Sesizarea a fost preluată în analiza concurentă.",
                    acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
                )
            except ValueError:
                outcomes.append("conflict")
            else:
                outcomes.append("started")
            finally:
                connection.close()

        threads = [
            Thread(target=reviewer_task, args=(reviewer.pk,))
            for reviewer in (self.reviewer, self.second_reviewer)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, ["started", "conflict"])
        self.assertEqual(PublicProviderReportTriageEvent.objects.count(), 1)
        self.case.refresh_from_db()
        self.assertEqual(self.case.revision, 1)
