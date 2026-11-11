"""Privacy and emission tests for production operational logging."""

import json
import logging
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from .logging_utils import OperationalJsonFormatter
from .provider_access import claim_account_login_attempt


class OperationalJsonFormatterTests(SimpleTestCase):
    """Keep the production log schema structured and explicitly PII-free."""

    def test_formatter_emits_allowlisted_fields_only(self):
        record = logging.LogRecord(
            name="services.security",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="Account login attempt budget exhausted.",
            args=(),
            exc_info=None,
        )
        record.event = "account_login_throttled"
        record.scope = "admin"
        record.email = "private@example.invalid"
        record.password = "never-log-this"

        payload = json.loads(OperationalJsonFormatter().format(record))

        self.assertEqual(
            set(payload), {"timestamp", "level", "logger", "message", "event", "scope"}
        )
        self.assertEqual(payload["event"], "account_login_throttled")
        self.assertNotIn("private@example.invalid", json.dumps(payload))
        self.assertNotIn("never-log-this", json.dumps(payload))


class OperationalSecurityEventTests(TestCase):
    """Emit one identity-free event when a shared login budget is exhausted."""

    @patch("services.provider_access.security_logger.warning")
    def test_blocked_admin_login_emits_scope_without_identifier(self, warning):
        for _attempt in range(5):
            self.assertTrue(
                claim_account_login_attempt(scope="admin", identifier="SecretAdmin")
            )

        self.assertFalse(
            claim_account_login_attempt(scope="admin", identifier="secretadmin")
        )

        warning.assert_called_once_with(
            "Account login attempt budget exhausted.",
            extra={"event": "account_login_throttled", "scope": "admin"},
        )
        self.assertNotIn("secretadmin", repr(warning.call_args))
