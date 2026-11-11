import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0031_provider_development_demo_grant")]

    operations = [
        migrations.CreateModel(
            name="ProviderRepresentationEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "evidence_type",
                    models.CharField(
                        choices=[
                            ("onrc_document", "Document ONRC recent"),
                            ("signed_authorization", "Împuternicire semnată"),
                            ("company_document", "Document oficial al firmei"),
                        ],
                        max_length=32,
                    ),
                ),
                ("document", models.BinaryField(editable=False)),
                ("mime_type", models.CharField(max_length=32)),
                ("byte_size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("declaration_version", models.CharField(max_length=48)),
                ("declared_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "claim",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="representation_evidence",
                        to="services.providerclaimrequest",
                    ),
                ),
                (
                    "registration",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="representation_evidence",
                        to="services.providerregistrationrequest",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="providerrepresentationevidence",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(claim__isnull=False, registration__isnull=True)
                    | models.Q(claim__isnull=True, registration__isnull=False)
                ),
                name="representation_evidence_single_request",
            ),
        ),
        migrations.AddConstraint(
            model_name="providerrepresentationevidence",
            constraint=models.CheckConstraint(
                condition=models.Q(byte_size__gt=0),
                name="representation_evidence_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="providerrepresentationevidence",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(mime_type="")
                    & ~models.Q(sha256="")
                    & ~models.Q(declaration_version="")
                ),
                name="representation_evidence_metadata",
            ),
        ),
    ]
