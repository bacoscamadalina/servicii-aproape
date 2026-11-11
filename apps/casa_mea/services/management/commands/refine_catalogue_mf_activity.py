"""Build version-2 county previews from verified MF predominant activity."""

import csv
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management.base import BaseCommand, CommandError

from services.catalogue_activation import audit_run_for_catalogue
from services.importers.onrc import _sha256
from services.importers.primary_activity import (
    audit_active_catalogue_against_primary_activity,
    build_primary_activity_index,
    load_known_caen_v2,
    prepare_refinement_runs,
    refine_run_from_shadow_index,
    verify_primary_activity_manifest,
)
from services.models import CatalogueScope, ImportRun


class Command(BaseCommand):
    help = "Construiește runuri v2 MF fail-closed și un plan atomic de preview."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--input-dir", required=True, type=Path)
        parser.add_argument("--caen-dictionary", required=True, type=Path)
        parser.add_argument("--onrc-manifest", required=True, type=Path)
        parser.add_argument("--plan-output", required=True, type=Path)
        parser.add_argument("--report-output", required=True, type=Path)
        parser.add_argument("--scratch-dir", type=Path)
        parser.add_argument(
            "--base-run-id",
            action="append",
            type=int,
            help=(
                "Run ONRC v1 neactivat folosit ca bază; repetat exact pentru toate "
                "cele 42 de județe. Pointerele curente rămân predecesorii swapului."
            ),
        )

    def handle(self, *args, **options):
        """Audit once, clone per county, postaudit, and write a CAS activation plan."""

        try:
            onrc_manifest = json.loads(options["onrc_manifest"].read_text(encoding="utf-8"))
            known_caen = load_known_caen_v2(
                options["caen_dictionary"],
                onrc_manifest["resources"]["caen_dictionary"]["sha256"],
            )
            manifest, paths, evidence_hash = verify_primary_activity_manifest(
                options["manifest"], options["input_dir"]
            )
            manifest_hash = _sha256(options["manifest"])
            scopes = list(
                CatalogueScope.objects.select_related("current_run")
                .filter(provider="ONRC").exclude(current_run=None).order_by("county")
            )
            if len(scopes) != 42:
                raise ValueError("Rafinarea necesită exact 42 de pointere active")
            predecessors = {scope.county: scope.current_run_id for scope in scopes}
            requested_base_ids = options["base_run_id"]
            if requested_base_ids:
                base_runs = list(
                    ImportRun.objects.select_related("snapshot")
                    .filter(pk__in=requested_base_ids).order_by("county")
                )
                if (
                    len(requested_base_ids) != 42
                    or len(base_runs) != 42
                    or len(set(requested_base_ids)) != 42
                    or len({run.county for run in base_runs}) != 42
                ):
                    raise ValueError(
                        "--base-run-id trebuie să indice exact 42 de runuri județene unice"
                    )
                active_run_ids = set(predecessors.values())
                overlap = active_run_ids.intersection(requested_base_ids)
                if overlap:
                    raise ValueError(
                        "Runurile de bază explicite trebuie să rămână neactivate"
                    )
            else:
                base_runs = [scope.current_run for scope in scopes]
            base_contract = {
                run.pk: (
                    run.scope_key,
                    run.state,
                    run.snapshot_id,
                    run.caen_mapping_version,
                    run.caen_mapping_hash,
                    run.status_policy_version,
                    run.locality_policy,
                    run.locality_rules_hash,
                )
                for run in base_runs
            }

            with TemporaryDirectory(dir=options["scratch_dir"]) as temporary_directory:
                database_path, source_counts = build_primary_activity_index(
                    paths, Path(temporary_directory)
                )
                shadow = audit_active_catalogue_against_primary_activity(
                    database_path,
                    known_caen,
                    _sha256(options["onrc_manifest"]),
                    base_runs=base_runs if requested_base_ids else None,
                )
                refreshed, _paths, refreshed_hash = verify_primary_activity_manifest(
                    options["manifest"], options["input_dir"]
                )
                if (
                    _sha256(options["manifest"]) != manifest_hash
                    or refreshed_hash != evidence_hash
                    or refreshed["dataset_year"] != manifest["dataset_year"]
                ):
                    raise ValueError("Sursele MF s-au schimbat în timpul scanării")
                current = dict(CatalogueScope.objects.filter(
                    provider="ONRC"
                ).values_list("county", "current_run_id"))
                if current != predecessors:
                    raise ValueError("Un pointer de catalog s-a schimbat în timpul scanării")
                refreshed_base_runs = list(
                    ImportRun.objects.select_related("snapshot")
                    .filter(pk__in=base_contract).order_by("county")
                )
                refreshed_contract = {
                    run.pk: (
                        run.scope_key,
                        run.state,
                        run.snapshot_id,
                        run.caen_mapping_version,
                        run.caen_mapping_hash,
                        run.status_policy_version,
                        run.locality_policy,
                        run.locality_rules_hash,
                    )
                    for run in refreshed_base_runs
                }
                if refreshed_contract != base_contract:
                    raise ValueError("Un run de bază s-a schimbat în timpul scanării")
                for run in refreshed_base_runs:
                    audit_run_for_catalogue(run)
                base_runs = refreshed_base_runs

                verified_resources = {
                    item["kind"]: {
                        "filename": item["filename"],
                        "size_bytes": item["size_bytes"],
                        "sha256": item["sha256"],
                        "url": item["url"],
                    }
                    for item in manifest["resources"]
                }
                _snapshot, target_runs = prepare_refinement_runs(
                    manifest=manifest,
                    manifest_sha256=manifest_hash,
                    verified_resources=verified_resources,
                    base_runs=base_runs,
                )
                results = []
                targets_by_county = {run.county: run for run in target_runs}
                for source_run in base_runs:
                    target_run = targets_by_county[source_run.county]
                    counters, changed = refine_run_from_shadow_index(
                        source_run, target_run, database_path
                    )
                    audited = audit_run_for_catalogue(target_run)
                    results.append({
                        "county": target_run.county,
                        "base_run_id": source_run.pk,
                        "run_id": target_run.pk,
                        "scope_key": target_run.scope_key,
                        "changed": changed,
                        "counters": counters,
                        "audited": audited,
                    })

            plan = [{
                "run_id": item["run_id"],
                "expected_scope_key": item["scope_key"],
                "expected_previous_run_id": predecessors[item["county"]],
            } for item in results]
            report = {
                "report_schema_version": 1,
                "mf_manifest_sha256": manifest_hash,
                "mf_evidence_sha256": evidence_hash,
                "source_counts": dict(sorted(source_counts.items())),
                "shadow": shadow,
                "runs": results,
                "activation_plan": plan,
                "visibility": "not_activated",
                "publication_approvals_inherited": 0,
            }
            for path, payload in (
                (options["plan_output"], plan),
                (options["report_output"], report),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(path)
            self.stdout.write(json.dumps({
                "runs": len(results),
                "staged_businesses": sum(
                    row["counters"]["staged_businesses"] for row in results
                ),
                "plan": str(options["plan_output"]),
                "report": str(options["report_output"]),
            }, ensure_ascii=False, sort_keys=True))
        except (
            csv.Error, json.JSONDecodeError, KeyError, OSError, sqlite3.Error,
            TypeError, ValueError,
        ) as error:
            raise CommandError(str(error)) from error
