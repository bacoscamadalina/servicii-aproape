"""Restore a trusted private bundle ONCE into a fresh database and media volume."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

import psycopg


def validate_backup(backup: Path, app_root: Path) -> dict:
    """Verify all bytes before writes; hashes detect corruption, not authorship."""
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") not in (1, 2) or manifest.get("postgres_major") != 17 or manifest.get("private") is not True:
        raise ValueError("Unsupported private backup manifest.")
    if set(manifest["files"]) != {"database.dump", "private_media.tar.gz"}:
        raise ValueError("Incomplete backup.")
    for name, expected in manifest["files"].items():
        path = backup / name
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"Corrupt backup artifact: {name}")
    pinned = {
        str(path.relative_to(app_root)): path
        for path in (app_root / "services/data").rglob("*.json") if "raw" not in path.parts
    }
    if set(manifest["source_artifacts"]) != set(pinned):
        raise ValueError("Source artifact set differs from the application image.")
    for name, path in pinned.items():
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != manifest["source_artifacts"][name]:
            raise ValueError(f"Application source pin differs: {name}")
    if manifest["schema"] == 2:
        media = manifest.get("media")
        if not isinstance(media, dict) or set(media) != {"regular_files", "uncompressed_bytes"}:
            raise ValueError("Incomplete backup media inventory.")
        if any(not isinstance(media[field], int) or media[field] < 0 for field in media):
            raise ValueError("Invalid backup media inventory.")
    return manifest


def inspect_safe_media_archive(archive_path: Path) -> dict[str, int]:
    """Validate archive members and return an identity-free size inventory."""

    regular_files = 0
    uncompressed_bytes = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0].startswith(".")
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError(
                    "Unsafe media archive: only relative regular files/directories are accepted."
                )
            if member.isfile():
                regular_files += 1
                uncompressed_bytes += member.size
    return {
        "regular_files": regular_files,
        "uncompressed_bytes": uncompressed_bytes,
    }


def restore_private_backup(backup: Path, media: Path, app_root: Path) -> None:
    """Stage media, restore SQL transactionally, mark the two-part copy complete.

    Filesystem and PostgreSQL cannot commit atomically together. A failure after
    SQL commit leaves no marker and blocks bootstrap; retry into fresh volumes.
    """
    manifest = validate_backup(backup, app_root)
    media_inventory = inspect_safe_media_archive(backup / "private_media.tar.gz")
    if manifest["schema"] == 2 and media_inventory != manifest["media"]:
        raise ValueError("Backup media inventory differs from its manifest.")
    connection = {
        "dbname": os.environ["CASAMEA_POSTGRES_DB"],
        "user": os.environ["CASAMEA_POSTGRES_USER"],
        "password": os.environ["CASAMEA_POSTGRES_PASSWORD"],
        "host": os.environ["CASAMEA_POSTGRES_HOST"],
        "port": os.environ.get("CASAMEA_POSTGRES_PORT", "5432"),
    }
    with psycopg.connect(**connection, autocommit=True) as database:
        # Serialize this tool across workers; external migrations must stay stopped.
        database.execute("SELECT pg_advisory_lock(772910483)")
        exists = database.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f'))"
        ).fetchone()[0]
        media.mkdir(exist_ok=True)
        if exists or any(media.iterdir()):
            raise ValueError("Restore refused: database and media volume must both be empty. Nothing overwritten.")
        with tempfile.TemporaryDirectory(prefix="restore-", dir=media) as staging_name:
            staging = Path(staging_name)
            with tarfile.open(backup / "private_media.tar.gz", "r:gz") as archive:
                archive.extractall(staging, filter="data")
            # Prepare ownership before SQL commits so ordinary permission failures
            # cannot strand an otherwise complete database restore.
            for path in staging.rglob("*"):
                os.chown(path, 10001, 10001)
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
            environment = {**os.environ, "PGPASSWORD": connection["password"]}
            subprocess.run([
                "pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl",
                "--host", connection["host"], "--port", connection["port"],
                "--username", connection["user"], "--dbname", connection["dbname"],
                str(backup / "database.dump"),
            ], env=environment, check=True)
            for path in staging.iterdir():
                shutil.move(str(path), media / path.name)
        os.chown(media, 10001, 10001)
        os.chmod(media, 0o700)
        marker = media / ".restore-complete"
        marker.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        os.chown(marker, 10001, 10001)
        os.chmod(marker, 0o600)
    print("Private database/media restored. No catalogue approvals or visibility states were changed.")


if __name__ == "__main__":
    restore_private_backup(Path("/backup"), Path("/app/private_media"), Path("/app"))
