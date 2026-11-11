FROM python:3.14-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp
WORKDIR /app

# Both final images run as the same unprivileged application identity.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
COPY --chown=root:root requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY --chown=root:root config/ config/
COPY --chown=root:root services/ services/
COPY --chown=root:root locale/ locale/
COPY --chown=root:root deploy/*.py deploy/
COPY --chown=root:root deploy/Caddyfile deploy/Caddyfile
COPY --chown=root:root tools/ tools/
COPY --chown=root:root tests/ tests/
COPY --chown=root:root manage.py ./
RUN python manage.py collectstatic --noinput --settings=config.build \
    && mkdir -p /app/private_media && chown app:app /app/private_media

USER 10001:10001
STOPSIGNAL SIGTERM

FROM base AS production
# Backup/restore tools require the PostgreSQL 17 client, but the autonomous preview does not.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*
COPY --chown=root:root deploy/preview/ /app/deploy/preview/
COPY --chown=root:root deploy/managed_cloud/ /app/deploy/managed_cloud/
# Source exports may be owner-only locally; normalize packaged public projections.
RUN chmod 0444 /app/deploy/preview/* /app/deploy/managed_cloud/*
USER 10001:10001
ENV DJANGO_SETTINGS_MODULE=config.production
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "--worker-tmp-dir", "/tmp", "--error-logfile", "-"]

# Complete persistent development cloud: full workflows plus the immutable national
# catalogue. The build fails unless every packaged listing has its matching identity.
FROM production AS managed-cloud
ENV DJANGO_SETTINGS_MODULE=config.managed_cloud_development PORT=8000
RUN python -c "import django; django.setup(); from django.conf import settings; from services.preview_catalogue import snapshot_metadata; from services.managed_cloud_seed import read_identity_seed; metadata = snapshot_metadata(); identities = read_identity_seed(settings.MANAGED_CLOUD_IDENTITY_SEED_PATH, settings.PREVIEW_CATALOGUE_PATH); assert len(identities) == metadata['businesses']"
CMD ["python", "deploy/start_managed_cloud.py"]

# Last stage is intentionally the zero-setup private cloud development viewer.
FROM base AS preview
# The non-root web process can read, but cannot modify the packaged catalogue,
# even on managed clouds that cannot accept a read_only filesystem option.
COPY --chown=root:root deploy/preview/ /app/deploy/preview/
ENV DJANGO_SETTINGS_MODULE=config.preview PORT=8000
RUN python -c "import django; django.setup(); from services.preview_catalogue import snapshot_metadata; snapshot_metadata()"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python deploy/preview_healthcheck.py
CMD ["python", "deploy/start_preview.py"]
