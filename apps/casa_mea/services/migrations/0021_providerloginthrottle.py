from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0020_alter_publicproviderreport_options_and_more")]

    operations = [
        migrations.CreateModel(
            name="ProviderLoginThrottle",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key_digest", models.CharField(max_length=64, unique=True)),
                ("window_started_at", models.DateTimeField()),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["window_started_at"],
                        name="provider_login_window_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("attempt_count__lte", 5)),
                        name="provider_login_attempt_count_lte_5",
                    )
                ],
            },
        )
    ]
