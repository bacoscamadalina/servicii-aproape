"""Contracts for audited category presentation and intake policy."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .catalog import CATEGORIES
from .forms import ProviderRegistrationForm
from .models import ServiceCategoryPolicy, ServiceCategoryPolicyEvent
from .service_category_policies import (
    CATEGORY_POLICY_ACKNOWLEDGEMENT,
    editable_provider_service_slugs,
    new_provider_service_categories,
    publicly_discoverable_service_categories,
    update_service_category_policy,
)


class ServiceCategoryPolicyTests(TestCase):
    """Keep operational controls complete, audited and non-destructive."""

    def setUp(self):
        self.manager = get_user_model().objects.create_user(
            username="category-manager",
            email="category-manager@example.test",
            is_staff=True,
        )
        self.manager.user_permissions.add(
            Permission.objects.get(codename="manage_service_category_policy"),
            Permission.objects.get(codename="view_servicecategorypolicy"),
        )

    def update(self, category="electricieni", **overrides):
        policy = ServiceCategoryPolicy.objects.get(category=category)
        values = {
            "category": category,
            "state": ServiceCategoryPolicy.State.INTAKE_PAUSED,
            "display_order": policy.display_order,
            "expected_revision": policy.revision,
            "reason": "Oprire temporară pentru verificarea capacității.",
            "actor": self.manager,
            "acknowledgement": CATEGORY_POLICY_ACKNOWLEDGEMENT,
        }
        values.update(overrides)
        return update_service_category_policy(**values)

    def test_migration_seeds_exactly_one_ordered_policy_for_every_category(self):
        self.assertEqual(
            list(ServiceCategoryPolicy.objects.values_list("category", flat=True)),
            [slug for slug, _label, _description in CATEGORIES],
        )
        self.assertEqual(ServiceCategoryPolicy.objects.count(), len(CATEGORIES))

    def test_paused_category_remains_discoverable_but_rejects_new_intake(self):
        self.update()

        self.assertIn(
            "electricieni",
            {record.slug for record in publicly_discoverable_service_categories()},
        )
        self.assertNotIn(
            "electricieni",
            {record.slug for record in new_provider_service_categories()},
        )
        form = ProviderRegistrationForm(
            category_choices=tuple(
                (record.slug, record.label)
                for record in new_provider_service_categories()
            )
        )
        self.assertNotIn(
            "electricieni", dict(form.fields["requested_category"].choices)
        )

    def test_hidden_category_leaves_public_discovery_without_deleting_policy(self):
        self.update(state=ServiceCategoryPolicy.State.HIDDEN)

        response = self.client.get("/")
        local_page = self.client.get(
            "/servicii/electricieni/iasi/iasi-95079/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, ">Electricitate<")
        self.assertEqual(local_page.status_code, 404)
        self.assertTrue(
            ServiceCategoryPolicy.objects.filter(category="electricieni").exists()
        )

    def test_existing_service_remains_editable_after_intake_is_paused(self):
        self.update()

        editable = editable_provider_service_slugs(
            authorized_categories={"constructii", "electricieni"},
            current_services={"electricieni"},
        )

        self.assertEqual(editable, frozenset({"constructii", "electricieni"}))

    def test_update_appends_event_and_rejects_stale_revision(self):
        policy, changed = self.update(display_order=5)

        self.assertTrue(changed)
        self.assertEqual(policy.revision, 1)
        event = ServiceCategoryPolicyEvent.objects.get()
        self.assertEqual(event.previous_state, ServiceCategoryPolicy.State.ACTIVE)
        self.assertEqual(event.new_state, ServiceCategoryPolicy.State.INTAKE_PAUSED)
        self.assertEqual(event.previous_order, 20)
        self.assertEqual(event.new_order, 5)
        self.assertEqual(event.actor, self.manager)

        with self.assertRaisesMessage(ValueError, "modificată între timp"):
            self.update(expected_revision=0)
        self.assertEqual(ServiceCategoryPolicyEvent.objects.count(), 1)

    def test_update_requires_permission_and_explicit_boundary_confirmation(self):
        unauthorized = get_user_model().objects.create_user(
            username="ordinary-staff", is_staff=True
        )
        policy = ServiceCategoryPolicy.objects.get(category="electricieni")

        with self.assertRaises(PermissionError):
            update_service_category_policy(
                category=policy.category,
                state=ServiceCategoryPolicy.State.HIDDEN,
                display_order=policy.display_order,
                expected_revision=policy.revision,
                reason="Motiv operațional suficient de explicit.",
                actor=unauthorized,
                acknowledgement=CATEGORY_POLICY_ACKNOWLEDGEMENT,
            )
        with self.assertRaisesMessage(ValueError, "Confirmarea"):
            self.update(acknowledgement="")

    def test_admin_manage_page_is_get_inert_and_post_is_audited(self):
        self.client.force_login(self.manager)
        url = reverse("admin:services_servicecategorypolicy_manage")

        landing = self.client.get(url)

        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, "Disponibilitatea serviciilor")
        self.assertContains(landing, "nu modifică date CAEN")
        self.assertContains(landing, 'name="category-policy"', count=7)
        self.assertEqual(ServiceCategoryPolicyEvent.objects.count(), 0)

        policy = ServiceCategoryPolicy.objects.get(category="electricieni")
        invalid = self.client.post(
            url,
            {
                "category": policy.category,
                "state": ServiceCategoryPolicy.State.INTAKE_PAUSED,
                "display_order": policy.display_order,
                "expected_revision": policy.revision,
                "reason": "",
            },
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertIn(
            b'<details class="category-policy__row" name="category-policy" open>',
            invalid.content,
        )
        self.assertEqual(ServiceCategoryPolicyEvent.objects.count(), 0)

        response = self.client.post(
            url,
            {
                "category": policy.category,
                "state": ServiceCategoryPolicy.State.INTAKE_PAUSED,
                "display_order": policy.display_order,
                "expected_revision": policy.revision,
                "reason": "Oprire temporară pentru verificarea capacității.",
                "acknowledgement": "on",
            },
        )

        self.assertRedirects(response, url)
        policy.refresh_from_db()
        self.assertEqual(policy.state, ServiceCategoryPolicy.State.INTAKE_PAUSED)
        self.assertEqual(ServiceCategoryPolicyEvent.objects.count(), 1)

    def test_admin_manage_page_rejects_staff_without_policy_permission(self):
        viewer = get_user_model().objects.create_user(
            username="category-viewer", is_staff=True
        )
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_servicecategorypolicy")
        )
        self.client.force_login(viewer)

        response = self.client.get(
            reverse("admin:services_servicecategorypolicy_manage")
        )

        self.assertEqual(response.status_code, 403)
