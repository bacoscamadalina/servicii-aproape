"""Read-only structural and freshness verification for one private backup bundle."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

if __package__:
    from .restore import inspect_safe_media_archive, validate_backup
else:
    from restore import inspect_safe_media_archive, validate_backup


def verify_private_backup(
    backup: Path,
    app_root: Path,
    *,
    max_age_hours: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Verify hashes, source pins, media inventory, dump structure and optional age."""

    manifest = validate_backup(backup, app_root)
    media = inspect_safe_media_archive(backup / "private_media.tar.gz")
    if manifest["schema"] == 2 and media != manifest["media"]:
        raise ValueError("Backup media inventory differs from its manifest.")

    try:
        subprocess.run(
            ["pg_restore", "--list", str(backup / "database.dump")],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError("PostgreSQL dump structure is invalid.") from error

    observed_at = now or datetime.now(timezone.utc)
    created_at_text = manifest.get("created_at")
    age_seconds = None
    if max_age_hours is not None:
        if not created_at_text:
            raise ValueError("Backup freshness cannot be proven from this legacy manifest.")
        try:
            created_at = datetime.fromisoformat(created_at_text)
        except (TypeError, ValueError) as error:
            raise ValueError("Backup creation timestamp is invalid.") from error
        if created_at.tzinfo is None:
            raise ValueError("Backup creation timestamp must include a timezone.")
        age_seconds = int((observed_at - created_at).total_seconds())
        if age_seconds < 0:
            raise ValueError("Backup creation timestamp is in the future.")
        if age_seconds > max_age_hours * 3600:
            raise ValueError("Backup is older than the configured freshness limit.")

    return {
        "schema": 1,
        "valid": True,
        "backup_manifest_schema": manifest["schema"],
        "created_at": created_at_text,
        "age_seconds": age_seconds,
        "database_bytes": manifest["files"]["database.dump"]["bytes"],
        "media_archive_bytes": manifest["files"]["private_media.tar.gz"]["bytes"],
        "media_regular_files": media["regular_files"],
        "media_uncompressed_bytes": media["uncompressed_bytes"],
        "source_artifacts": len(manifest["source_artifacts"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--app-root", type=Path, default=Path(__file__).resolve().parents[1])
    configured_max_age = os.environ.get("CASAMEA_BACKUP_MAX_AGE_HOURS")
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=int(configured_max_age) if configured_max_age else None,
    )
    arguments = parser.parse_args()
    try:
        report = verify_private_backup(
            arguments.backup.resolve(),
            arguments.app_root.resolve(),
            max_age_hours=arguments.max_age_hours,
        )
    except Exception:
        print(json.dumps({"schema": 1, "valid": False, "error": "backup_verification_failed"}))
        raise SystemExit(1)
    print(json.dumps(report, sort_keys=True))
