from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0028_providerregistrationrequest")]

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
                    )
                ),
                name="provider_draft_source_contract",
            ),
        ),
    ]
