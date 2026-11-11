"""Validate production SMTP and optionally send one explicit synthetic probe."""

import json
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


SMTP_PROBE_ACKNOWLEDGEMENT = "SEND_SYNTHETIC_SMTP_PROBE"
security_logger = logging.getLogger("services.security")


class Command(BaseCommand):
    """Expose an identity-free SMTP readiness result; never infer permission to send."""

    help = "Verifică SMTP și, numai cu confirmare explicită, trimite un mesaj sintetic."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true")
        parser.add_argument("--recipient")
        parser.add_argument("--acknowledgement")

    def handle(self, *args, **options):
        if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
            raise CommandError("SMTP production backend is not configured.")
        configured = bool(
            settings.EMAIL_HOST
            and settings.EMAIL_PORT
            and settings.EMAIL_HOST_USER
            and settings.EMAIL_HOST_PASSWORD
            and settings.DEFAULT_FROM_EMAIL
            and settings.EMAIL_USE_TLS
            and settings.EMAIL_TIMEOUT
        )
        if not configured:
            raise CommandError("SMTP production settings are incomplete.")
        if not options["send"]:
            self.stdout.write(
                json.dumps(
                    {
                        "schema": 1,
                        "valid": True,
                        "configured": True,
                        "delivery_tested": False,
                        "tls": True,
                        "timeout_seconds": settings.EMAIL_TIMEOUT,
                    },
                    sort_keys=True,
                )
            )
            return

        recipient = options["recipient"] or ""
        try:
            validate_email(recipient)
        except ValidationError as error:
            raise CommandError("A valid probe recipient is required.") from error
        if options["acknowledgement"] != SMTP_PROBE_ACKNOWLEDGEMENT:
            raise CommandError(
                f"Sending requires --acknowledgement {SMTP_PROBE_ACKNOWLEDGEMENT}."
            )
        try:
            delivered = send_mail(
                subject="ServiciiAproape SMTP production probe",
                message=(
                    "This is a synthetic ServiciiAproape delivery test. It contains "
                    "no account, provider, claim or authentication data."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as error:
            security_logger.error(
                "Synthetic SMTP delivery probe failed.",
                extra={
                    "event": "smtp_probe_failed",
                    "exception_type": type(error).__name__,
                },
            )
            self.stdout.write(
                json.dumps(
                    {"schema": 1, "valid": False, "configured": True, "delivery_tested": True},
                    sort_keys=True,
                )
            )
            raise CommandError("SMTP delivery probe failed.") from error
        if delivered != 1:
            raise CommandError("SMTP backend did not confirm exactly one delivery.")
        security_logger.info(
            "Synthetic SMTP delivery probe succeeded.",
            extra={"event": "smtp_probe_succeeded"},
        )
        self.stdout.write(
            json.dumps(
                {"schema": 1, "valid": True, "configured": True, "delivery_tested": True},
                sort_keys=True,
            )
        )
