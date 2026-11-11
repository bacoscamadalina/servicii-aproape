"""Fail-closed and privacy tests for the explicit production SMTP probe."""

import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .management.commands.verify_smtp_delivery import SMTP_PROBE_ACKNOWLEDGEMENT


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="smtp.example.test",
    EMAIL_PORT=587,
    EMAIL_HOST_USER="smtp-user",
    EMAIL_HOST_PASSWORD="smtp-password",
    DEFAULT_FROM_EMAIL="ServiciiAproape <no-reply@example.test>",
    EMAIL_USE_TLS=True,
    EMAIL_TIMEOUT=10,
)
class SmtpDeliveryVerificationTests(SimpleTestCase):
    """Never transmit until the operator supplies every explicit send guard."""

    @patch("services.management.commands.verify_smtp_delivery.send_mail")
    def test_configuration_audit_does_not_send(self, send_mail):
        output = io.StringIO()
        call_command("verify_smtp_delivery", stdout=output)

        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "schema": 1,
                "valid": True,
                "configured": True,
                "delivery_tested": False,
                "tls": True,
                "timeout_seconds": 10,
            },
        )
        send_mail.assert_not_called()

    @patch("services.management.commands.verify_smtp_delivery.send_mail")
    def test_send_requires_recipient_and_exact_acknowledgement(self, send_mail):
        with self.assertRaisesRegex(CommandError, "valid probe recipient"):
            call_command("verify_smtp_delivery", "--send")
        with self.assertRaisesRegex(CommandError, "SEND_SYNTHETIC_SMTP_PROBE"):
            call_command(
                "verify_smtp_delivery",
                "--send",
                "--recipient",
                "operator@example.test",
            )
        send_mail.assert_not_called()

    @patch("services.management.commands.verify_smtp_delivery.security_logger.info")
    @patch("services.management.commands.verify_smtp_delivery.send_mail", return_value=1)
    def test_success_report_and_log_are_identity_free(self, send_mail, info):
        output = io.StringIO()
        call_command(
            "verify_smtp_delivery",
            "--send",
            "--recipient",
            "operator@example.test",
            "--acknowledgement",
            SMTP_PROBE_ACKNOWLEDGEMENT,
            stdout=output,
        )

        self.assertEqual(
            json.loads(output.getvalue()),
            {"schema": 1, "valid": True, "configured": True, "delivery_tested": True},
        )
        self.assertNotIn("operator@example.test", output.getvalue())
        send_mail.assert_called_once()
        info.assert_called_once_with(
            "Synthetic SMTP delivery probe succeeded.",
            extra={"event": "smtp_probe_succeeded"},
        )

    @patch("services.management.commands.verify_smtp_delivery.security_logger.error")
    @patch(
        "services.management.commands.verify_smtp_delivery.send_mail",
        side_effect=RuntimeError("private provider response"),
    )
    def test_failure_report_omits_recipient_and_exception_text(self, send_mail, error):
        output = io.StringIO()
        with self.assertRaisesRegex(CommandError, "probe failed"):
            call_command(
                "verify_smtp_delivery",
                "--send",
                "--recipient",
                "operator@example.test",
                "--acknowledgement",
                SMTP_PROBE_ACKNOWLEDGEMENT,
                stdout=output,
            )

        self.assertEqual(
            json.loads(output.getvalue()),
            {"schema": 1, "valid": False, "configured": True, "delivery_tested": True},
        )
        self.assertNotIn("operator@example.test", output.getvalue())
        self.assertNotIn("private provider response", output.getvalue())
        error.assert_called_once_with(
            "Synthetic SMTP delivery probe failed.",
            extra={"event": "smtp_probe_failed", "exception_type": "RuntimeError"},
        )
