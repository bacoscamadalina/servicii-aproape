#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in {
        "runserver",
        "migrate_catalogue",
        "export_managed_cloud_seed",
    }:
        from config.local_catalogue import (
            LocalCatalogueError,
            configure_runserver_catalogue_from_local_container,
        )

        try:
            configured = configure_runserver_catalogue_from_local_container()
        except LocalCatalogueError as exc:
            raise SystemExit(f"Catalog local indisponibil: {exc}") from exc
        if configured:
            print("Catalog local: PostgreSQL complet, 42 de județe.")
        if command == "migrate_catalogue":
            # This explicit alias selects the same PostgreSQL catalogue as runserver.
            # Plain ``migrate`` intentionally retains Django's normal SQLite default.
            sys.argv[1] = "migrate"

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
