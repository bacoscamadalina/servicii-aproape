from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0019_publicproviderreportcase_and_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="publicproviderreport",
            options={
                "ordering": ("-created_at", "-id"),
                "permissions": [
                    (
                        "view_public_provider_report_insights",
                        "Poate vedea sumarul operațional al sesizărilor publice",
                    )
                ],
            },
        ),
        migrations.AddIndex(
            model_name="publicproviderreporttriageevent",
            index=models.Index(
                fields=["created_at", "new_state", "outcome"],
                name="report_event_window_idx",
            ),
        ),
    ]
