import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("services", "0030_harden_unverified_provider_draft_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderDevelopmentDemoGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                ("internal_note", models.TextField(max_length=1200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "authorization_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="provider_development_demo_authorizations",
                        to="services.importrun",
                    ),
                ),
                (
                    "catalogue_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="provider_development_demo_catalogues",
                        to="services.importrun",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_provider_development_demo_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="development_demo_grant",
                        to="services.providerprofile",
                    ),
                ),
            ],
            options={
                "permissions": [
                    (
                        "manage_provider_development_demo",
                        "Poate administra accesul demonstrativ al furnizorilor",
                    )
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="providerdevelopmentdemogrant",
            constraint=models.CheckConstraint(
                condition=~models.Q(internal_note=""),
                name="provider_demo_grant_note_required",
            ),
        ),
    ]
