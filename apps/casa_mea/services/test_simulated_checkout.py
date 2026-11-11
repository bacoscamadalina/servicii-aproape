"""Contracts for the temporary zero-payment subscription simulation."""

from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ProviderSubscription, ProviderSubscriptionEvent
from .provider_subscriptions import SIMULATED_CHECKOUT_POLICY_VERSION
from .test_provider_offerings import ProviderOfferingFixtureMixin


@override_settings(SIMULATED_CHECKOUT_ENABLED=True, READ_ONLY_PREVIEW=False)
class ProviderSimulatedCheckoutTests(ProviderOfferingFixtureMixin, TestCase):
    """Keep fake checkout explicit, owner-only, idempotent and payment-data free."""

    def setUp(self):
        self.create_fixture()
        self.client.force_login(self.owner)
        self.checkout_url = reverse("services:provider_simulated_checkout")
        self.success_url = reverse("services:provider_simulated_checkout_success")

    def test_checkout_requires_an_authenticated_active_owner(self):
        anonymous = Client().get(self.checkout_url)
        self.assertRedirects(
            anonymous,
            f"{reverse('services:provider_login')}?next={self.checkout_url}",
        )

        self.membership.state = self.membership.State.REVOKED
        self.membership.revoked_at = timezone.now()
        self.membership.save(update_fields=("state", "revoked_at"))
        self.assertEqual(self.client.get(self.checkout_url).status_code, 403)

    def test_login_returns_to_checkout_and_rejects_external_next_url(self):
        self.owner.set_password("Demo-checkout-2026!")
        self.owner.save(update_fields=("password",))
        self.client.logout()

        returned = self.client.post(
            reverse("services:provider_login"),
            {
                "email": self.owner.email,
                "password": "Demo-checkout-2026!",
                "next": self.checkout_url,
            },
        )
        self.assertRedirects(returned, self.checkout_url)

        self.client.logout()
        external = self.client.post(
            reverse("services:provider_login"),
            {
                "email": self.owner.email,
                "password": "Demo-checkout-2026!",
                "next": "https://example.invalid/steal-session",
            },
        )
        self.assertRedirects(external, reverse("services:provider_dashboard"))

    @override_settings(SIMULATED_CHECKOUT_ENABLED=False)
    def test_disabled_checkout_is_not_exposed(self):
        self.assertEqual(self.client.get(self.checkout_url).status_code, 404)

    @override_settings(READ_ONLY_PREVIEW=True)
    def test_read_only_preview_never_exposes_checkout(self):
        self.assertEqual(self.client.get(self.checkout_url).status_code, 404)

    def test_get_is_private_read_only_and_collects_no_financial_fields(self):
        response = self.client.get(self.checkout_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, noarchive")
        self.assertEqual(response.headers["Cache-Control"], "max-age=0, no-cache, no-store, must-revalidate, private")
        self.assertContains(response, "Simulare fără plată.")
        self.assertContains(response, "•••• 4242")
        self.assertNotContains(response, 'name="card_number"')
        self.assertNotContains(response, 'name="cvv"')
        self.assertFalse(ProviderSubscription.objects.exists())
        self.assertFalse(ProviderSubscriptionEvent.objects.exists())

    def test_explicit_confirmation_activates_exactly_one_demo_period(self):
        response = self.client.post(
            self.checkout_url,
            {"expected_revision": 0, "acknowledgement": "on"},
        )

        self.assertRedirects(response, self.success_url)
        subscription = ProviderSubscription.objects.get(profile=self.profile)
        self.assertEqual(subscription.status, ProviderSubscription.Status.ACTIVE)
        self.assertAlmostEqual(
            subscription.period_ends_at - subscription.period_started_at,
            timedelta(days=30),
        )
        event = ProviderSubscriptionEvent.objects.get(subscription=subscription)
        self.assertEqual(event.policy_version, SIMULATED_CHECKOUT_POLICY_VERSION)
        self.assertEqual(event.actor, self.owner)
        self.assertIn("nicio plată", event.internal_note)

        original_end = subscription.period_ends_at
        repeated = self.client.post(
            self.checkout_url,
            {"expected_revision": 0, "acknowledgement": "on"},
        )
        self.assertRedirects(repeated, self.success_url)
        subscription.refresh_from_db()
        self.assertEqual(subscription.period_ends_at, original_end)
        self.assertEqual(subscription.events.count(), 1)

    def test_confirmation_is_required_and_success_needs_a_demo_event(self):
        missing_confirmation = self.client.post(
            self.checkout_url,
            {"expected_revision": 0},
        )
        self.assertEqual(missing_confirmation.status_code, 200)
        self.assertContains(missing_confirmation, "Acest câmp este obligatoriu")
        self.assertFalse(ProviderSubscription.objects.exists())

        now = timezone.now()
        ProviderSubscription.objects.create(
            profile=self.profile,
            status=ProviderSubscription.Status.ACTIVE,
            period_started_at=now,
            period_ends_at=now + timedelta(days=30),
        )
        self.assertRedirects(
            self.client.get(self.success_url),
            reverse("services:provider_dashboard"),
        )

    def test_success_page_states_that_no_payment_or_invoice_exists(self):
        self.client.post(
            self.checkout_url,
            {"expected_revision": 0, "acknowledgement": "on"},
        )

        response = self.client.get(self.success_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plată procesată")
        self.assertContains(response, "nu o chitanță și nu o factură")
        self.assertContains(response, self.profile.display_name)

    def test_public_plan_links_to_simulation_only_while_enabled(self):
        plan = self.client.get(reverse("services:subscription_plan"))
        self.assertContains(plan, self.checkout_url)
        self.assertContains(plan, "Simulare fără card")

        with self.settings(SIMULATED_CHECKOUT_ENABLED=False):
            disabled = self.client.get(reverse("services:subscription_plan"))
        self.assertNotContains(disabled, self.checkout_url)
        self.assertContains(disabled, "Începe revendicarea")
