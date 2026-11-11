from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0052_providerleadbatch_submission_nonce_digest"),
    ]

    operations = [
        migrations.AddField(
            model_name="providerlead",
            name="submission_nonce_digest",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
