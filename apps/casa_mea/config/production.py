"""Fail-closed cloud settings; local development behavior is unchanged."""

import os
from pathlib import Path
import re
from email.utils import parseaddr

from django.core.exceptions import ImproperlyConfigured
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from .build import *  # noqa: F403

DEBUG = False  # CASAMEA_DEBUG cannot make the cloud image expose internal previews.
PROVIDER_DEVELOPMENT_DEMO_ENABLED = False
SECRET_KEY = os.environ.get("CASAMEA_SECRET_KEY", "")  # noqa: F405
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("CASAMEA_SECRET_KEY must be a new random secret of at least 50 characters.")
if os.environ.get("CASAMEA_DB_ENGINE") != "postgresql":  # noqa: F405
    raise ImproperlyConfigured("Cloud deployment requires explicit PostgreSQL; SQLite fallback is forbidden.")
if not os.environ.get("CASAMEA_POSTGRES_PASSWORD"):  # noqa: F405
    raise ImproperlyConfigured("CASAMEA_POSTGRES_PASSWORD is required.")

DOMAIN = os.environ.get("CASAMEA_DOMAIN", "")  # noqa: F405
if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", DOMAIN):
    raise ImproperlyConfigured("CASAMEA_DOMAIN must be one host name, without scheme, port, path or wildcard.")
ALLOWED_HOSTS = [DOMAIN]
CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}"]
MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],
    "services.middleware.ProductionBrowserSecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]

# Safe only behind the deployment's trusted HTTPS reverse proxy, which overwrites
# X-Forwarded-Proto. The application port must not be exposed directly to the internet.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
# We own this hostname, not every future subdomain or a browser preload contract.
# Keep all other deployment warnings fatal in bootstrap.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
MEDIA_ROOT = Path(os.environ.get("CASAMEA_MEDIA_ROOT", "/app/private_media"))  # noqa: F405

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("CASAMEA_EMAIL_HOST", "")  # noqa: F405
if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", EMAIL_HOST):
    raise ImproperlyConfigured("CASAMEA_EMAIL_HOST must be one SMTP host name.")
try:
    EMAIL_PORT = int(os.environ.get("CASAMEA_EMAIL_PORT", "587"))  # noqa: F405
except ValueError as error:
    raise ImproperlyConfigured("CASAMEA_EMAIL_PORT must be an integer.") from error
if not 1 <= EMAIL_PORT <= 65535:
    raise ImproperlyConfigured("CASAMEA_EMAIL_PORT must be between 1 and 65535.")
EMAIL_HOST_USER = os.environ.get("CASAMEA_EMAIL_HOST_USER", "")  # noqa: F405
EMAIL_HOST_PASSWORD = os.environ.get("CASAMEA_EMAIL_HOST_PASSWORD", "")  # noqa: F405
if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    raise ImproperlyConfigured("SMTP username and password are required in production.")
DEFAULT_FROM_EMAIL = os.environ.get("CASAMEA_DEFAULT_FROM_EMAIL", "")  # noqa: F405
if "\r" in DEFAULT_FROM_EMAIL or "\n" in DEFAULT_FROM_EMAIL:
    raise ImproperlyConfigured("CASAMEA_DEFAULT_FROM_EMAIL is invalid.")
_sender_name, _sender_address = parseaddr(DEFAULT_FROM_EMAIL, strict=True)
try:
    validate_email(_sender_address)
except ValidationError as error:
    raise ImproperlyConfigured("CASAMEA_DEFAULT_FROM_EMAIL is invalid.") from error
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 10

LEGAL_OPERATOR_NAME = os.environ.get("CASAMEA_LEGAL_OPERATOR_NAME", "").strip()  # noqa: F405
LEGAL_OPERATOR_ADDRESS = os.environ.get("CASAMEA_LEGAL_OPERATOR_ADDRESS", "").strip()  # noqa: F405
PRIVACY_EMAIL = os.environ.get("CASAMEA_PRIVACY_EMAIL", "").strip()  # noqa: F405
COMMERCIAL_EMAIL = os.environ.get("CASAMEA_COMMERCIAL_EMAIL", "").strip()  # noqa: F405
if not LEGAL_OPERATOR_NAME or not LEGAL_OPERATOR_ADDRESS:
    raise ImproperlyConfigured(
        "CASAMEA_LEGAL_OPERATOR_NAME and CASAMEA_LEGAL_OPERATOR_ADDRESS are required."
    )
try:
    validate_email(PRIVACY_EMAIL)
except ValidationError as error:
    raise ImproperlyConfigured("CASAMEA_PRIVACY_EMAIL must be a valid address.") from error
try:
    validate_email(COMMERCIAL_EMAIL)
except ValidationError as error:
    raise ImproperlyConfigured("CASAMEA_COMMERCIAL_EMAIL must be a valid address.") from error

_retention_names = (
    "CASAMEA_RETENTION_UNVERIFIED_CLAIM_DAYS",
    "CASAMEA_RETENTION_REJECTED_CLAIM_DAYS",
    "CASAMEA_RETENTION_CLOSED_REPORT_DAYS",
    "CASAMEA_RETENTION_CLOSED_DATA_REQUEST_DAYS",
    "CASAMEA_RETENTION_MANAGED_SITE_INQUIRY_DAYS",
)
if any(not os.environ.get(name, "").strip() for name in _retention_names):  # noqa: F405
    raise ImproperlyConfigured(
        "All CASAMEA_RETENTION_*_DAYS values are required in production."
    )

# Security events use a strict field allowlist so cloud alerts need no account PII.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "operational_json": {
            "()": "services.logging_utils.OperationalJsonFormatter",
        }
    },
    "handlers": {
        "operational_console": {
            "class": "logging.StreamHandler",
            "formatter": "operational_json",
        }
    },
    "loggers": {
        "services.security": {
            "handlers": ["operational_console"],
            "level": "INFO",
            "propagate": False,
        }
    },
}
