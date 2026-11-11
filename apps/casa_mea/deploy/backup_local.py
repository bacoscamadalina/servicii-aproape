"""Export a PRIVATE PostgreSQL/media transfer bundle, never an application image.

Run while provider/admin writes are paused: pg_dump is transactionally consistent,
but a live filesystem and PostgreSQL cannot share that transaction.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

APP_ROOT = Path(__file__).resolve().parents[1]


def export_private_backup(destination: Path, container: str, media_root: Path) -> None:
    """Create a fresh restricted bundle; a manifest marks successful completion."""
    metadata = json.loads(subprocess.run(
        ["docker", "inspect", container], check=True, capture_output=True, text=True,
    ).stdout)[0]
    environment = dict(item.split("=", 1) for item in metadata["Config"]["Env"] if "=" in item)
    database, user = environment["POSTGRES_DB"], environment["POSTGRES_USER"]
    version = subprocess.run([
        "docker", "exec", container, "psql", "--username", user, "--dbname", database,
        "-Atc", "SHOW server_version_num",
    ], check=True, capture_output=True, text=True).stdout.strip()
    if not version.isdigit() or int(version) // 10000 != 17:
        raise ValueError("This transfer contract requires PostgreSQL 17.")
    if not media_root.is_dir():
        raise ValueError("The private media directory is missing; refusing an incomplete backup.")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    dump_path = destination / "database.dump"
    with dump_path.open("xb") as dump:
        os.chmod(dump_path, 0o600)
        subprocess.run([
            "docker", "exec", container, "pg_dump", "--format=custom",
            "--no-owner", "--no-acl", "--username", user, "--dbname", database,
        ], stdout=dump, check=True)
    media_path = destination / "private_media.tar.gz"
    media_file_count = 0
    media_uncompressed_bytes = 0
    with tarfile.open(media_path, "w:gz") as archive:
        for path in sorted(media_root.rglob("*")):
            if path.relative_to(media_root) == Path(".restore-complete"):
                continue  # Deployment metadata is regenerated, never a portfolio asset.
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Private media contains a link or special file; export stopped.")
            if path.is_file():
                media_file_count += 1
                media_uncompressed_bytes += path.stat().st_size
            archive.add(path, arcname=str(path.relative_to(media_root)), recursive=False)
    os.chmod(media_path, 0o600)
    artifact_hashes = {}
    for path in sorted((APP_ROOT / "services/data").rglob("*.json")):
        if "raw" not in path.parts:
            with path.open("rb") as source:
                artifact_hashes[str(path.relative_to(APP_ROOT))] = hashlib.file_digest(source, "sha256").hexdigest()
    files = {}
    for path in (dump_path, media_path):
        with path.open("rb") as source:
            files[path.name] = {"sha256": hashlib.file_digest(source, "sha256").hexdigest(), "bytes": path.stat().st_size}
    manifest = {
        "schema": 2, "created_at": datetime.now(timezone.utc).isoformat(),
        "private": True, "postgres_major": 17,
        "files": files, "source_artifacts": artifact_hashes,
        "media": {
            "regular_files": media_file_count,
            "uncompressed_bytes": media_uncompressed_bytes,
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    print(f"Private backup completed: {destination} ({dump_path.stat().st_size:,} database bytes).")
    print("Contains private accounts and records. Transfer only to your trusted server; never commit or publish.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--container", default="casamea-postgres-pilot")
    parser.add_argument("--media-root", type=Path, default=APP_ROOT / "private_media")
    parser.add_argument("--writes-paused", action="store_true", required=True,
                        help="Confirm no provider/admin/import writes occur during the backup.")
    arguments = parser.parse_args()
    export_private_backup(arguments.destination.resolve(), arguments.container, arguments.media_root.resolve())
