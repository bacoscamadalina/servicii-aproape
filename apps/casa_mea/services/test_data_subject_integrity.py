"""Read-only integrity audit contracts for personal-data requests."""

from datetime import timedelta
from io import StringIO
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .data_retention import REDACTED_DATA_REQUEST_TEXT
from .data_subject_exports import EXPORT_ACKNOWLEDGEMENT, generate_data_subject_export
from .data_subject_integrity import audit_data_subject_requests
from .data_subject_requests import (
    EXTENSION_ACKNOWLEDGEMENT,
    PROCESS_ACKNOWLEDGEMENT,
    add_calendar_months,
    advance_data_subject_request,
    extend_data_subject_request_deadline,
    initial_data_request_due_at,
)
from .models import DataSubjectRequest, DataSubjectRequestEvent


class DataSubjectRequestIntegrityTests(TestCase):
    """Prove bounded observation, anomaly classification and non-mutation."""

    def setUp(self):
        self.processor = get_user_model().objects.create_user(
            username="privacy-integrity", password="test-password", is_staff=True
        )
        self.processor.user_permissions.add(
            Permission.objects.get(codename="process_data_subject_request")
        )
        self.received_at = (timezone.now() - timedelta(days=20)).replace(
            microsecond=0
        )

    def create_request(self):
        """Create one immutable intake record through its model contract."""

        return DataSubjectRequest.objects.create(
            request_kind=DataSubjectRequest.Kind.ACCESS,
            channel=DataSubjectRequest.Channel.EMAIL,
            requester_name="Persoană audit",
            contact_email="audit@example.test",
            details="Solicită acces la datele asociate contului său.",
            received_at=self.received_at,
            due_at=initial_data_request_due_at(self.received_at),
            recorded_by=self.processor,
        )

    def complete_valid_chain(self):
        """Exercise extension, verification, export and closure in their valid order."""

        item = self.create_request()
        extend_data_subject_request_deadline(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=0,
            internal_note="Volumul datelor necesită inventariere suplimentară.",
            acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=2),
        )
        advance_data_subject_request(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=1,
            new_status=DataSubjectRequest.Status.IN_REVIEW,
            internal_note="Identitatea a fost confirmată prin canalul verificat.",
            acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=3),
        )
        generate_data_subject_export(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=2,
            acknowledgement=EXPORT_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=4),
        )
        advance_data_subject_request(
            request_id=item.pk,
            actor=self.processor,
            expected_revision=3,
            new_status=DataSubjectRequest.Status.FULFILLED,
            internal_note="Pachetul a fost transmis persoanei prin canalul adecvat.",
            acknowledgement=PROCESS_ACKNOWLEDGEMENT,
            now=self.received_at + timedelta(days=5),
        )
        item.refresh_from_db()
        return item

    def test_valid_chains_and_empty_register_use_one_streaming_query(self):
        with self.assertNumQueries(1):
            empty = audit_data_subject_requests(chunk_size=2)
        self.assertTrue(empty.is_valid)
        self.assertEqual(empty.total_requests, 0)

        item = self.complete_valid_chain()
        second = self.create_request()
        with self.assertNumQueries(1):
            audit = audit_data_subject_requests(chunk_size=2)

        self.assertTrue(audit.is_valid)
        self.assertEqual(audit.total_requests, 2)
        self.assertEqual(audit.total_events, 4)
        self.assertFalse(any(dict(audit.anomaly_counts).values()))
        self.assertNotIn(item.contact_email, json.dumps(audit.as_dict()))
        self.assertNotIn(second.requester_name, json.dumps(audit.as_dict()))

    def test_audit_classifies_drift_without_repairing_it(self):
        item = self.complete_valid_chain()
        DataSubjectRequest.objects.filter(pk=item.pk).update(
            revision=9,
            due_at=item.due_at + timedelta(seconds=1),
            identity_verified_at=item.received_at - timedelta(seconds=1),
        )
        DataSubjectRequestEvent.objects.filter(request=item, revision=1).delete()
        DataSubjectRequestEvent.objects.filter(request=item, revision=2).update(
            internal_note="scurt"
        )
        before = (
            DataSubjectRequest.objects.get(pk=item.pk).revision,
            DataSubjectRequestEvent.objects.filter(request=item).count(),
        )

        audit = audit_data_subject_requests()
        anomalies = dict(audit.anomaly_counts)

        self.assertFalse(audit.is_valid)
        self.assertEqual(anomalies["request_revision_mismatch"], 1)
        self.assertEqual(anomalies["initial_deadline_mismatch"], 1)
        self.assertEqual(anomalies["extension_contract_mismatch"], 1)
        self.assertEqual(anomalies["request_timeline_mismatch"], 1)
        self.assertEqual(anomalies["event_revision_mismatch"], 1)
        self.assertEqual(anomalies["event_metadata_mismatch"], 1)
        after = (
            DataSubjectRequest.objects.get(pk=item.pk).revision,
            DataSubjectRequestEvent.objects.filter(request=item).count(),
        )
        self.assertEqual(after, before)

    def test_retention_minimized_notes_remain_auditable(self):
        item = self.complete_valid_chain()
        DataSubjectRequest.objects.filter(pk=item.pk).update(
            retention_applied_at=timezone.now()
        )
        DataSubjectRequestEvent.objects.filter(request=item).update(
            internal_note=REDACTED_DATA_REQUEST_TEXT
        )

        self.assertTrue(audit_data_subject_requests().is_valid)

    def test_terminal_requests_cannot_gain_a_deadline_extension_event(self):
        for expected_count, terminal_status in enumerate(
            (
                DataSubjectRequest.Status.FULFILLED,
                DataSubjectRequest.Status.REFUSED,
            ),
            start=1,
        ):
            with self.subTest(terminal_status=terminal_status):
                item = self.create_request()
                advance_data_subject_request(
                    request_id=item.pk,
                    actor=self.processor,
                    expected_revision=0,
                    new_status=DataSubjectRequest.Status.IN_REVIEW,
                    internal_note="Identitatea a fost confirmată pentru testul terminal.",
                    acknowledgement=PROCESS_ACKNOWLEDGEMENT,
                    now=self.received_at + timedelta(days=1),
                )
                advance_data_subject_request(
                    request_id=item.pk,
                    actor=self.processor,
                    expected_revision=1,
                    new_status=terminal_status,
                    internal_note="Cererea a fost închisă pentru testul terminal.",
                    acknowledgement=PROCESS_ACKNOWLEDGEMENT,
                    now=self.received_at + timedelta(days=2),
                )
                event = DataSubjectRequestEvent.objects.create(
                    request=item,
                    action=DataSubjectRequestEvent.Action.DEADLINE_EXTENDED,
                    previous_status=terminal_status,
                    new_status=terminal_status,
                    revision=3,
                    internal_note="Prelungire imposibilă injectată exclusiv pentru test.",
                    policy_version="2026-09-02-v1",
                    acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
                    actor=self.processor,
                )
                DataSubjectRequest.objects.filter(pk=item.pk).update(
                    revision=3,
                    extended_due_at=add_calendar_months(item.due_at, 2),
                    extension_notified_at=min(item.due_at, event.created_at),
                )

                anomalies = dict(audit_data_subject_requests().anomaly_counts)
                self.assertEqual(
                    anomalies["event_transition_mismatch"], expected_count
                )

    def test_audit_detects_status_chronology_and_export_metadata_drift(self):
        item = self.complete_valid_chain()
        first_event = item.events.get(revision=1)
        DataSubjectRequestEvent.objects.filter(request=item, revision=2).update(
            created_at=first_event.created_at - timedelta(seconds=1)
        )
        DataSubjectRequestEvent.objects.filter(request=item, revision=3).update(
            internal_note="Pachet fără digest valid."
        )
        DataSubjectRequestEvent.objects.filter(request=item, revision=4).delete()

        anomalies = dict(audit_data_subject_requests().anomaly_counts)

        self.assertEqual(anomalies["request_status_mismatch"], 1)
        self.assertEqual(anomalies["event_chronology_mismatch"], 1)
        self.assertEqual(anomalies["event_metadata_mismatch"], 1)

    def test_parent_timestamps_must_not_postdate_their_events(self):
        item = self.complete_valid_chain()
        identity_event = item.events.get(revision=2)
        close_event = item.events.get(revision=4)
        extension_event = item.events.get(revision=1)
        DataSubjectRequest.objects.filter(pk=item.pk).update(
            identity_verified_at=identity_event.created_at + timedelta(seconds=1),
            closed_at=close_event.created_at + timedelta(seconds=2),
            extension_notified_at=extension_event.created_at + timedelta(seconds=1),
        )

        anomalies = dict(audit_data_subject_requests().anomaly_counts)

        self.assertEqual(anomalies["request_timeline_mismatch"], 1)
        self.assertEqual(anomalies["extension_contract_mismatch"], 1)

    def test_command_emits_identity_free_json_and_fails_nonzero_on_drift(self):
        item = self.complete_valid_chain()
        valid_output = StringIO()
        call_command("audit_data_subject_requests", stdout=valid_output)
        valid_payload = json.loads(valid_output.getvalue())
        self.assertTrue(valid_payload["valid"])
        self.assertNotIn(item.contact_email, valid_output.getvalue())
        self.assertNotIn(item.requester_name, valid_output.getvalue())

        DataSubjectRequest.objects.filter(pk=item.pk).update(revision=12)
        invalid_output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_data_subject_requests", stdout=invalid_output)
        invalid_payload = json.loads(invalid_output.getvalue())
        self.assertFalse(invalid_payload["valid"])
        self.assertEqual(
            invalid_payload["anomalies"]["request_revision_mismatch"], 1
        )
