"""Persistent managed-cloud deployment backed by the packaged public catalogue."""

from .production import *  # noqa: F403

# Discovery remains a verified immutable projection, while accounts, claims,
# publication state and portfolio media use the persistent PostgreSQL database.
PACKAGED_CATALOGUE = True
PREVIEW_CATALOGUE_PATH = BASE_DIR / "deploy/preview/catalogue.snapshot"  # noqa: F405
PREVIEW_REQUIRE_COMPLETE = True
MANAGED_CLOUD_IDENTITY_SEED_PATH = (
    BASE_DIR / "deploy/managed_cloud/identities.jsonl.gz"  # noqa: F405
)
