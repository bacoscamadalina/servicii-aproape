from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0029_allow_unverified_provider_offering_drafts")]

    operations = [
        migrations.RemoveConstraint(
            model_name="providerserviceareadraft",
            name="provider_draft_source_contract",
        ),
        migrations.AddConstraint(
            model_name="providerserviceareadraft",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        revision=0,
                        authorization_run__isnull=True,
                        siruta_catalogue_version="",
                        siruta_catalogue_sha256="",
                        reviewed_revision__isnull=True,
                        review_state="draft",
                    )
                    | (
                        models.Q(revision__gt=0)
                        & ~models.Q(siruta_catalogue_version="")
                        & ~models.Q(siruta_catalogue_sha256="")
                        & (
                            models.Q(
                                review_state="draft",
                                reviewed_revision__isnull=True,
                            )
                            | models.Q(authorization_run__isnull=False)
                        )
                    )
                ),
                name="provider_draft_source_contract",
            ),
        ),
    ]
