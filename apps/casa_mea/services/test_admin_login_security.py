"""Security tests for the shared Django Admin authentication boundary."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import AccountLoginThrottle
from .provider_access import claim_account_login_attempt


class AdminLoginSecurityTests(TestCase):
    """Keep administrator login budgets durable, private, and scope-isolated."""

    password = "Admin-pass-2026!"

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="OperationsAdmin",
            email="operations@example.invalid",
            password=self.password,
        )
        self.login_url = reverse("admin:login")

    def test_admin_login_attempts_share_one_persistent_budget(self):
        """Cache resets and username casing cannot bypass the database limit."""

        for attempt in range(5):
            response = self.client.post(
                self.login_url,
                {
                    "username": "OPERATIONSADMIN" if attempt % 2 else "operationsadmin",
                    "password": "Wrong-admin-pass-2026!",
                    "next": reverse("admin:index"),
                },
            )
            self.assertEqual(response.status_code, 200)
            cache.clear()

        blocked = self.client.post(
            self.login_url,
            {
                "username": "operationsadmin",
                "password": "Wrong-admin-pass-2026!",
                "next": reverse("admin:index"),
            },
        )
        self.assertContains(blocked, "Prea multe încercări")
        throttle = AccountLoginThrottle.objects.get()
        self.assertEqual(throttle.attempt_count, 5)
        self.assertNotIn("operationsadmin", throttle.key_digest)

    def test_successful_admin_login_clears_attempt_budget(self):
        """A successful administrator login starts with a fresh failure budget."""

        self.assertTrue(
            claim_account_login_attempt(
                scope="admin", identifier=self.admin.username
            )
        )
        self.assertTrue(AccountLoginThrottle.objects.exists())

        response = self.client.post(
            self.login_url,
            {
                "username": self.admin.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )

        self.assertRedirects(response, reverse("admin:index"))
        self.assertFalse(AccountLoginThrottle.objects.exists())

    def test_provider_budget_does_not_block_admin_login(self):
        """Domain separation prevents provider failures from locking administrators."""

        for _attempt in range(5):
            self.assertTrue(
                claim_account_login_attempt(
                    scope="provider", identifier=self.admin.username
                )
            )

        response = self.client.post(
            self.login_url,
            {
                "username": self.admin.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
        )

        self.assertRedirects(response, reverse("admin:index"))
        provider_throttle = AccountLoginThrottle.objects.get()
        self.assertEqual(provider_throttle.attempt_count, 5)
