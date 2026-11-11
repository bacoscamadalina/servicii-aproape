"""Initialize persistent managed-cloud state, then replace this process with Gunicorn."""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.managed_cloud")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.validators import validate_email
from django.db import connection
from django.db.utils import OperationalError

from services.managed_cloud_seed import seed_business_identities_if_empty


def wait_for_database() -> None:
    """Wait at most one minute for the Compose database without hiding its last error."""

    last_error = None
    for _attempt in range(60):
        try:
            connection.ensure_connection()
            return
        except OperationalError as error:
            last_error = error
            time.sleep(1)
    raise SystemExit(f"PostgreSQL did not become ready: {last_error}")


def create_initial_admin_if_absent() -> bool:
    """Create exactly one environment-owned administrator without rotating it on restart."""

    username = os.environ.get("CASAMEA_ADMIN_USERNAME", "").strip()
    email = os.environ.get("CASAMEA_ADMIN_EMAIL", "").strip()
    password = os.environ.get("CASAMEA_ADMIN_PASSWORD", "")
    if not username or not email or not password:
        raise SystemExit(
            "CASAMEA_ADMIN_USERNAME, CASAMEA_ADMIN_EMAIL and "
            "CASAMEA_ADMIN_PASSWORD are required."
        )
    try:
        validate_email(email)
    except ValidationError as error:
        raise SystemExit("CASAMEA_ADMIN_EMAIL must be valid.") from error

    users = get_user_model()
    existing = users.objects.filter(username=username).first()
    if existing:
        if not existing.is_active or not existing.is_staff or not existing.is_superuser:
            raise SystemExit(
                "The configured administrator username belongs to a non-administrator account."
            )
        return False
    candidate = users(username=username, email=email, is_staff=True, is_superuser=True)
    try:
        validate_password(password, user=candidate)
    except ValidationError as error:
        raise SystemExit(
            "CASAMEA_ADMIN_PASSWORD does not satisfy password validation."
        ) from error
    users.objects.create_superuser(username=username, email=email, password=password)
    return True


def main() -> None:
    """Prepare persistent state completely before accepting HTTP traffic."""

    wait_for_database()
    call_command("migrate", interactive=False, verbosity=1)
    seeded = seed_business_identities_if_empty(
        Path(settings.MANAGED_CLOUD_IDENTITY_SEED_PATH),
        Path(settings.PREVIEW_CATALOGUE_PATH),
    )
    admin_created = create_initial_admin_if_absent()
    if getattr(settings, "MANAGED_CLOUD_DEPLOY_CHECK", True):
        call_command("check", deploy=True, fail_level="WARNING")
    else:
        call_command("check")
    print(
        f"Managed cloud ready: seeded_businesses={seeded}, "
        f"admin_created={str(admin_created).lower()}",
        flush=True,
    )

    port = os.environ.get("PORT", "8000")
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise SystemExit("PORT must be an integer from 1 to 65535")
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "config.wsgi:application",
            "--bind",
            f"0.0.0.0:{port}",
            "--workers",
            "2",
            "--timeout",
            "60",
            "--worker-tmp-dir",
            "/tmp",
            "--error-logfile",
            "-",
        ],
    )


if __name__ == "__main__":
    main()
