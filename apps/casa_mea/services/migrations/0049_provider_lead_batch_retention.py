"""Record when a comparison project no longer retains customer access or ownership."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0048_provider_engagement_retention_index")]

    operations = [
        migrations.AddField(
            model_name="providerleadbatch",
            name="retention_applied_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="providerleadbatch",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(retention_applied_at__isnull=True)
                    | models.Q(
                        customer_account__isnull=True,
                        customer_access_expires_at__lte=models.F("retention_applied_at"),
                    )
                ),
                name="retained_lead_batch_detached",
            ),
        ),
    ]
