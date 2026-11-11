"""Deployment safety tests; no Docker daemon or private database is required."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from deploy.restore import restore_private_backup, validate_backup
from deploy.backup_local import export_private_backup
from deploy.verify_backup import verify_private_backup
from services.catalogue_activation import (
    activate_catalogue_scope,
    record_publication_approval,
    ACKNOWLEDGEMENT,
    PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
)
from services.models import CatalogueScope, PublicationApproval
from services.production_readiness import ANOMALY_CODES, audit_production_readiness
from services.test_catalogue_activation import CatalogueFixtureMixin


class ProductionSettingsTests(SimpleTestCase):
    """Production settings are isolated from the development switch and secrets."""

    def settings_process(self, **changes):
        """Read settings in a clean interpreter without changing the test process."""
        environment = {key: value for key, value in os.environ.items() if not key.startswith("CASAMEA_")}
        environment.update({
            "CASAMEA_SECRET_KEY": "test-only-secret-" * 5,
            "CASAMEA_DOMAIN": "example.test", "CASAMEA_DB_ENGINE": "postgresql",
            "CASAMEA_POSTGRES_DB": "test", "CASAMEA_POSTGRES_USER": "test",
            "CASAMEA_POSTGRES_PASSWORD": "test-only",
            "CASAMEA_EMAIL_HOST": "smtp.example.test",
            "CASAMEA_EMAIL_PORT": "587",
            "CASAMEA_EMAIL_HOST_USER": "smtp-user",
            "CASAMEA_EMAIL_HOST_PASSWORD": "smtp-password",
            "CASAMEA_DEFAULT_FROM_EMAIL": "ServiciiAproape <no-reply@example.test>",
            "CASAMEA_LEGAL_OPERATOR_NAME": "Example Operator SRL",
            "CASAMEA_LEGAL_OPERATOR_ADDRESS": "Strada Exemplu 1, Iași",
            "CASAMEA_PRIVACY_EMAIL": "privacy@example.test",
            "CASAMEA_COMMERCIAL_EMAIL": "contact@example.test",
            "CASAMEA_RETENTION_UNVERIFIED_CLAIM_DAYS": "30",
            "CASAMEA_RETENTION_REJECTED_CLAIM_DAYS": "365",
            "CASAMEA_RETENTION_CLOSED_REPORT_DAYS": "365",
            "CASAMEA_RETENTION_CLOSED_DATA_REQUEST_DAYS": "1095",
            "CASAMEA_RETENTION_MANAGED_SITE_INQUIRY_DAYS": "365",
            **changes,
        })
        return subprocess.run([
            sys.executable, "-c", "from config import production as s; "
            "assert not s.DEBUG; assert s.SESSION_COOKIE_SECURE; "
            "assert s.ALLOWED_HOSTS == ['example.test']; "
            "assert s.EMAIL_BACKEND.endswith('smtp.EmailBackend'); "
            "assert s.SECURE_SSL_REDIRECT; "
            "assert 'services.middleware.ProductionBrowserSecurityMiddleware' in s.MIDDLEWARE",
        ], env=environment, capture_output=True, text=True)

    def test_debug_environment_cannot_enable_preview(self):
        result = self.settings_process(CASAMEA_DEBUG="1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_weak_secrets_are_rejected(self):
        for secret in ("", "short", "django-insecure-" + "x" * 60):
            with self.subTest(secret=secret):
                self.assertNotEqual(self.settings_process(CASAMEA_SECRET_KEY=secret).returncode, 0)

    def test_sqlite_fallback_and_empty_password_are_rejected(self):
        self.assertNotEqual(self.settings_process(CASAMEA_DB_ENGINE="sqlite").returncode, 0)
        self.assertNotEqual(self.settings_process(CASAMEA_POSTGRES_PASSWORD="").returncode, 0)

    def test_host_injection_and_wildcard_are_rejected(self):
        for domain in ("*", "https://example.test", "example.test:443", "example.test\nfile_server"):
            with self.subTest(domain=domain):
                self.assertNotEqual(self.settings_process(CASAMEA_DOMAIN=domain).returncode, 0)

    def test_incomplete_or_invalid_smtp_is_rejected(self):
        invalid = (
            {"CASAMEA_EMAIL_HOST": ""},
            {"CASAMEA_EMAIL_HOST": "https://smtp.example.test"},
            {"CASAMEA_EMAIL_PORT": "0"},
            {"CASAMEA_EMAIL_PORT": "not-a-port"},
            {"CASAMEA_EMAIL_HOST_USER": ""},
            {"CASAMEA_EMAIL_HOST_PASSWORD": ""},
            {"CASAMEA_DEFAULT_FROM_EMAIL": "not-an-email"},
            {"CASAMEA_DEFAULT_FROM_EMAIL": "valid@example.test\nBcc: hidden@example.test"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertNotEqual(self.settings_process(**changes).returncode, 0)

    def test_incomplete_legal_identity_is_rejected(self):
        invalid = (
            {"CASAMEA_LEGAL_OPERATOR_NAME": ""},
            {"CASAMEA_LEGAL_OPERATOR_ADDRESS": ""},
            {"CASAMEA_PRIVACY_EMAIL": "not-an-email"},
            {"CASAMEA_COMMERCIAL_EMAIL": "not-an-email"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertNotEqual(self.settings_process(**changes).returncode, 0)

    def test_managed_site_price_must_exceed_the_essential_price(self):
        for price in ("invalid", "49", "0", "10001"):
            with self.subTest(price=price):
                self.assertNotEqual(
                    self.settings_process(
                        CASAMEA_MANAGED_SITE_MONTHLY_PRICE_RON=price
                    ).returncode,
                    0,
                )

    def test_missing_or_invalid_retention_policy_is_rejected(self):
        invalid = (
            {"CASAMEA_RETENTION_UNVERIFIED_CLAIM_DAYS": ""},
            {"CASAMEA_RETENTION_UNVERIFIED_CLAIM_DAYS": "6"},
            {"CASAMEA_RETENTION_REJECTED_CLAIM_DAYS": "not-a-number"},
            {"CASAMEA_RETENTION_CLOSED_REPORT_DAYS": "3651"},
            {"CASAMEA_RETENTION_CLOSED_DATA_REQUEST_DAYS": "364"},
            {"CASAMEA_RETENTION_MANAGED_SITE_INQUIRY_DAYS": "29"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertNotEqual(self.settings_process(**changes).returncode, 0)


class ManagedCloudDevelopmentSettingsTests(SimpleTestCase):
    """The persistent dev target must need neither a domain nor external e-mail."""

    def test_development_cloud_uses_console_email_and_full_packaged_catalogue(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("CASAMEA_")
        }
        environment.update(
            {
                "CASAMEA_DB_ENGINE": "postgresql",
                "CASAMEA_POSTGRES_DB": "test",
                "CASAMEA_POSTGRES_USER": "test",
                "CASAMEA_POSTGRES_PASSWORD": "test",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from config import managed_cloud_development as s; "
                "assert s.DEBUG and s.ALLOWED_HOSTS == ['*']; "
                "assert s.SECURE_PROXY_SSL_HEADER == "
                "('HTTP_X_FORWARDED_PROTO', 'https'); "
                "assert s.CSRF_TRUSTED_ORIGINS == "
                "['https://*.apps.doiplusdoi.ro']; "
                "assert not s.SESSION_COOKIE_SECURE and not s.CSRF_COOKIE_SECURE; "
                "assert s.EMAIL_BACKEND.endswith('console.EmailBackend'); "
                "assert s.PACKAGED_CATALOGUE and not s.MANAGED_CLOUD_DEPLOY_CHECK; "
                "assert 'whitenoise.middleware.WhiteNoiseMiddleware' in s.MIDDLEWARE",
            ],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


@override_settings(
    ALLOWED_HOSTS=["*"],
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    CSRF_TRUSTED_ORIGINS=["https://*.apps.doiplusdoi.ro"],
)
class ManagedCloudDevelopmentCsrfTests(TestCase):
    """Admin forms accept only the managed platform's HTTPS development origins."""

    host = "casamea-example-dev.apps.doiplusdoi.ro"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_admin_post_accepts_platform_origin_behind_https_proxy(self):
        page = self.client.get(
            "/admin/login/",
            HTTP_HOST=self.host,
            HTTP_X_FORWARDED_PROTO="https",
        )
        token = page.cookies["csrftoken"].value
        response = self.client.post(
            "/admin/login/",
            {"csrfmiddlewaretoken": token},
            HTTP_HOST=self.host,
            HTTP_ORIGIN=f"https://{self.host}",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_post_rejects_unrelated_https_origin(self):
        page = self.client.get(
            "/admin/login/",
            HTTP_HOST=self.host,
            HTTP_X_FORWARDED_PROTO="https",
        )
        response = self.client.post(
            "/admin/login/",
            {"csrfmiddlewaretoken": page.cookies["csrftoken"].value},
            HTTP_HOST=self.host,
            HTTP_ORIGIN="https://attacker.example",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(response.status_code, 403)

class BackupValidationTests(SimpleTestCase):
    """Corrupt/mismatched bundles never reach database restore or media installation."""

    def setUp(self):
        """Create a tiny synthetic bundle, not a copy of user data."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "services/data").mkdir(parents=True)
        (self.root / "services/data/localities.json").write_bytes(b"{}")
        (self.root / "database.dump").write_bytes(b"synthetic-dump")
        self.media = self.root / "media"
        self.media.mkdir()
        self.write_archive_and_manifest("portfolio/example.txt")

    def write_archive_and_manifest(self, member_name):
        """Generate fixture artifacts and the corresponding checksum manifest."""
        with tarfile.open(self.root / "private_media.tar.gz", "w:gz") as archive:
            item = tarfile.TarInfo(member_name)
            item.size = 1
            archive.addfile(item, io.BytesIO(b"x"))
        self.manifest = {
            "schema": 1, "postgres_major": 17, "private": True,
            "files": {
                name: {"bytes": (self.root / name).stat().st_size,
                       "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest()}
                for name in ("database.dump", "private_media.tar.gz")
            },
            "source_artifacts": {"services/data/localities.json": hashlib.sha256(b"{}").hexdigest()},
        }
        self.save_manifest()

    def save_manifest(self):
        """Persist the altered synthetic manifest for negative tests."""
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def test_valid_bundle(self):
        self.assertEqual(validate_backup(self.root, self.root), self.manifest)

    def test_reexport_omits_deployment_marker_and_keeps_private_permissions(self):
        (self.media / ".restore-complete").write_bytes(b"old-marker")
        (self.media / "portfolio.txt").write_bytes(b"synthetic")

        def run_fixture(command, **kwargs):
            """Replace Docker with deterministic synthetic outputs."""
            if command[1] == "inspect":
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps([
                    {"Config": {"Env": ["POSTGRES_DB=test", "POSTGRES_USER=test"]}}
                ]))
            if "psql" in command:
                return subprocess.CompletedProcess(command, 0, stdout="170000\n")
            kwargs["stdout"].write(b"synthetic-sql")
            return subprocess.CompletedProcess(command, 0)

        destination = self.root / "export"
        with patch("deploy.backup_local.subprocess.run", side_effect=run_fixture):
            with patch("deploy.backup_local.APP_ROOT", self.root):
                export_private_backup(destination, "synthetic-container", self.media)
        with tarfile.open(destination / "private_media.tar.gz") as archive:
            self.assertEqual(archive.getnames(), ["portfolio.txt"])
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual((destination / "database.dump").stat().st_mode & 0o777, 0o600)
        manifest = validate_backup(destination, self.root)
        self.assertEqual(manifest["schema"], 2)
        self.assertEqual(
            manifest["media"], {"regular_files": 1, "uncompressed_bytes": 9}
        )

    @patch("deploy.verify_backup.subprocess.run")
    def test_structural_and_freshness_verification_is_identity_free(self, run):
        created_at = datetime(2026, 9, 1, 8, tzinfo=datetime_timezone.utc)
        self.manifest["created_at"] = created_at.isoformat()
        self.save_manifest()

        report = verify_private_backup(
            self.root,
            self.root,
            max_age_hours=24,
            now=created_at + timedelta(hours=23),
        )

        self.assertTrue(report["valid"])
        self.assertEqual(report["age_seconds"], 23 * 3600)
        self.assertEqual(report["media_regular_files"], 1)
        self.assertNotIn("portfolio", json.dumps(report))
        run.assert_called_once_with(
            ["pg_restore", "--list", str(self.root / "database.dump")],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    @patch("deploy.verify_backup.subprocess.run")
    def test_verifier_rejects_stale_or_structurally_invalid_dump(self, run):
        created_at = datetime(2026, 9, 1, 8, tzinfo=datetime_timezone.utc)
        self.manifest["created_at"] = created_at.isoformat()
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "older"):
            verify_private_backup(
                self.root,
                self.root,
                max_age_hours=24,
                now=created_at + timedelta(hours=25),
            )

        run.side_effect = subprocess.CalledProcessError(1, "pg_restore")
        with self.assertRaisesRegex(ValueError, "dump structure"):
            verify_private_backup(self.root, self.root)

    @patch("deploy.verify_backup.subprocess.run")
    def test_schema_two_media_inventory_is_rechecked(self, run):
        self.manifest["schema"] = 2
        self.manifest["media"] = {"regular_files": 2, "uncompressed_bytes": 1}
        self.save_manifest()

        with self.assertRaisesRegex(ValueError, "inventory differs"):
            verify_private_backup(self.root, self.root)
        run.assert_not_called()

    def test_corrupt_dump(self):
        (self.root / "database.dump").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Corrupt backup"):
            validate_backup(self.root, self.root)

    def test_changed_source_pin(self):
        (self.root / "services/data/localities.json").write_bytes(b"[]")
        with self.assertRaisesRegex(ValueError, "source pin differs"):
            validate_backup(self.root, self.root)

    def test_missing_artifact_and_wrong_major(self):
        self.manifest["files"].pop("database.dump")
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            validate_backup(self.root, self.root)
        self.manifest["postgres_major"] = 16
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_backup(self.root, self.root)

    @patch.dict(os.environ, {"CASAMEA_POSTGRES_DB": "test", "CASAMEA_POSTGRES_USER": "test",
                            "CASAMEA_POSTGRES_PASSWORD": "test", "CASAMEA_POSTGRES_HOST": "db"})
    @patch("deploy.restore.subprocess.run")
    @patch("deploy.restore.psycopg.connect")
    def test_nonempty_targets_and_unsafe_archive_are_rejected(self, connect, run):
        database = connect.return_value.__enter__.return_value
        database.execute.return_value.fetchone.return_value = (True,)
        with self.assertRaisesRegex(ValueError, "must both be empty"):
            restore_private_backup(self.root, self.media, self.root)
        database.execute.return_value.fetchone.return_value = (False,)
        (self.media / "existing").write_bytes(b"preserve")
        with self.assertRaisesRegex(ValueError, "must both be empty"):
            restore_private_backup(self.root, self.media, self.root)
        self.assertEqual((self.media / "existing").read_bytes(), b"preserve")
        empty_media = self.root / "empty_media"
        empty_media.mkdir()
        self.write_archive_and_manifest("../outside")
        with self.assertRaisesRegex(ValueError, "Unsafe media"):
            restore_private_backup(self.root, empty_media, self.root)
        self.assertEqual(list(empty_media.iterdir()), [])
        run.assert_not_called()

    @patch.dict(os.environ, {"CASAMEA_POSTGRES_DB": "test", "CASAMEA_POSTGRES_USER": "test",
                            "CASAMEA_POSTGRES_PASSWORD": "test", "CASAMEA_POSTGRES_HOST": "db"})
    @patch("deploy.restore.os.chown")
    @patch("deploy.restore.psycopg.connect")
    def test_failed_sql_or_media_install_never_marks_restore_complete(self, connect, chown):
        database = connect.return_value.__enter__.return_value
        database.execute.return_value.fetchone.return_value = (False,)
        original = (self.root / "database.dump").read_bytes()
        with patch("deploy.restore.subprocess.run", side_effect=subprocess.CalledProcessError(1, "pg_restore")):
            with self.assertRaises(subprocess.CalledProcessError):
                restore_private_backup(self.root, self.media, self.root)
        self.assertEqual(list(self.media.iterdir()), [])
        with patch("deploy.restore.subprocess.run") as restore:
            with patch("deploy.restore.shutil.move", side_effect=OSError("test filesystem failure")):
                with self.assertRaisesRegex(OSError, "filesystem failure"):
                    restore_private_backup(self.root, self.media, self.root)
            restore.assert_called_once()
        self.assertFalse((self.media / ".restore-complete").exists())
        self.assertEqual((self.root / "database.dump").read_bytes(), original)


class CatalogueDeploymentTests(CatalogueFixtureMixin, TestCase):
    """Copy verification must not implicitly grant publication."""

    def test_empty_database_refused(self):
        with self.assertRaisesRegex(CommandError, "42 ONRC"):
            call_command("verify_cloud_catalogue")

    @override_settings(DEBUG=False)
    def test_existing_preview_reported_but_never_published(self):
        self.build_catalogue(total=2)
        scope, _ = activate_catalogue_scope(
            run=self.run, actor_username=self.actor.username,
            expected_scope_key=self.run.scope_key,
            acknowledgement=ACKNOWLEDGEMENT, visibility="internal_preview",
        )
        output, errors = io.StringIO(), io.StringIO()
        with patch("services.management.commands.verify_cloud_catalogue.county_choices", return_value=(("Iași", "Iași"),)):
            call_command("verify_cloud_catalogue", stdout=output, stderr=errors)
        report = json.loads(output.getvalue())
        self.assertEqual(report["current_registry_rows"], 2)
        self.assertEqual(report["readable_counties_in_this_environment"], 0)
        self.assertIn("NOT publicly approved", errors.getvalue())
        scope.refresh_from_db()
        self.assertEqual(scope.visibility, "internal_preview")
        self.assertIsNone(scope.current_approval_id)

    def test_run_source_drift_is_rejected(self):
        self.build_catalogue(total=2)
        self.activate_preview()
        self.run.snapshot.state = "rejected"
        self.run.snapshot.save(update_fields=("state",))
        with patch("services.management.commands.verify_cloud_catalogue.county_choices", return_value=(("Iași", "Iași"),)):
            with self.assertRaisesRegex(CommandError, "integrity failed"):
                call_command("verify_cloud_catalogue")


class ProductionReadinessTests(CatalogueFixtureMixin, TestCase):
    """Mutable public gates are audited independently from container liveness."""

    def setUp(self):
        self.build_catalogue(total=2)
        permission = Permission.objects.get(codename="approve_catalogue_publication")
        self.actor.user_permissions.add(permission)

    def publish(self):
        approval = record_publication_approval(
            run=self.run,
            actor_username=self.actor.username,
            review_reference="synthetic production readiness review",
            review_due_at=timezone.now() + timedelta(days=30),
            acknowledgement=PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
        )
        activate_catalogue_scope(
            run=self.run,
            visibility=CatalogueScope.Visibility.PUBLIC,
            actor_username=self.actor.username,
            expected_scope_key=self.run.scope_key,
            acknowledgement=ACKNOWLEDGEMENT,
        )
        return approval

    def test_public_launch_area_passes_without_writes(self):
        self.publish()
        with CaptureQueriesContext(connection) as queries:
            report = audit_production_readiness(counties=("Iași",))
        self.assertTrue(report.is_valid)
        self.assertEqual(report.ready_counties, 1)
        mutating = ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE ", "DROP ")
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(mutating) for query in queries))

    def test_preview_and_expired_approval_fail_with_distinct_codes(self):
        self.activate_preview()
        preview = dict(audit_production_readiness(counties=("Iași",)).anomaly_counts)
        self.assertEqual(preview["not_public"], 1)

        approval = self.publish()
        PublicationApproval.objects.filter(pk=approval.pk).update(
            review_due_at=timezone.now() - timedelta(seconds=1)
        )
        expired = dict(audit_production_readiness(counties=("Iași",)).anomaly_counts)
        self.assertEqual(expired["approval_invalid"], 1)

    def test_revoked_approval_and_run_drift_fail_closed(self):
        approval = self.publish()
        PublicationApproval.objects.filter(pk=approval.pk).update(
            state=PublicationApproval.State.REVOKED,
            revoked_at=timezone.now(),
            revoked_by=self.actor,
        )
        revoked = dict(audit_production_readiness(counties=("Iași",)).anomaly_counts)
        self.assertEqual(revoked["approval_invalid"], 1)

        PublicationApproval.objects.filter(pk=approval.pk).update(
            state=PublicationApproval.State.APPROVED,
            revoked_at=None,
            revoked_by=None,
        )
        self.snapshot.state = "rejected"
        self.snapshot.save(update_fields=("state",))
        drift = dict(audit_production_readiness(counties=("Iași",)).anomaly_counts)
        self.assertEqual(drift["run_integrity_failed"], 1)

    def test_cross_county_pointer_fails_before_run_audit(self):
        self.publish()
        self.run.county = "Cluj"
        self.run.save(update_fields=("county",))
        report = dict(audit_production_readiness(counties=("Iași",)).anomaly_counts)
        self.assertEqual(report["run_county_mismatch"], 1)

    def test_report_triage_integrity_is_part_of_launch_gate(self):
        self.publish()
        triage = patch("services.production_readiness.audit_public_provider_report_triage")
        with triage as mocked:
            mocked.return_value.is_valid = False
            report = audit_production_readiness(counties=("Iași",))
        self.assertEqual(dict(report.anomaly_counts)["triage_integrity_failed"], 1)
        self.assertFalse(report.is_valid)

    def test_personal_data_request_integrity_is_part_of_launch_gate(self):
        self.publish()
        privacy_audit = patch(
            "services.production_readiness.audit_data_subject_requests"
        )
        with privacy_audit as mocked:
            mocked.return_value.is_valid = False
            report = audit_production_readiness(counties=("Iași",))
        self.assertEqual(
            dict(report.anomaly_counts)["data_subject_integrity_failed"], 1
        )
        self.assertFalse(report.is_valid)

    def test_retention_integrity_is_part_of_launch_gate(self):
        self.publish()
        with patch("services.production_readiness.audit_retention_integrity") as mocked:
            mocked.return_value.is_valid = False
            report = audit_production_readiness(counties=("Iași",))
        self.assertEqual(dict(report.anomaly_counts)["retention_integrity_failed"], 1)
        self.assertFalse(report.is_valid)

    def test_missing_scope_is_aggregate_and_identity_free(self):
        report = audit_production_readiness(counties=("Cluj",)).as_dict()
        self.assertEqual(report["anomalies"]["missing_scope"], 1)
        self.assertNotIn("Cluj", json.dumps(report))

    def test_command_checks_restore_marker_and_emits_json(self):
        self.publish()
        with tempfile.TemporaryDirectory() as media_root:
            Path(media_root, ".restore-complete").touch()
            output = io.StringIO()
            with override_settings(MEDIA_ROOT=media_root):
                call_command("audit_production_readiness", "--county", "Iași", stdout=output)
        report = json.loads(output.getvalue())
        self.assertTrue(report["valid"])
        self.assertFalse(report["deployment"]["pending_migrations"])

    def test_command_rejects_invalid_launch_allowlist(self):
        for counties in (("Iași", "Iași"), ("Atlantida",)):
            with self.subTest(counties=counties):
                with self.assertRaisesRegex(CommandError, "official county"):
                    arguments = tuple(
                        value for county in counties for value in ("--county", county)
                    )
                    call_command("audit_production_readiness", *arguments)

    def test_command_fails_without_restore_marker_after_emitting_report(self):
        self.publish()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with self.assertRaisesRegex(CommandError, "readiness audit failed"):
                    call_command(
                        "audit_production_readiness", "--county", "Iași", stdout=output
                    )
        report = json.loads(output.getvalue())
        self.assertFalse(report["valid"])
        self.assertFalse(report["deployment"]["restore_complete"])

    def test_pending_migrations_skip_current_schema_queries(self):
        output = io.StringIO()
        migrations = patch(
            "services.management.commands.audit_production_readiness.MigrationExecutor"
        )
        catalogue = patch(
            "services.management.commands.audit_production_readiness.audit_production_readiness"
        )
        with migrations as mocked_migrations, catalogue as mocked_catalogue:
            executor = mocked_migrations.return_value
            executor.loader.graph.leaf_nodes.return_value = [("services", "future")]
            executor.migration_plan.return_value = [("future", False)]
            with self.assertRaisesRegex(CommandError, "readiness audit failed"):
                call_command(
                    "audit_production_readiness", "--county", "Iași", stdout=output
                )
        mocked_catalogue.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertFalse(report["catalogue_checked"])
        self.assertTrue(report["deployment"]["pending_migrations"])
        self.assertEqual(set(report["anomalies"]), set(ANOMALY_CODES))
