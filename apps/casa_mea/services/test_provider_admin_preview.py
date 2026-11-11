"""Administrative provider-account preview authorization and inertness tests."""

from io import BytesIO
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import (
    ProviderProfile,
    ProviderPublicationScope,
    ProviderPublicationSubmission,
    ProviderSubscription,
    ProviderSubscriptionEvent,
)
from .provider_offerings import replace_provider_services_and_coverage_for_owner
from .provider_publication import add_portfolio_image_for_owner, save_provider_profile_for_owner
from .provider_subscriptions import provider_subscription_state
from .test_provider_offerings import ProviderOfferingFixtureMixin


class ProviderAdminPreviewTests(ProviderOfferingFixtureMixin, TestCase):
    """Keep staff preview read-only, permission-gated, and distinct from publication."""

    def setUp(self):
        self.private_media = tempfile.mkdtemp(prefix="servicii-aproape-admin-preview-")
        self.settings_override = override_settings(MEDIA_ROOT=self.private_media)
        self.settings_override.enable()
        self.create_fixture()
        save_provider_profile_for_owner(
            user=self.owner,
            values={
                "display_name": "Atelier Test Aproape",
                "description": "Renovăm locuințe și explicăm clar fiecare etapă.",
                "public_address": "Strada Atelierului 12, Iași",
                "public_phone": "0712 345 678",
                "public_email": "contact@atelier.example",
                "website": "https://atelier.example",
                "availability": ProviderProfile.Availability.LIMITED,
                "contact_preference": ProviderProfile.ContactPreference.EMAIL,
            },
        )
        replace_provider_services_and_coverage_for_owner(
            user=self.owner,
            expected_revision=0,
            categories=["constructii"],
            coverage_pairs=[("Iași", "95079")],
        )
        self.portfolio_item = add_portfolio_image_for_owner(
            user=self.owner,
            upload=self.image_upload(),
            caption="Renovare interioară",
        )
        User = get_user_model()
        self.viewer = User.objects.create_user(
            username="profile-viewer",
            email="admin@example.test",
            password="preview-test-password",
            is_active=True,
            is_staff=True,
        )
        self.viewer.user_permissions.add(Permission.objects.get(codename="view_providerprofile"))
        self.client = Client()
        self.preview_url = reverse(
            "admin:services_providerprofile_preview", args=(self.profile.pk,)
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.private_media, ignore_errors=True)

    @staticmethod
    def image_upload():
        rendered = BytesIO()
        Image.new("RGB", (640, 480), "#d9982f").save(rendered, format="JPEG")
        return SimpleUploadedFile("lucrare.jpg", rendered.getvalue(), content_type="image/jpeg")

    def test_staff_viewer_sees_current_account_content_without_creating_workflow_state(self):
        self.client.force_login(self.viewer)
        scope_count = ProviderPublicationScope.objects.count()
        submission_count = ProviderPublicationSubmission.objects.count()
        subscription_count = ProviderSubscription.objects.count()
        subscription_event_count = ProviderSubscriptionEvent.objects.count()
        response = self.client.get(self.preview_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Previzualizare administrativă")
        self.assertContains(response, "Atelier Test Aproape")
        self.assertContains(response, "owner@example.test")
        self.assertContains(response, "Construcții &amp; renovări")
        self.assertContains(response, "Iași — Iași")
        self.assertContains(response, "Renovare interioară")
        self.assertContains(response, "Disponibilitate limitată")
        self.assertContains(response, "Contact preferat")
        self.assertContains(response, "Strada Atelierului 12, Iași")
        self.assertEqual(ProviderPublicationScope.objects.count(), scope_count)
        self.assertEqual(ProviderPublicationSubmission.objects.count(), submission_count)
        self.assertEqual(ProviderSubscription.objects.count(), subscription_count)
        self.assertEqual(ProviderSubscriptionEvent.objects.count(), subscription_event_count)
        self.assertContains(response, "Abonament de test")
        self.assertContains(response, "nu are permisiunea separată")

    def test_authorized_staff_can_activate_and_deactivate_a_test_subscription(self):
        """The preview POST uses revisioned services and records both decisions."""

        self.viewer.user_permissions.add(
            Permission.objects.get(codename="manage_provider_subscription")
        )
        self.client.force_login(self.viewer)
        activated = self.client.post(
            self.preview_url,
            {
                "workflow_action": "subscription",
                "action": "activate",
                "expected_revision": "0",
                "internal_note": "Activare manuală pentru verificarea profilului.",
                "acknowledgement": "on",
            },
            follow=True,
        )
        self.assertEqual(activated.status_code, 200)
        self.assertContains(activated, "a fost activat sau prelungit")
        state = provider_subscription_state(self.profile)
        self.assertTrue(state.is_active)
        self.assertEqual(state.revision, 1)

        deactivated = self.client.post(
            self.preview_url,
            {
                "workflow_action": "subscription",
                "action": "deactivate",
                "expected_revision": "1",
                "internal_note": "Dezactivare manuală pentru verificarea profilului.",
                "acknowledgement": "on",
            },
            follow=True,
        )
        self.assertEqual(deactivated.status_code, 200)
        self.assertContains(deactivated, "a fost dezactivat")
        self.assertEqual(provider_subscription_state(self.profile).code, "inactive")
        self.assertEqual(
            list(ProviderSubscriptionEvent.objects.values_list("action", flat=True)),
            ["activate", "deactivate"],
        )

    def test_subscription_post_requires_the_dedicated_permission(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            self.preview_url,
            {
                "workflow_action": "subscription",
                "action": "activate",
                "expected_revision": "0",
                "internal_note": "Încercare fără permisiunea necesară.",
                "acknowledgement": "on",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ProviderSubscription.objects.exists())

    def test_profile_list_exposes_preview_action(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("admin:services_providerprofile_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Conturi furnizori")
        self.assertContains(response, self.preview_url)
        self.assertContains(response, "Previzualizează")

    def test_staff_without_profile_view_permission_is_denied(self):
        User = get_user_model()
        staff = User.objects.create_user(
            username="staff-without-profile-view",
            password="preview-test-password",
            is_active=True,
            is_staff=True,
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.preview_url).status_code, 403)

    def test_anonymous_user_is_redirected_to_admin_login(self):
        response = self.client.get(self.preview_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_profile_viewer_can_load_private_preview_image(self):
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("services:provider_portfolio_image", args=(self.portfolio_item.asset.opaque_id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
