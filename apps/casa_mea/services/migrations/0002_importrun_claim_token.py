import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("services", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="importrun",
            name="claim_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        )
    ]
