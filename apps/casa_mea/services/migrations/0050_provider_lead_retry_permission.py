from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("services", "0049_provider_lead_batch_retention")]

    operations = [
        migrations.AlterModelOptions(
            name="providerlead",
            options={
                "ordering": ("-created_at", "-id"),
                "permissions": [
                    ("view_provider_lead_insights", "Poate vedea agregatele operaționale ale solicitărilor"),
                    ("retry_provider_lead_notification", "Poate retrimite notificările eșuate ale firmelor"),
                ],
            },
        ),
    ]
