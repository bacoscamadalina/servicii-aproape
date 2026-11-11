"""Security and lifecycle tests for provider approval and draft-profile access."""

from datetime import timedelta
import re
from threading import Barrier, Thread

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AccountLoginThrottle,
    BusinessIdentity,
    ProviderAccountInvitation,
    ProviderClaimRequest,
    ProviderMembership,
    ProviderPasswordResetThrottle,
    ProviderProfile,
)
from .provider_access import (
    REVIEW_ACKNOWLEDGEMENT,
    approve_provider_claim,
    claim_account_login_attempt,
    claim_password_reset_send_slot,
    clear_account_login_attempts,
    deliver_provider_invitation_email,
    reject_provider_claim,
    rotate_provider_invitation,
)
from .test_representation_evidence import create_representation_evidence


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ProviderAccessTests(TestCase):
    """Exercise the full approval → activation → private draft path."""

    def setUp(self):
        self.business = BusinessIdentity.objects.create(registration_number="J27/55/2020")
        self.claim = ProviderClaimRequest.objects.create(
            business=self.business,
            legal_name_at_request="ATELIER TEST S.R.L.",
            contact_name="Ana Popescu",
            role="administrator",
            email="ana@example.ro",
            status=ProviderClaimRequest.Status.REVIEW_PENDING,
            token_digest="a" * 64,
            token_expires_at=timezone.now() + timedelta(hours=1),
            email_verified_at=timezone.now(),
            email_delivery_state=ProviderClaimRequest.DeliveryState.SENT,
            privacy_notice_version="2026-08-25",
            consented_at=timezone.now(),
        )
        create_representation_evidence(claim=self.claim)
        self.reviewer = get_user_model().objects.create_user(
            username="reviewer",
            email="reviewer@serviciiaproape.ro",
            password="Review-pass-2026!",
            is_staff=True,
        )
        self.reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_claim")
        )

    def approve(self):
        return approve_provider_claim(
            claim_id=self.claim.pk,
            reviewer=self.reviewer,
            review_note="Mandatul de reprezentare a fost verificat offline.",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )

    def approve_and_deliver(self):
        profile, invitation, token = self.approve()
        delivered = deliver_provider_invitation_email(
            invitation=ProviderAccountInvitation.objects.select_related(
                "membership__user", "membership__profile"
            ).get(pk=invitation.pk),
            activation_url=f"http://testserver{reverse('services:provider_activate', args=(token,))}",
        )
        self.assertTrue(delivered)
        return profile, invitation, token

    def test_approval_creates_one_inactive_owner_and_hashed_invitation(self):
        profile, invitation, token = self.approve_and_deliver()
        self.claim.refresh_from_db()
        invitation.refresh_from_db()
        membership = invitation.membership

        self.assertEqual(self.claim.status, ProviderClaimRequest.Status.APPROVED)
        self.assertTrue(self.claim.approval_policy_version)
        self.assertEqual(profile.business, self.business)
        self.assertEqual(membership.state, ProviderMembership.State.INVITED)
        self.assertFalse(membership.user.is_active)
        self.assertFalse(membership.user.has_usable_password())
        self.assertNotEqual(invitation.token_digest, token)
        self.assertNotIn(token, invitation.token_digest)
        self.assertEqual(invitation.delivery_state, invitation.DeliveryState.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(token, mail.outbox[0].body)

    def test_new_claim_approval_activates_the_selected_email_and_password(self):
        password = "Provider-pass-2026!"
        ProviderClaimRequest.objects.filter(pk=self.claim.pk).update(
            account_first_name="Ana",
            account_last_name="Popescu",
            account_username="ana.popescu",
            password_hash=make_password(password),
            credentials_supplied_at=timezone.now(),
            email_verified_at=None,
        )

        profile, invitation, token = self.approve()

        self.assertIsNone(invitation)
        self.assertIsNone(token)
        self.assertEqual(len(mail.outbox), 0)
        user = get_user_model().objects.get(username="ana.popescu")
        membership = ProviderMembership.objects.get(profile=profile, user=user)
        self.assertTrue(user.is_active)
        self.assertEqual(user.first_name, "Ana")
        self.assertEqual(user.last_name, "Popescu")
        self.assertTrue(user.check_password(password))
        self.assertEqual(membership.state, ProviderMembership.State.ACTIVE)
        self.assertIsNotNone(membership.activated_at)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.password_hash, "")

        response = self.client.post(
            reverse("services:provider_login"),
            {"email": "ANA@EXAMPLE.RO", "password": password},
        )
        self.assertRedirects(
            response,
            reverse("services:provider_dashboard"),
            fetch_redirect_response=False,
        )

    def test_approval_refuses_unverified_self_review_collision_and_missing_permission(self):
        self.claim.status = ProviderClaimRequest.Status.EMAIL_PENDING
        self.claim.email_verified_at = None
        self.claim.save(update_fields=("status", "email_verified_at"))
        with self.assertRaises(ValueError):
            self.approve()
        self.assertFalse(ProviderProfile.objects.exists())

        self.claim.status = ProviderClaimRequest.Status.REVIEW_PENDING
        self.claim.email_verified_at = timezone.now()
        self.claim.save(update_fields=("status", "email_verified_at"))
        self.reviewer.email = self.claim.email.upper()
        self.reviewer.save(update_fields=("email",))
        with self.assertRaises(ValueError):
            self.approve()

        self.reviewer.email = "reviewer@serviciiaproape.ro"
        self.reviewer.save(update_fields=("email",))
        get_user_model().objects.create_user(
            username="collision", email="ANA@EXAMPLE.RO", password="Unused-pass-2026!"
        )
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(get_user_model().objects.filter(email__iexact=self.claim.email).count(), 1)

        outsider = get_user_model().objects.create_user(
            username="outsider", password="Unused-pass-2026!", is_staff=True
        )
        with self.assertRaises(PermissionError):
            approve_provider_claim(
                claim_id=self.claim.pk,
                reviewer=outsider,
                review_note="Verificare administrativă documentată.",
                acknowledgement=REVIEW_ACKNOWLEDGEMENT,
            )
        self.assertFalse(ProviderProfile.objects.exists())

    def test_rejection_is_terminal_and_creates_no_provider_records(self):
        rejected = reject_provider_claim(
            claim_id=self.claim.pk,
            reviewer=self.reviewer,
            review_note="Documentele nu confirmă dreptul de reprezentare.",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        self.assertEqual(rejected.status, ProviderClaimRequest.Status.REJECTED)
        self.assertFalse(ProviderProfile.objects.exists())
        with self.assertRaises(ValueError):
            reject_provider_claim(
                claim_id=self.claim.pk,
                reviewer=self.reviewer,
                review_note="A doua decizie nu este permisă.",
                acknowledgement=REVIEW_ACKNOWLEDGEMENT,
            )

    def test_approval_requires_an_intact_representation_document(self):
        self.claim.representation_evidence.delete()
        with self.assertRaisesMessage(ValueError, "Dovada dreptului"):
            self.approve()
        self.assertFalse(ProviderProfile.objects.exists())

        evidence = create_representation_evidence(claim=self.claim)
        evidence.sha256 = "0" * 64
        evidence.save(update_fields=("sha256",))
        with self.assertRaisesMessage(ValueError, "Dovada dreptului"):
            self.approve()
        self.assertFalse(ProviderProfile.objects.exists())

    def test_activation_get_is_read_only_and_post_activates_exactly_once(self):
        profile, invitation, token = self.approve_and_deliver()
        url = reverse("services:provider_activate", args=(token,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
        self.assertFalse(invitation.membership.user.is_active)

        weak = self.client.post(
            url, {"new_password1": "123", "new_password2": "123"}
        )
        self.assertEqual(weak.status_code, 200)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)

        session_before = self.client.session.session_key
        activated = self.client.post(
            url,
            {
                "new_password1": "Provider-pass-2026!",
                "new_password2": "Provider-pass-2026!",
            },
            follow=True,
        )
        self.assertRedirects(activated, reverse("services:provider_dashboard"))
        invitation.refresh_from_db()
        invitation.membership.refresh_from_db()
        invitation.membership.user.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(invitation.membership.state, ProviderMembership.State.ACTIVE)
        self.assertTrue(invitation.membership.user.is_active)
        self.assertNotEqual(self.client.session.session_key, session_before)
        self.assertContains(activated, profile.display_name)
        self.assertEqual(self.client.get(url).status_code, 410)

    def test_expired_invitation_fails_closed(self):
        _profile, invitation, token = self.approve_and_deliver()
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=("expires_at",))
        self.assertEqual(
            self.client.get(reverse("services:provider_activate", args=(token,))).status_code,
            410,
        )

    def test_failed_delivery_can_rotate_without_duplicate_account_records(self):
        _profile, invitation, old_token = self.approve()
        invitation.delivery_state = invitation.DeliveryState.FAILED
        invitation.save(update_fields=("delivery_state",))
        rotated, new_token = rotate_provider_invitation(
            claim_id=self.claim.pk,
            reviewer=self.reviewer,
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(rotated.delivery_state, rotated.DeliveryState.PENDING)
        self.assertEqual(ProviderProfile.objects.count(), 1)
        self.assertEqual(ProviderMembership.objects.count(), 1)
        self.assertEqual(ProviderAccountInvitation.objects.count(), 1)
        self.assertEqual(
            self.client.get(
                reverse("services:provider_activate", args=(old_token,))
            ).status_code,
            410,
        )

    def test_dashboard_whitelists_draft_fields_and_requires_active_membership(self):
        profile, _invitation, token = self.approve_and_deliver()
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {
                "new_password1": "Provider-pass-2026!",
                "new_password2": "Provider-pass-2026!",
            },
        )
        response = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "display_name": "Atelierul Anei",
                "description": "Mobilă realizată la comandă.",
                "public_phone": "0712 000 000",
                "public_email": "contact@atelier.ro",
                "website": "https://atelier.ro",
                "availability": ProviderProfile.Availability.ACCEPTING,
                "contact_preference": ProviderProfile.ContactPreference.PHONE,
                "state": ProviderProfile.State.DISABLED,
                "business": 999999,
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("services:provider_dashboard"))
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Atelierul Anei")
        self.assertEqual(profile.availability, ProviderProfile.Availability.ACCEPTING)
        self.assertEqual(
            profile.contact_preference, ProviderProfile.ContactPreference.PHONE
        )
        self.assertEqual(profile.state, ProviderProfile.State.DRAFT)
        self.assertEqual(profile.business, self.business)

        membership = profile.memberships.get()
        membership.state = ProviderMembership.State.REVOKED
        membership.revoked_at = timezone.now()
        membership.save(update_fields=("state", "revoked_at"))
        self.assertEqual(self.client.get(reverse("services:provider_dashboard")).status_code, 403)

    def test_dashboard_rejects_a_preferred_contact_method_without_its_value(self):
        """Do not persist a preference that would lead visitors to an empty contact."""

        profile, _invitation, token = self.approve_and_deliver()
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {
                "new_password1": "Provider-pass-2026!",
                "new_password2": "Provider-pass-2026!",
            },
        )

        response = self.client.post(
            reverse("services:provider_dashboard"),
            {
                "action": "save_profile",
                "display_name": "Atelierul Anei",
                "description": "Mobilă realizată la comandă.",
                "public_phone": "",
                "public_email": "contact@atelier.ro",
                "website": "https://atelier.ro",
                "availability": ProviderProfile.Availability.ACCEPTING,
                "contact_preference": ProviderProfile.ContactPreference.PHONE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Completează această metodă înainte să o alegi ca preferată.",
        )
        profile.refresh_from_db()
        self.assertEqual(profile.contact_preference, ProviderProfile.ContactPreference.ANY)
        self.assertEqual(profile.display_name, "ATELIER TEST S.R.L.")

    def test_provider_can_log_out_and_return_with_email_and_password(self):
        _profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        self.assertEqual(self.client.get(reverse("services:provider_logout")).status_code, 404)
        self.client.post(reverse("services:provider_logout"))
        response = self.client.post(
            reverse("services:provider_login"),
            {"email": self.claim.email.upper(), "password": password},
        )
        self.assertRedirects(response, reverse("services:provider_dashboard"))

    def test_provider_login_attempts_use_one_shared_persistent_budget(self):
        """Cache resets and address casing cannot bypass the database-backed limit."""

        login_url = reverse("services:provider_login")
        for attempt in range(5):
            response = self.client.post(
                login_url,
                {
                    "email": "UNKNOWN@example.ro" if attempt % 2 else "unknown@example.ro",
                    "password": "Wrong-provider-pass-2026!",
                },
            )
            self.assertContains(response, "E-mailul sau parola nu sunt corecte")
            cache.clear()

        blocked = self.client.post(
            login_url,
            {"email": "unknown@example.ro", "password": "Wrong-provider-pass-2026!"},
        )
        self.assertContains(blocked, "Prea multe încercări")
        throttle = AccountLoginThrottle.objects.get()
        self.assertEqual(throttle.attempt_count, 5)
        self.assertNotIn("unknown@example.ro", throttle.key_digest)

    def test_successful_provider_login_clears_shared_attempt_budget(self):
        """A legitimate successful login must start with a fresh failure budget."""

        _profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        self.client.post(reverse("services:provider_logout"))
        self.assertTrue(
            claim_account_login_attempt(scope="provider", identifier=self.claim.email)
        )
        self.assertTrue(AccountLoginThrottle.objects.exists())

        response = self.client.post(
            reverse("services:provider_login"),
            {"email": self.claim.email.upper(), "password": password},
        )
        self.assertRedirects(response, reverse("services:provider_dashboard"))
        self.assertFalse(AccountLoginThrottle.objects.exists())

    def test_login_throttle_resets_window_and_removes_only_expired_rows(self):
        """Window rollover and bounded retention cleanup preserve active budgets."""

        now = timezone.now()
        expired = AccountLoginThrottle.objects.create(
            key_digest="e" * 64,
            window_started_at=now - timedelta(hours=25),
            attempt_count=5,
        )
        active = AccountLoginThrottle.objects.create(
            key_digest="f" * 64,
            window_started_at=now - timedelta(minutes=14),
            attempt_count=2,
        )
        self.assertTrue(
            claim_account_login_attempt(
                scope="provider", identifier="rollover@example.ro"
            )
        )
        clear_account_login_attempts(
            scope="provider", identifier="rollover@example.ro"
        )
        self.assertFalse(AccountLoginThrottle.objects.filter(pk=expired.pk).exists())
        self.assertTrue(AccountLoginThrottle.objects.filter(pk=active.pk).exists())

    def test_provider_can_change_password_and_other_sessions_are_closed(self):
        """Keep the changing session while the password hash invalidates every other one."""

        _profile, _invitation, token = self.approve_and_deliver()
        old_password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": old_password, "new_password2": old_password},
        )
        other_client = Client()
        other_client.login(
            username=self.claim.email,
            password=old_password,
        )
        new_password = "Provider-changed-2026!"

        changed = self.client.post(
            reverse("services:provider_password_change"),
            {
                "old_password": old_password,
                "new_password1": new_password,
                "new_password2": new_password,
            },
            follow=True,
        )
        self.assertRedirects(changed, reverse("services:provider_dashboard"))
        self.assertContains(changed, "Celelalte sesiuni ale contului au fost închise")
        self.assertEqual(
            self.client.get(reverse("services:provider_dashboard")).status_code, 200
        )
        other_response = other_client.get(reverse("services:provider_dashboard"))
        self.assertRedirects(
            other_response,
            f"{reverse('services:provider_login')}?next={reverse('services:provider_dashboard')}",
        )

        self.client.post(reverse("services:provider_logout"))
        cache.clear()
        old_login = self.client.post(
            reverse("services:provider_login"),
            {"email": self.claim.email, "password": old_password},
        )
        self.assertEqual(old_login.status_code, 200)
        new_login = self.client.post(
            reverse("services:provider_login"),
            {"email": self.claim.email, "password": new_password},
        )
        self.assertRedirects(new_login, reverse("services:provider_dashboard"))

    def test_password_change_rejects_mismatched_new_passwords_without_mutation(self):
        """Keep the current credential and render an adjacent recovery error."""

        _profile, _invitation, token = self.approve_and_deliver()
        current_password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": current_password, "new_password2": current_password},
        )

        refused = self.client.post(
            reverse("services:provider_password_change"),
            {
                "old_password": current_password,
                "new_password1": "Provider-changed-2026!",
                "new_password2": "Provider-different-2026!",
            },
        )

        self.assertEqual(refused.status_code, 200)
        self.assertContains(refused, "Cele două parole nu corespund.")
        user = get_user_model().objects.get(email=self.claim.email)
        self.assertTrue(user.check_password(current_password))
        self.assertFalse(user.check_password("Provider-changed-2026!"))

    def test_password_change_requires_current_password_and_active_membership(self):
        """A live session alone cannot replace a password after proof or access fails."""

        change_url = reverse("services:provider_password_change")
        self.assertRedirects(
            self.client.get(change_url),
            f"{reverse('services:provider_login')}?next={change_url}",
        )
        profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        refused = self.client.post(
            change_url,
            {
                "old_password": "Parola-gresita-2026!",
                "new_password1": "Provider-changed-2026!",
                "new_password2": "Provider-changed-2026!",
            },
        )
        self.assertEqual(refused.status_code, 200)
        self.assertContains(refused, "Parola curentă nu este corectă")
        self.assertTrue(
            get_user_model().objects.get(email=self.claim.email).check_password(password)
        )

        membership = profile.memberships.get()
        membership.state = ProviderMembership.State.REVOKED
        membership.revoked_at = timezone.now()
        membership.save(update_fields=("state", "revoked_at"))
        self.assertEqual(
            self.client.get(change_url).status_code,
            403,
        )

    def test_active_provider_can_reset_password_with_a_single_use_link(self):
        """A reset changes only the credential and returns through provider login."""

        profile, _invitation, token = self.approve_and_deliver()
        old_password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": old_password, "new_password2": old_password},
        )
        self.client.post(reverse("services:provider_logout"))
        mail.outbox.clear()
        cache.clear()

        requested = self.client.post(
            reverse("services:provider_password_reset"),
            {"email": self.claim.email.upper()},
        )
        self.assertRedirects(
            requested, reverse("services:provider_password_reset_done")
        )
        self.assertEqual(len(mail.outbox), 1)
        reset_path = re.search(r"http://testserver([^\s]+)", mail.outbox[0].body).group(1)
        confirmation = self.client.get(reset_path, follow=True)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "Alege o parolă nouă")
        set_password_path = confirmation.request["PATH_INFO"]

        new_password = "Provider-reset-2026!"
        completed = self.client.post(
            set_password_path,
            {"new_password1": new_password, "new_password2": new_password},
            follow=True,
        )
        self.assertRedirects(
            completed, reverse("services:provider_password_reset_complete")
        )
        self.assertContains(completed, "Parola a fost schimbată")
        profile.refresh_from_db()
        self.assertEqual(profile.state, ProviderProfile.State.DRAFT)

        login_response = self.client.post(
            reverse("services:provider_login"),
            {"email": self.claim.email, "password": new_password},
        )
        self.assertRedirects(login_response, reverse("services:provider_dashboard"))
        self.client.post(reverse("services:provider_logout"))
        reused = self.client.get(reset_path, follow=True)
        self.assertContains(reused, "Linkul nu mai este activ")

    def test_password_reset_is_generic_and_excludes_revoked_or_unknown_accounts(self):
        """The public response must not reveal provider account state or existence."""

        profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        self.client.post(reverse("services:provider_logout"))
        membership = profile.memberships.get()
        membership.state = ProviderMembership.State.REVOKED
        membership.revoked_at = timezone.now()
        membership.save(update_fields=("state", "revoked_at"))
        mail.outbox.clear()
        cache.clear()

        for email in (self.claim.email, "necunoscut@example.ro"):
            response = self.client.post(
                reverse("services:provider_password_reset"), {"email": email}
            )
            self.assertRedirects(
                response, reverse("services:provider_password_reset_done")
            )
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_email_sends_are_bounded(self):
        """Repeated valid requests return identically but send at most three messages."""

        _profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        self.client.post(reverse("services:provider_logout"))
        mail.outbox.clear()
        cache.clear()

        for _attempt in range(4):
            response = self.client.post(
                reverse("services:provider_password_reset"),
                {"email": self.claim.email},
                REMOTE_ADDR="192.0.2.10",
            )
            self.assertRedirects(
                response, reverse("services:provider_password_reset_done")
            )
        self.assertEqual(len(mail.outbox), 3)

    def test_password_reset_throttle_removes_only_expired_rows(self):
        """Opportunistic bounded cleanup retains active windows and drops old keys."""

        now = timezone.now()
        expired = ProviderPasswordResetThrottle.objects.create(
            key_digest="c" * 64,
            window_started_at=now - timedelta(hours=25),
            send_count=3,
        )
        active = ProviderPasswordResetThrottle.objects.create(
            key_digest="d" * 64,
            window_started_at=now - timedelta(minutes=14),
            send_count=2,
        )

        self.assertTrue(
            claim_password_reset_send_slot(
                email="retention@example.ro", client_address="192.0.2.55"
            )
        )
        self.assertFalse(
            ProviderPasswordResetThrottle.objects.filter(pk=expired.pk).exists()
        )
        self.assertTrue(
            ProviderPasswordResetThrottle.objects.filter(pk=active.pk).exists()
        )

    def test_password_reset_link_fails_closed_after_access_revocation(self):
        """A valid credential must not outlive the provider membership boundary."""

        profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        self.client.post(reverse("services:provider_logout"))
        mail.outbox.clear()
        cache.clear()
        self.client.post(
            reverse("services:provider_password_reset"), {"email": self.claim.email}
        )
        reset_path = re.search(r"http://testserver([^\s]+)", mail.outbox[0].body).group(1)

        membership = profile.memberships.get()
        membership.state = ProviderMembership.State.REVOKED
        membership.revoked_at = timezone.now()
        membership.save(update_fields=("state", "revoked_at"))

        response = self.client.get(reset_path, follow=True)
        self.assertContains(response, "Linkul nu mai este activ")

    def test_password_reset_fails_closed_for_ambiguous_provider_ownership(self):
        """One e-mail must not select between multiple active provider identities."""

        _profile, _invitation, token = self.approve_and_deliver()
        password = "Provider-pass-2026!"
        self.client.post(
            reverse("services:provider_activate", args=(token,)),
            {"new_password1": password, "new_password2": password},
        )
        self.client.post(reverse("services:provider_logout"))
        user = get_user_model().objects.get(email=self.claim.email)
        other_business = BusinessIdentity.objects.create(
            registration_number="J27/56/2020"
        )
        other_claim = ProviderClaimRequest.objects.create(
            business=other_business,
            legal_name_at_request="ALT ATELIER S.R.L.",
            contact_name="Ion Popescu",
            role="administrator",
            email="ion@example.ro",
            status=ProviderClaimRequest.Status.REVIEW_PENDING,
            token_digest="b" * 64,
            token_expires_at=timezone.now() + timedelta(hours=1),
            email_verified_at=timezone.now(),
            email_delivery_state=ProviderClaimRequest.DeliveryState.SENT,
            privacy_notice_version="2026-08-25",
            consented_at=timezone.now(),
        )
        create_representation_evidence(claim=other_claim)
        other_profile, _invitation, _token = approve_provider_claim(
            claim_id=other_claim.pk,
            reviewer=self.reviewer,
            review_note="Mandatul pentru a doua firmă a fost verificat offline.",
            acknowledgement=REVIEW_ACKNOWLEDGEMENT,
        )
        other_membership = other_profile.memberships.get()
        other_membership.user = user
        other_membership.state = ProviderMembership.State.ACTIVE
        other_membership.activated_at = timezone.now()
        other_membership.save(update_fields=("user", "state", "activated_at"))
        mail.outbox.clear()
        cache.clear()

        response = self.client.post(
            reverse("services:provider_password_reset"), {"email": self.claim.email}
        )
        self.assertRedirects(response, reverse("services:provider_password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_review_requires_csrf_and_dedicated_permission(self):
        self.reviewer.is_superuser = True
        self.reviewer.save(update_fields=("is_superuser",))
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        url = reverse(
            "admin:services_providerclaimrequest_review", args=(self.claim.pk,)
        )
        self.assertEqual(
            client.post(
                url,
                {
                    "decision": "reject",
                    "review_note": "Dreptul de reprezentare nu a fost demonstrat.",
                    "acknowledgement": "on",
                },
            ).status_code,
            403,
        )
        page = client.get(url)
        evidence_url = reverse(
            "admin:services_providerclaimrequest_evidence", args=(self.claim.pk,)
        )
        self.assertContains(page, evidence_url)
        evidence_response = client.get(evidence_url)
        self.assertEqual(evidence_response.status_code, 200)
        self.assertEqual(evidence_response["Content-Type"], "application/pdf")
        self.assertTrue(
            evidence_response["Content-Disposition"].startswith("attachment;")
        )
        self.assertIn("private", evidence_response["Cache-Control"])
        self.assertIn("no-store", evidence_response["Cache-Control"])
        csrf_token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()
        ).group(1)
        decided = client.post(
            url,
            {
                "csrfmiddlewaretoken": csrf_token,
                "decision": "reject",
                "review_note": "Dreptul de reprezentare nu a fost demonstrat.",
                "acknowledgement": "on",
            },
        )
        self.assertEqual(decided.status_code, 302)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ProviderClaimRequest.Status.REJECTED)


