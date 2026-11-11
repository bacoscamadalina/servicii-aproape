from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_cases_for_existing_reports(apps, schema_editor):
    Report = apps.get_model("services", "PublicProviderReport")
    Case = apps.get_model("services", "PublicProviderReportCase")
    Case.objects.bulk_create(
        Case(report_id=report_id)
        for report_id in Report.objects.values_list("id", flat=True)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0018_publicproviderreport"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PublicProviderReportCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(choices=[("new", "Nouă"), ("in_review", "În analiză"), ("closed", "Închisă")], default="new", max_length=16)),
                ("outcome", models.CharField(blank=True, choices=[("no_issue_found", "Nu s-a confirmat o problemă"), ("duplicate", "Sesizare duplicată"), ("insufficient_information", "Informații insuficiente"), ("separate_follow_up_required", "Necesită o acțiune separată")], max_length=32)),
                ("revision", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("report", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="triage_case", to="services.publicproviderreport")),
            ],
            options={
                "permissions": [("triage_public_provider_report", "Poate analiza sesizările despre profiluri publice")],
                "indexes": [models.Index(fields=["state", "updated_at"], name="report_case_queue_idx")],
                "constraints": [models.CheckConstraint(condition=models.Q(models.Q(("state", "closed"), models.Q(("outcome", ""), _negated=True)), models.Q(("outcome", ""), ("state__in", ("new", "in_review"))), _connector="OR"), name="public_report_case_state_contract")],
            },
        ),
        migrations.RunPython(create_cases_for_existing_reports, migrations.RunPython.noop),
        migrations.CreateModel(
            name="PublicProviderReportTriageEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("previous_state", models.CharField(choices=[("new", "Nouă"), ("in_review", "În analiză"), ("closed", "Închisă")], max_length=16)),
                ("new_state", models.CharField(choices=[("new", "Nouă"), ("in_review", "În analiză"), ("closed", "Închisă")], max_length=16)),
                ("outcome", models.CharField(blank=True, choices=[("no_issue_found", "Nu s-a confirmat o problemă"), ("duplicate", "Sesizare duplicată"), ("insufficient_information", "Informații insuficiente"), ("separate_follow_up_required", "Necesită o acțiune separată")], max_length=32)),
                ("revision", models.PositiveBigIntegerField()),
                ("internal_note", models.TextField(max_length=1200)),
                ("policy_version", models.CharField(max_length=24)),
                ("acknowledgement", models.CharField(max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="public_provider_report_triage_events", to=settings.AUTH_USER_MODEL)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="services.publicproviderreportcase")),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("case", "revision"), name="uniq_public_report_case_revision"),
                    models.CheckConstraint(condition=models.Q(("internal_note", ""), _negated=True) & models.Q(("policy_version", ""), _negated=True) & models.Q(("acknowledgement", ""), _negated=True), name="public_report_event_content_contract"),
                    models.CheckConstraint(condition=models.Q(models.Q(("new_state", "closed"), models.Q(("outcome", ""), _negated=True)), models.Q(("new_state", "in_review"), ("outcome", "")), _connector="OR"), name="public_report_event_state_contract"),
                ],
            },
        ),
    ]
