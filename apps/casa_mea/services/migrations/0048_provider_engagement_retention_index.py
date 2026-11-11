"""Support bounded global purges of expired profile-interaction digests."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0047_managed_site_inquiry_workflow")]

    operations = [
        migrations.AddIndex(
            model_name="providerengagementevent",
            index=models.Index(
                fields=("occurred_on", "id"), name="provider_engagement_ret_idx"
            ),
        ),
    ]
