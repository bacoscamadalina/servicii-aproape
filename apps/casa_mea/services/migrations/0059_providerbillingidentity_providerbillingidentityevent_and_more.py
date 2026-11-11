import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0058_providerinvoicedraft"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderBillingIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legal_name", models.CharField(max_length=500)),
                ("fiscal_identifier", models.CharField(max_length=40)),
                ("registration_number", models.CharField(max_length=80)),
                ("registered_address", models.CharField(max_length=500)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("profile", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="billing_identity", to="services.providerprofile")),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ProviderBillingIdentityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveBigIntegerField()),
                ("legal_name", models.CharField(max_length=500)),
                ("fiscal_identifier", models.CharField(max_length=40)),
                ("registration_number", models.CharField(max_length=80)),
                ("registered_address", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("identity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="services.providerbillingidentity")),
            ],
        ),
        migrations.AddConstraint(
            model_name="providerbillingidentity",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(legal_name="") & ~models.Q(fiscal_identifier="")
                    & ~models.Q(registration_number="") & ~models.Q(registered_address="")
                    & models.Q(revision__gt=0)
                ),
                name="provider_billing_identity_content_contract",
            ),
        ),
        migrations.AddConstraint(
            model_name="providerbillingidentityevent",
            constraint=models.UniqueConstraint(
                fields=("identity", "revision"), name="uniq_provider_billing_identity_revision"
            ),
        ),
    ]
