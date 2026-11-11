from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [("services", "0059_providerbillingidentity_providerbillingidentityevent_and_more")]

    operations = [
        migrations.AddField(
            model_name="providerworkorder",
            name="scheduled_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="providerworkorderevent",
            name="previous_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="providerworkorderevent",
            name="new_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="providerworkorder",
            name="provider_work_order_lifecycle",
        ),
        migrations.AddConstraint(
            model_name="providerworkorder",
            constraint=models.CheckConstraint(
                condition=(
                    Q(status="awaiting_schedule", scheduled_start__isnull=True, scheduled_end__isnull=True, completed_at__isnull=True)
                    | Q(status="scheduled", scheduled_start__isnull=False, completed_at__isnull=True)
                    | Q(status="completed", scheduled_start__isnull=False, completed_at__isnull=False)
                ),
                name="provider_work_order_lifecycle",
            ),
        ),
        migrations.AddConstraint(
            model_name="providerworkorder",
            constraint=models.CheckConstraint(
                condition=Q(scheduled_end__isnull=True) | Q(scheduled_end__gt=F("scheduled_start")),
                name="provider_work_order_end_after_start",
            ),
        ),
    ]
