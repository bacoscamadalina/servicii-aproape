from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def backfill_quote_lines(apps, schema_editor):
    """Preserve every historical quote as one equivalent priced position."""

    ProviderQuote = apps.get_model("services", "ProviderQuote")
    ProviderQuoteLine = apps.get_model("services", "ProviderQuoteLine")
    batch = []
    for quote in ProviderQuote.objects.order_by("pk").iterator(chunk_size=1000):
        batch.append(
            ProviderQuoteLine(
                quote_id=quote.pk,
                position=1,
                description=quote.summary,
                quantity=Decimal("1.00"),
                unit="lucrare",
                unit_price_ron=quote.amount_ron,
            )
        )
        if len(batch) == 1000:
            ProviderQuoteLine.objects.bulk_create(batch)
            batch = []
    if batch:
        ProviderQuoteLine.objects.bulk_create(batch)


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0068_providerlead_crm_customer_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderQuoteLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveSmallIntegerField()),
                ("description", models.CharField(max_length=240)),
                ("quantity", models.DecimalField(decimal_places=2, max_digits=10)),
                ("unit", models.CharField(max_length=24)),
                ("unit_price_ron", models.DecimalField(decimal_places=2, max_digits=12)),
                ("quote", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="services.providerquote")),
            ],
            options={
                "ordering": ("position", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("quote", "position"), name="uniq_provider_quote_line_position"),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("position__gt", 0),
                            ("quantity__gt", 0),
                            ("unit_price_ron__gte", 0),
                            models.Q(("description", ""), _negated=True),
                            models.Q(("unit", ""), _negated=True),
                        ),
                        name="provider_quote_line_content_contract",
                    ),
                ],
            },
        ),
        migrations.RunPython(backfill_quote_lines, migrations.RunPython.noop),
    ]
