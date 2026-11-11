from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("services", "0002_importrun_claim_token")]

    operations = [
        migrations.AddField(
            model_name="importrun",
            name="locality_rules_hash",
            field=models.CharField(blank=True, max_length=64),
        )
    ]
