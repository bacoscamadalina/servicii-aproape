from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("services", "0017_providerpasswordresetthrottle")]

    operations = [
        migrations.CreateModel(
            name="PublicProviderReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(choices=[("incorrect_information", "Informații incorecte"), ("wrong_service", "Servicii prezentate greșit"), ("unreachable_contact", "Date de contact nefuncționale"), ("inappropriate_portfolio", "Portofoliu nepotrivit"), ("other", "Altă problemă")], max_length=32)),
                ("details", models.TextField(max_length=1200)),
                ("reporter_session_digest", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="public_reports", to="services.providerpublicationsubmission")),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [models.Index(fields=["reason", "created_at"], name="public_report_reason_idx")],
                "constraints": [models.UniqueConstraint(fields=("submission", "reporter_session_digest"), name="uniq_public_report_session_snapshot")],
            },
        )
    ]
