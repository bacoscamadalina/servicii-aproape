"""Connect local ``runserver`` sessions to the complete PostgreSQL catalogue."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping, MutableMapping

import psycopg


DEFAULT_CONTAINER = "casamea-postgres-pilot"
POSTGRES_PORT = "5432/tcp"


class LocalCatalogueError(RuntimeError):
    """Explain why the complete local catalogue could not be started."""


def configure_runserver_catalogue_from_local_container(
    environ: MutableMapping[str, str] | None = None,
) -> bool:
    """Start the local catalogue container and expose its connection to Django.

    Invariant: an explicitly selected database always wins. Automatic discovery is
    only a convenience for the otherwise unconfigured local ``runserver`` command.
    Secrets are read into the current process from Docker metadata and are never
    written to the repository or printed.
    """

    target_environ = os.environ if environ is None else environ
    if target_environ.get("CASAMEA_DB_ENGINE"):
        return False

    container = target_environ.get(
        "CASAMEA_POSTGRES_CONTAINER", DEFAULT_CONTAINER
    )
    try:
        inspected = subprocess.run(
            ["docker", "inspect", container],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise LocalCatalogueError(
            "Docker nu este instalat. Instalează Docker sau setează explicit "
            "CASAMEA_DB_ENGINE=sqlite pentru o bază locală goală."
        ) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LocalCatalogueError(
            f"Containerul PostgreSQL «{container}» nu este disponibil. "
            "Catalogul complet nu poate fi încărcat."
        ) from exc

    try:
        metadata = json.loads(inspected.stdout)[0]
        container_environment = _environment_by_name(metadata["Config"]["Env"])
        port_bindings = metadata["HostConfig"]["PortBindings"][POSTGRES_PORT]
        host_port = port_bindings[0]["HostPort"]
        database = container_environment["POSTGRES_DB"]
        user = container_environment["POSTGRES_USER"]
        password = container_environment["POSTGRES_PASSWORD"]
        is_running = bool(metadata["State"]["Running"])
        if not host_port.isdigit() or not all((database, user, password)):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LocalCatalogueError(
            f"Containerul «{container}» nu are contractul PostgreSQL local așteptat."
        ) from exc

    if not is_running:
        try:
            subprocess.run(
                ["docker", "start", container],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise LocalCatalogueError(
                f"Containerul PostgreSQL «{container}» nu a putut fi pornit."
            ) from exc

    connection = {
        "CASAMEA_DB_ENGINE": "postgresql",
        "CASAMEA_POSTGRES_DB": database,
        "CASAMEA_POSTGRES_USER": user,
        "CASAMEA_POSTGRES_PASSWORD": password,
        "CASAMEA_POSTGRES_HOST": "127.0.0.1",
        "CASAMEA_POSTGRES_PORT": host_port,
    }
    target_environ.update(connection)
    _wait_for_catalogue_database(connection)
    return True


def _environment_by_name(entries: list[str]) -> Mapping[str, str]:
    """Parse Docker environment entries without logging their values."""

    return dict(entry.split("=", 1) for entry in entries if "=" in entry)


def _wait_for_catalogue_database(connection: Mapping[str, str]) -> None:
    """Wait briefly for PostgreSQL startup and fail with an actionable message."""

    error: Exception | None = None
    for _ in range(40):
        try:
            with psycopg.connect(
                dbname=connection["CASAMEA_POSTGRES_DB"],
                user=connection["CASAMEA_POSTGRES_USER"],
                password=connection["CASAMEA_POSTGRES_PASSWORD"],
                host=connection["CASAMEA_POSTGRES_HOST"],
                port=connection["CASAMEA_POSTGRES_PORT"],
                connect_timeout=2,
            ) as database_connection:
                with database_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM services_cataloguescope "
                        "WHERE current_run_id IS NOT NULL"
                    )
                    if cursor.fetchone()[0] != 42:
                        raise LocalCatalogueError(
                            "Baza locală nu conține cele 42 de cataloage județene active."
                        )
                return
        except LocalCatalogueError:
            raise
        except psycopg.Error as exc:
            error = exc
            time.sleep(0.25)

    raise LocalCatalogueError(
        "PostgreSQL a pornit, dar catalogul local nu a devenit disponibil în 10 secunde."
    ) from error
