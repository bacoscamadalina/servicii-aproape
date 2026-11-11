"""Customer registration, authentication, recovery, and portal authorization contracts."""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from .models import CustomerAccount
from .provider_access import claim_password_reset_send_slot


class CustomerAccountTests(TestCase):
    def registration_payload(self, **changes):
        payload = {
            "last_name": "Popescu",
            "first_name": "Maria",
            "username": "maria.popescu",
            "email": "MARIA@example.test",
            "password1": "CasaMea-Sigura-2026!",
            "password2": "CasaMea-Sigura-2026!",
            "privacy_consent": "on",
            "website": "",
        }
        return {**payload, **changes}

    def test_registration_creates_active_account_without_email_confirmation(self):
        response = self.client.post(
            reverse("services:customer_register"), self.registration_payload()
        )

        self.assertRedirects(response, reverse("services:customer_dashboard"))
        account = CustomerAccount.objects.select_related("user").get()
        self.assertTrue(account.user.is_active)
        self.assertEqual(account.normalized_email, "maria@example.test")
        self.assertTrue(account.user.check_password("CasaMea-Sigura-2026!"))
        self.assertNotIn("password", self.client.session)

    def test_registration_rejects_password_mismatch_and_case_insensitive_identity(self):
        get_user_model().objects.create_user(
            username="Existing", email="existing@example.test", password="Unused-Safe-2026!"
        )
        mismatch = self.client.post(
            reverse("services:customer_register"),
            self.registration_payload(password2="Alta-parola-2026!"),
        )
        self.assertContains(mismatch, "Parolele nu coincid")
        collision = self.client.post(
            reverse("services:customer_register"),
            self.registration_payload(username="EXISTING", email="nou@example.test"),
        )
        self.assertContains(collision, "de utilizator este deja folosit")
        self.assertFalse(CustomerAccount.objects.exists())

    def test_login_is_customer_only_and_dashboard_requires_authentication(self):
        self.assertRedirects(
            self.client.get(reverse("services:customer_dashboard")),
            f"{reverse('services:customer_login')}?next={reverse('services:customer_dashboard')}",
        )
        self.client.post(reverse("services:customer_register"), self.registration_payload())
        self.client.post(reverse("services:customer_logout"))
        response = self.client.post(
            reverse("services:customer_login"),
            {"email": "maria@example.test", "password": "CasaMea-Sigura-2026!"},
        )
        self.assertRedirects(response, reverse("services:customer_dashboard"))
        dashboard = self.client.get(reverse("services:customer_dashboard"))
        self.assertContains(dashboard, "Proiectele mele")
        self.assertContains(
            dashboard,
            reverse("services:provider_lead_batch_create"),
            count=1,
        )

    def test_provider_account_cannot_enter_customer_portal(self):
        provider = get_user_model().objects.create_user(
            username="provider", email="provider@example.test", password="Provider-Safe-2026!"
        )
        self.client.force_login(provider)
        response = self.client.get(reverse("services:customer_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("services:customer_login"), response.url)

    def test_customer_can_reset_password_and_reuse_login_only_with_new_password(self):
        """A single-use customer link changes the credential without changing ownership."""

        self.client.post(reverse("services:customer_register"), self.registration_payload())
        self.client.post(reverse("services:customer_logout"))
        response = self.client.post(
            reverse("services:customer_password_reset"), {"email": "MARIA@example.test"}
        )
        self.assertRedirects(response, reverse("services:customer_password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        reset_path = re.search(r"http://testserver([^\s]+)", mail.outbox[0].body).group(1)
        self.assertIn("/client/reseteaza-parola/", reset_path)
        confirm = self.client.get(reset_path, follow=True)
        self.assertContains(confirm, "Alege o parolă nouă")
        changed = self.client.post(
            confirm.redirect_chain[-1][0],
            {"new_password1": "Noua-Parola-Sigura-2026!", "new_password2": "Noua-Parola-Sigura-2026!"},
        )
        self.assertRedirects(changed, reverse("services:customer_password_reset_complete"))
        self.assertContains(self.client.get(reset_path, follow=True), "Linkul nu mai este activ")
        user = CustomerAccount.objects.get().user
        self.assertTrue(user.check_password("Noua-Parola-Sigura-2026!"))
        self.assertFalse(user.check_password("CasaMea-Sigura-2026!"))
        login = self.client.post(reverse("services:customer_login"), {
            "email": "maria@example.test", "password": "Noua-Parola-Sigura-2026!",
        })
        self.assertRedirects(login, reverse("services:customer_dashboard"))

    def test_customer_reset_does_not_disclose_unknown_or_provider_accounts(self):
        """Both non-customer addresses get the same response and no e-mail."""

        get_user_model().objects.create_user(
            username="provider", email="provider@example.test", password="Provider-Safe-2026!"
        )
        for email in ("provider@example.test", "unknown@example.test"):
            response = self.client.post(reverse("services:customer_password_reset"), {"email": email})
            self.assertRedirects(response, reverse("services:customer_password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_customer_reset_is_bounded_and_link_fails_when_role_is_lost(self):
        """Sending is bounded and a deactivated account cannot consume its old link."""

        self.client.post(reverse("services:customer_register"), self.registration_payload())
        self.client.post(reverse("services:customer_logout"))
        for _ in range(4):
            self.client.post(
                reverse("services:customer_password_reset"),
                {"email": "maria@example.test"}, REMOTE_ADDR="192.0.2.88",
            )
        self.assertEqual(len(mail.outbox), 3)
        reset_path = re.search(r"http://testserver([^\s]+)", mail.outbox[0].body).group(1)
        account = CustomerAccount.objects.get()
        account.user.is_active = False
        account.user.save(update_fields=("is_active",))
        self.assertContains(self.client.get(reset_path, follow=True), "Linkul nu mai este activ")

    def test_reset_send_budgets_are_separate_by_account_role(self):
        """Requests against one portal cannot exhaust the other portal's budget."""

        for _ in range(3):
            self.assertTrue(claim_password_reset_send_slot(
                email="shared@example.test", client_address="192.0.2.10", scope="customer",
            ))
        self.assertFalse(claim_password_reset_send_slot(
            email="shared@example.test", client_address="192.0.2.10", scope="customer",
        ))
        self.assertTrue(claim_password_reset_send_slot(
            email="shared@example.test", client_address="192.0.2.10", scope="provider",
        ))

    def test_authenticated_customer_can_change_password_and_keep_only_current_session(self):
        """Current-password proof rotates the hash and invalidates other sessions."""

        self.client.post(reverse("services:customer_register"), self.registration_payload())
        user = CustomerAccount.objects.get().user
        other_client = Client()
        other_client.force_login(user)
        change_url = reverse("services:customer_password_change")
        self.assertContains(self.client.get(reverse("services:customer_dashboard")), change_url)

        changed = self.client.post(change_url, {
            "old_password": "CasaMea-Sigura-2026!",
            "new_password1": "Noua-Parola-Sigura-2026!",
            "new_password2": "Noua-Parola-Sigura-2026!",
        }, follow=True)
        self.assertRedirects(changed, reverse("services:customer_dashboard"))
        self.assertContains(changed, "Celelalte sesiuni ale contului au fost închise")
        self.assertEqual(self.client.get(reverse("services:customer_dashboard")).status_code, 200)
        self.assertRedirects(
            other_client.get(reverse("services:customer_dashboard")),
            f"{reverse('services:customer_login')}?next={reverse('services:customer_dashboard')}",
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password("Noua-Parola-Sigura-2026!"))

    def test_password_change_rejects_wrong_password_mismatch_and_non_customer(self):
        """A session alone never authorizes a credential update."""

        change_url = reverse("services:customer_password_change")
        self.assertRedirects(
            self.client.get(change_url),
            f"{reverse('services:customer_login')}?next={change_url}",
        )
        self.client.post(reverse("services:customer_register"), self.registration_payload())
        user = CustomerAccount.objects.get().user
        for payload, error in (
            ({"old_password": "Gresita-2026!", "new_password1": "Noua-Parola-Sigura-2026!", "new_password2": "Noua-Parola-Sigura-2026!"}, "Parola curentă nu este corectă"),
            ({"old_password": "CasaMea-Sigura-2026!", "new_password1": "Noua-Parola-Sigura-2026!", "new_password2": "Alta-Parola-Sigura-2026!"}, "Cele două parole nu corespund"),
        ):
            self.assertContains(self.client.post(change_url, payload), error)
        user.refresh_from_db()
        self.assertTrue(user.check_password("CasaMea-Sigura-2026!"))

        self.client.post(reverse("services:customer_logout"))
        provider = get_user_model().objects.create_user(
            username="provider", email="provider@example.test", password="Provider-Safe-2026!"
        )
        self.client.force_login(provider)
        self.assertRedirects(
            self.client.get(change_url),
            f"{reverse('services:customer_login')}?next={change_url}",
        )
