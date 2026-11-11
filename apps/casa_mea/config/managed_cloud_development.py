"""Persistent development cloud with the packaged catalogue and full workflows."""

import os

from .build import *  # noqa: F403

# This target is intentionally development-only: the platform URL may change and
# confirmation e-mails are inspected in container logs instead of being transmitted.
DEBUG = True
PROVIDER_DEVELOPMENT_DEMO_ENABLED = True
SECRET_KEY = os.environ.get(
    "CASAMEA_SECRET_KEY", "django-insecure-managed-cloud-development-only"
)
ALLOWED_HOSTS = ["*"]
# The managed platform owns this proxy boundary. Recognizing its HTTPS scheme keeps
# same-origin admin and provider POST forms valid without requiring a fixed dev URL.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = ["https://*.apps.doiplusdoi.ro"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "ServiciiAproape development <no-reply@localhost>"
MEDIA_ROOT = BASE_DIR / "private_media"  # noqa: F405

MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]

PACKAGED_CATALOGUE = True
PREVIEW_CATALOGUE_PATH = BASE_DIR / "deploy/preview/catalogue.snapshot"  # noqa: F405
PREVIEW_REQUIRE_COMPLETE = True
MANAGED_CLOUD_IDENTITY_SEED_PATH = (
    BASE_DIR / "deploy/managed_cloud/identities.jsonl.gz"  # noqa: F405
)
MANAGED_CLOUD_DEPLOY_CHECK = False
