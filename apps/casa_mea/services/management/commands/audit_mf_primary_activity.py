"""Generate a mutation-free national MF predominant-activity shadow report."""

import csv
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from services.importers.onrc import _sha256
from services.importers.primary_activity import (
    audit_active_catalogue_against_primary_activity,
    build_primary_activity_index,
    load_known_caen_v2,
    verify_primary_activity_manifest,
)


class Command(BaseCommand):
    help = "Auditează shadow activitatea preponderentă MF 2024; nu schimbă pointere."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--caen-dictionary", required=True, type=Path)
        parser.add_argument("--onrc-manifest", required=True, type=Path)
        parser.add_argument("--output", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)

    def handle(self, *args, **options):
        """Verify, index, audit, reverify, then atomically write the report."""

        try:
            onrc_manifest = json.loads(
                options["onrc_manifest"].read_text(encoding="utf-8")
            )
            expected_caen_hash = onrc_manifest["resources"]["caen_dictionary"][
                "sha256"
            ]
            known_caen = load_known_caen_v2(
                options["caen_dictionary"], expected_caen_hash
            )
            manifest, paths, evidence_hash = verify_primary_activity_manifest(
                options["manifest"], options["input_dir"]
            )
            manifest_hash = _sha256(options["manifest"])
            with TemporaryDirectory(
                dir=options["scratch_dir"]
            ) as temporary_directory:
                database_path, source_counts = build_primary_activity_index(
                    paths, Path(temporary_directory)
                )
                report = audit_active_catalogue_against_primary_activity(
                    database_path, known_caen, _sha256(options["onrc_manifest"])
                )
                report.update(
                    {
                        "generated_at": timezone.now().isoformat(),
                        "mf_manifest_sha256": manifest_hash,
                        "mf_evidence_sha256": evidence_hash,
                        "mf_dataset_url": manifest["dataset_url"],
                        "mf_license": manifest["license"],
                        "source_counts": dict(sorted(source_counts.items())),
                        "onrc_manifest_sha256": _sha256(options["onrc_manifest"]),
                        "caen_dictionary_sha256": expected_caen_hash,
                    }
                )
                refreshed, _paths, refreshed_hash = verify_primary_activity_manifest(
                    options["manifest"], options["input_dir"]
                )
                if (
                    _sha256(options["manifest"]) != manifest_hash
                    or refreshed_hash != evidence_hash
                    or refreshed["dataset_year"] != manifest["dataset_year"]
                ):
                    raise ValueError("Sursele MF s-au schimbat în timpul auditului")

            output = options["output"]
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary_output = output.with_suffix(output.suffix + ".tmp")
            temporary_output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary_output.replace(output)
            self.stdout.write(json.dumps({
                "base_candidates": report["base_candidates"],
                "decision_counts": report["decision_counts"],
                "output": str(output),
                "retention_percent": report["retention_percent"],
            }, ensure_ascii=False, sort_keys=True))
        except (
            csv.Error,
            json.JSONDecodeError,
            KeyError,
            OSError,
            sqlite3.Error,
            TypeError,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
