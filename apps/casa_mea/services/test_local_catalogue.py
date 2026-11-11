"""Tests for automatic local catalogue startup used only by ``runserver``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import manage

from config.local_catalogue import (
    LocalCatalogueError,
    configure_runserver_catalogue_from_local_container,
)


def _inspect_result(*, running: bool) -> subprocess.CompletedProcess[str]:
    """Return minimal Docker metadata with a deliberately opaque password."""

    return subprocess.CompletedProcess(
        args=["docker", "inspect", "casamea-postgres-pilot"],
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "Config": {
                        "Env": [
                            "POSTGRES_DB=casamea",
                            "POSTGRES_USER=casamea",
                            "POSTGRES_PASSWORD=opaque-secret",
                        ]
                    },
                    "HostConfig": {
                        "PortBindings": {
                            "5432/tcp": [{"HostPort": "55432"}]
                        }
                    },
                    "State": {"Running": running},
                }
            ]
        ),
        stderr="",
    )


class LocalCatalogueConfigurationTests(TestCase):
    """Keep local convenience isolated from explicit database configuration."""

    @patch("config.local_catalogue._wait_for_catalogue_database")
    @patch("config.local_catalogue.subprocess.run")
    def test_starts_stopped_container_and_sets_connection(
        self, run: MagicMock, wait: MagicMock
    ) -> None:
        run.side_effect = [_inspect_result(running=False), MagicMock()]
        environment: dict[str, str] = {}

        configured = configure_runserver_catalogue_from_local_container(environment)

        self.assertTrue(configured)
        self.assertEqual(environment["CASAMEA_DB_ENGINE"], "postgresql")
        self.assertEqual(environment["CASAMEA_POSTGRES_PORT"], "55432")
        self.assertEqual(environment["CASAMEA_POSTGRES_PASSWORD"], "opaque-secret")
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["docker", "inspect", "casamea-postgres-pilot"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
                call(
                    ["docker", "start", "casamea-postgres-pilot"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
            ],
        )
        wait.assert_called_once()

    @patch("config.local_catalogue._wait_for_catalogue_database")
    @patch("config.local_catalogue.subprocess.run")
    def test_running_container_is_not_started_again(
        self, run: MagicMock, wait: MagicMock
    ) -> None:
        run.return_value = _inspect_result(running=True)

        self.assertTrue(configure_runserver_catalogue_from_local_container({}))

        run.assert_called_once()
        wait.assert_called_once()

    @patch("config.local_catalogue.subprocess.run")
    def test_explicit_database_configuration_wins(self, run: MagicMock) -> None:
        environment = {"CASAMEA_DB_ENGINE": "sqlite"}

        configured = configure_runserver_catalogue_from_local_container(environment)

        self.assertFalse(configured)
        run.assert_not_called()

    @patch("config.local_catalogue.subprocess.run")
    def test_missing_container_fails_instead_of_using_empty_sqlite(
        self, run: MagicMock
    ) -> None:
        run.side_effect = subprocess.CalledProcessError(1, ["docker", "inspect"])

        with self.assertRaisesRegex(LocalCatalogueError, "nu este disponibil"):
            configure_runserver_catalogue_from_local_container({})

    @patch("config.local_catalogue.subprocess.run")
    def test_malformed_container_contract_is_rejected(self, run: MagicMock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["docker", "inspect"], returncode=0, stdout="[{}]", stderr=""
        )

        with self.assertRaisesRegex(LocalCatalogueError, "contractul PostgreSQL"):
            configure_runserver_catalogue_from_local_container({})


class LocalCatalogueManagementCommandTests(TestCase):
    """Route only the explicit catalogue migration alias to PostgreSQL discovery."""

    @patch("django.core.management.execute_from_command_line")
    @patch("config.local_catalogue.configure_runserver_catalogue_from_local_container")
    def test_migrate_catalogue_selects_container_and_rewrites_command(
        self, configure: MagicMock, execute: MagicMock
    ) -> None:
        configure.return_value = True
        arguments = ["manage.py", "migrate_catalogue", "--plan"]

        with patch.object(sys, "argv", arguments), patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings"}
        ):
            manage.main()

        configure.assert_called_once_with()
        execute.assert_called_once_with(["manage.py", "migrate", "--plan"])

    @patch("django.core.management.execute_from_command_line")
    @patch("config.local_catalogue.configure_runserver_catalogue_from_local_container")
    def test_plain_migrate_does_not_select_catalogue_container(
        self, configure: MagicMock, execute: MagicMock
    ) -> None:
        arguments = ["manage.py", "migrate", "--plan"]

        with patch.object(sys, "argv", arguments), patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings"}
        ):
            manage.main()

        configure.assert_not_called()
        execute.assert_called_once_with(arguments)
