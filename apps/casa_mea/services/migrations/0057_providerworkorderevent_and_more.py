import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0056_providerworkorder"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderWorkOrderEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveBigIntegerField()),
                ("previous_status", models.CharField(max_length=24)),
                ("new_status", models.CharField(max_length=24)),
                ("previous_start", models.DateTimeField(blank=True, null=True)),
                ("new_start", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        migrations.AddField(
            model_name="providerworkorder", name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="providerworkorder", name="revision",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="providerworkorder", name="scheduled_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="providerworkorder", name="status",
            field=models.CharField(
                choices=[
                    ("awaiting_schedule", "De programat"),
                    ("scheduled", "Programată"),
                    ("completed", "Finalizată"),
                ],
                default="awaiting_schedule", max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="providerworkorder",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(status="awaiting_schedule", scheduled_start__isnull=True, completed_at__isnull=True)
                    | models.Q(status="scheduled", scheduled_start__isnull=False, completed_at__isnull=True)
                    | models.Q(status="completed", scheduled_start__isnull=False, completed_at__isnull=False)
                ),
                name="provider_work_order_lifecycle",
            ),
        ),
        migrations.AddField(
            model_name="providerworkorderevent", name="actor",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="providerworkorderevent", name="work_order",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="services.providerworkorder"),
        ),
        migrations.AddConstraint(
            model_name="providerworkorderevent",
            constraint=models.UniqueConstraint(
                fields=("work_order", "revision"), name="uniq_work_order_event_revision"
            ),
        ),
    ]
