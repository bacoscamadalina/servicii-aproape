from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0051_alter_providerlead_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="providerleadbatch",
            name="submission_nonce_digest",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
