"""Self-contained private development viewer; no database, sessions or accounts."""

import secrets
from copy import deepcopy

from .build import *  # noqa: F403

DEBUG = False
READ_ONLY_PREVIEW = True
PREVIEW_REQUIRE_COMPLETE = True
SECRET_KEY = secrets.token_urlsafe(64)
# Private clouds choose their own host; no cookies or host-derived security links exist.
ALLOWED_HOSTS = ['*']
DATABASES = {'default': {'ENGINE': 'django.db.backends.dummy'}}
ROOT_URLCONF = 'config.preview_urls'
PREVIEW_CATALOGUE_PATH = BASE_DIR / 'deploy/preview/catalogue.snapshot'  # noqa: F405
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'services.preview_catalogue.ReadOnlyPreviewMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]['OPTIONS']['context_processors'] = [
    'django.template.context_processors.request',
    'services.context_processors.language_navigation',
    'services.preview_catalogue.preview_context',
]
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
