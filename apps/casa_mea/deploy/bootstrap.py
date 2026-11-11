"""Migrate only after an explicit completed restore; never start an empty catalogue."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.production")

import django
django.setup()

from django.conf import settings
from django.core.management import call_command

if not (Path(settings.MEDIA_ROOT) / ".restore-complete").is_file():
    raise SystemExit("Restore required: docker compose run --rm restore (only into empty volumes).")
call_command("migrate", interactive=False)
call_command("verify_cloud_catalogue")
call_command("check", deploy=True, fail_level="WARNING")
