import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0057_providerworkorderevent_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderInvoiceDraft",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_ron", models.DecimalField(decimal_places=2, max_digits=12)),
                ("description", models.TextField(max_length=2000)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("work_order", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="invoice_draft", to="services.providerworkorder")),
            ],
            options={
                "constraints": [models.CheckConstraint(
                    condition=models.Q(amount_ron__gt=0) & ~models.Q(description="") & models.Q(revision__gt=0),
                    name="provider_invoice_draft_content_contract",
                )],
            },
        ),
    ]
