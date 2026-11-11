from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0060_provider_work_order_scheduled_end")]

    operations = [
        migrations.AddIndex(
            model_name="providerworkorder",
            index=models.Index(
                fields=("status", "scheduled_start", "scheduled_end"),
                name="provider_work_slot_idx",
            ),
        ),
    ]
