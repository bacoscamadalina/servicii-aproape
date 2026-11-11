"""Administrative personal-data request registry and workflow contracts."""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .data_subject_requests import (
    EXTENSION_ACKNOWLEDGEMENT,
    PROCESS_ACKNOWLEDGEMENT,
    add_calendar_months,
    advance_data_subject_request,
    extend_data_subject_request_deadline,
    initial_data_request_due_at,
)
from .models import DataSubjectRequest, DataSubjectRequestEvent
from .forms import DataSubjectRequestProcessForm


class DataSubjectRequestTests(TestCase):
    """Prove intake immutability, deadline rules and audited state transitions."""

    def setUp(self):
        self.processor = get_user_model().objects.create_user(
            username="privacy-operator", password="test-password", is_staff=True
        )
        self.processor.user_permissions.add(
            Permission.objects.get(codename="add_datasubjectrequest"),
            Permission.objects.get(codename="view_datasubjectrequest"),
            Permission.objects.get(codename="process_data_subject_request"),
        )
        self.received_at = timezone.now().replace(microsecond=0)

    def create_request(self):
        return DataSubjectRequest.objects.create(
            request_kind=DataSubjectRequest.Kind.ACCESS,
            channel=DataSubjectRequest.Channel.EMAIL,
            requester_name="Ana Solicitant",
            contact_email="ana@example.test",
            details="Solicită acces la datele asociate contului său.",
            received_at=self.received_at,
            due_at=initial_data_request_due_at(self.received_at),
            recorded_by=self.processor,
        )

    def test_calendar_deadline_uses_one_month_not_thirty_days(self):
        january_end = timezone.make_aware(datetime(2027, 1, 31, 12, 30))
        leap_january_end = timezone.make_aware(datetime(2028, 1, 31, 12, 30))

        self.assertEqual(add_calendar_months(january_end, 1).day, 28)
        self.assertEqual(add_calendar_months(leap_january_end, 1).day, 29)
        self.assertEqual(add_calendar_months(january_end, 3).month, 4)

    def test_state_machine_records_events_and_rejects_stale_revision(self):
        item = self.create_request()
        advance_data_subject_request(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=0,
            new_status=DataSubjectRequest.Status.IDENTITY_PENDING,
            internal_note="Am solicitat confirmarea proporțională a identității.",
            acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=1),
        )
        with self.assertRaisesMessage(ValueError, "alt administrator"):
            advance_data_subject_request(
                request_id=item.pk,
                actor=self.processor,
                expected_revision=0,
                new_status=DataSubjectRequest.Status.IN_REVIEW,
                internal_note="Revizie veche pentru test.",
                acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            )
        item.refresh_from_db()
        self.assertIsNone(item.identity_verified_at)
        advance_data_subject_request(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=1,
            new_status=DataSubjectRequest.Status.IN_REVIEW,
            internal_note="Identitatea a fost confirmată prin canalul deja verificat.",
            acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=2),
        )
        item.refresh_from_db()
        self.assertIsNotNone(item.identity_verified_at)
        self.assertEqual(item.events.count(), 2)
        advance_data_subject_request(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=2,
            new_status=DataSubjectRequest.Status.FULFILLED,
            internal_note="Copia datelor și explicațiile au fost transmise solicitantului.",
            acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=3),
        )
        item.refresh_from_db()
        self.assertEqual(item.status, DataSubjectRequest.Status.FULFILLED)
        self.assertIsNotNone(item.closed_at)
        self.assertEqual(item.events.count(), 3)

    def test_extension_is_single_notified_and_must_precede_initial_deadline(self):
        item = self.create_request()
        extended = extend_data_subject_request_deadline(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=0,
            internal_note="Volumul sistemelor necesită inventariere suplimentară.",
            acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=10),
        )

        self.assertEqual(extended.extended_due_at, add_calendar_months(item.due_at, 2))
        self.assertIsNotNone(extended.extension_notified_at)
        self.assertEqual(extended.events.get().action, DataSubjectRequestEvent.Action.DEADLINE_EXTENDED)
        with self.assertRaisesMessage(ValueError, "deja prelungit"):
            extend_data_subject_request_deadline(
                request_id=item.pk,
                actor=self.processor,
                expected_revision=1,
                internal_note="A doua prelungire nu este permisă.",
                acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
            )

        late = self.create_request()
        with self.assertRaisesMessage(ValueError, "Termenul inițial"):
            extend_data_subject_request_deadline(
                request_id=late.pk,
                actor=self.processor,
                expected_revision=0,
                internal_note="Notificare introdusă prea târziu.",
                acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
                now=late.due_at + timedelta(seconds=1),
            )
        DataSubjectRequest.objects.filter(pk=late.pk).update(
            received_at=self.received_at - timedelta(days=40),
            due_at=self.received_at - timedelta(days=9),
        )
        late.refresh_from_db()
        self.assertNotIn(
            "extend_deadline",
            dict(DataSubjectRequestProcessForm(item=late).fields["action"].choices),
        )

    def test_admin_intake_sets_actor_deadline_and_get_is_inert(self):
        self.client.force_login(self.processor)
        response = self.client.post(
            reverse("admin:services_datasubjectrequest_add"),
            {
                "request_kind": DataSubjectRequest.Kind.ERASURE,
                "channel": DataSubjectRequest.Channel.EMAIL,
                "requester_name": "  Ana   Solicitant  ",
                "contact_email": "ANA@EXAMPLE.TEST",
                "details": "Solicită ștergerea datelor asociate profilului.",
                "received_at_0": timezone.localtime(self.received_at).strftime(
                    "%Y-%m-%d"
                ),
                "received_at_1": timezone.localtime(self.received_at).strftime("%H:%M:%S"),
                "_save": "Salvează",
            },
        )
        self.assertEqual(
            response.status_code,
            302,
            response.context["adminform"].form.errors.as_json()
            if response.status_code == 200
            else "",
        )
        item = DataSubjectRequest.objects.get()
        self.assertEqual(item.recorded_by, self.processor)
        self.assertEqual(item.requester_name, "Ana Solicitant")
        self.assertEqual(item.contact_email, "ana@example.test")
        self.assertEqual(item.due_at, initial_data_request_due_at(item.received_at))

        process_url = reverse(
            "admin:services_datasubjectrequest_process", args=(item.pk,)
        )
        before = (item.status, item.revision, item.events.count())
        page = self.client.get(process_url)
        item.refresh_from_db()
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Următoarea acțiune")
        self.assertEqual((item.status, item.revision, item.events.count()), before)

        processed = self.client.post(
            process_url,
            {
                "action": DataSubjectRequest.Status.IDENTITY_PENDING,
                "internal_note": "Am solicitat confirmarea proporțională a identității.",
                "acknowledgement": "on",
                "expected_revision": 0,
            },
        )
        self.assertEqual(processed.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, DataSubjectRequest.Status.IDENTITY_PENDING)
        self.assertEqual(item.events.count(), 1)

    def test_admin_processing_requires_dedicated_permission(self):
        item = self.create_request()
        viewer = get_user_model().objects.create_user(
            username="privacy-viewer", password="test-password", is_staff=True
        )
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_datasubjectrequest")
        )
        self.client.force_login(viewer)

        response = self.client.get(
            reverse("admin:services_datasubjectrequest_process", args=(item.pk,))
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthorized_service_call_is_rejected(self):
        item = self.create_request()
        viewer = get_user_model().objects.create_user(
            username="not-processor", password=None, is_staff=True
        )
        with self.assertRaises(PermissionError):
            advance_data_subject_request(
                request_id=item.pk,
                actor=viewer,
                expected_revision=0,
                new_status=DataSubjectRequest.Status.IN_REVIEW,
                internal_note="Încercare fără permisiune dedicată.",
                acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            )