class ProviderApprovalPostgreSQLTests(TransactionTestCase):
    """Prove that two real database connections cannot create two owners."""

    reset_sequences = True

    def test_two_concurrent_approvals_create_one_provider_identity(self):
        if connection.vendor != "postgresql":
            self.skipTest("Necesită două conexiuni PostgreSQL reale")
        business = BusinessIdentity.objects.create(registration_number="J27/99/2020")
        claim = ProviderClaimRequest.objects.create(
            business=business,
            legal_name_at_request="CONCURRENCY TEST S.R.L.",
            contact_name="Maria Test",
            role="administrator",
            email="maria-concurrency@example.ro",
            status=ProviderClaimRequest.Status.REVIEW_PENDING,
            token_digest="b" * 64,
            token_expires_at=timezone.now() + timedelta(hours=1),
            email_verified_at=timezone.now(),
            email_delivery_state=ProviderClaimRequest.DeliveryState.SENT,
            privacy_notice_version="2026-08-25",
            consented_at=timezone.now(),
        )
        create_representation_evidence(claim=claim)
        reviewer = get_user_model().objects.create_user(
            username="pg-reviewer", password="Review-pass-2026!", is_staff=True
        )
        reviewer.user_permissions.add(
            Permission.objects.get(codename="review_provider_claim")
        )
        barrier = Barrier(2)
        outcomes = []

        def approve_from_connection():
            close_old_connections()
            barrier.wait()
            try:
                approve_provider_claim(
                    claim_id=claim.pk,
                    reviewer=get_user_model().objects.get(pk=reviewer.pk),
                    review_note="Mandatul a fost verificat independent.",
                    acknowledgement=REVIEW_ACKNOWLEDGEMENT,
                )
            except ValueError:
                outcomes.append("refused")
            else:
                outcomes.append("approved")
            finally:
                connection.close()

        threads = [Thread(target=approve_from_connection) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(sorted(outcomes), ["approved", "refused"])
        self.assertEqual(ProviderProfile.objects.count(), 1)
        self.assertEqual(ProviderMembership.objects.count(), 1)
        self.assertEqual(ProviderAccountInvitation.objects.count(), 1)

    def test_concurrent_password_reset_requests_share_one_send_budget(self):
        """Six PostgreSQL connections may reserve only the three shared slots."""

        if connection.vendor != "postgresql":
            self.skipTest("Necesită conexiuni PostgreSQL reale")
        barrier = Barrier(6)
        outcomes = []

        def reserve_from_connection():
            close_old_connections()
            try:
                barrier.wait()
                outcomes.append(
                    claim_password_reset_send_slot(
                        email="provider-concurrency@example.ro",
                        client_address="192.0.2.44",
                    )
                )
            finally:
                connection.close()

        threads = [Thread(target=reserve_from_connection) for _attempt in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(outcomes.count(True), 3)
        self.assertEqual(outcomes.count(False), 3)

    def test_concurrent_login_attempts_share_one_failure_budget(self):
        """Eight PostgreSQL connections may reserve only five login attempts."""

        if connection.vendor != "postgresql":
            self.skipTest("Necesită conexiuni PostgreSQL reale")
        barrier = Barrier(8)
        outcomes = []

        def reserve_from_connection():
            close_old_connections()
            try:
                barrier.wait()
                outcomes.append(
                claim_account_login_attempt(
                    scope="provider", identifier="provider-login@example.ro"
                )
                )
            finally:
                connection.close()

        threads = [Thread(target=reserve_from_connection) for _attempt in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(outcomes.count(True), 5)
        self.assertEqual(outcomes.count(False), 3)
