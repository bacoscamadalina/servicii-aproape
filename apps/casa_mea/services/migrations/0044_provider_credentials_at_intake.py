from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0043_service_category_policy")]

    operations = [
        migrations.AddField(
            model_name="providerclaimrequest",
            name="account_first_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="providerclaimrequest",
            name="account_last_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="providerclaimrequest",
            name="account_username",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="providerclaimrequest",
            name="password_hash",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="providerclaimrequest",
            name="credentials_supplied_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="providerregistrationrequest",
            name="account_first_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="providerregistrationrequest",
            name="account_last_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="providerregistrationrequest",
            name="account_username",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="providerregistrationrequest",
            name="password_hash",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="providerregistrationrequest",
            name="credentials_supplied_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="providerclaimrequest",
            name="provider_claim_status_timestamps",
        ),
        migrations.AddConstraint(
            model_name="providerclaimrequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=("email_pending", "superseded"),
                        email_verified_at__isnull=True,
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                    )
                    | models.Q(
                        status="review_pending",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                    )
                    & (
                        models.Q(email_verified_at__isnull=False)
                        | models.Q(credentials_supplied_at__isnull=False)
                    )
                    | models.Q(
                        status__in=("approved", "rejected"),
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                        approval_policy_version__gt="",
                    )
                    & (
                        models.Q(email_verified_at__isnull=False)
                        | models.Q(credentials_supplied_at__isnull=False)
                    )
                ),
                name="provider_claim_status_timestamps",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="providerregistrationrequest",
            name="provider_registration_status_contract",
        ),
        migrations.AddConstraint(
            model_name="providerregistrationrequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=("email_pending", "superseded"),
                        email_verified_at__isnull=True,
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                        linked_business__isnull=True,
                        converted_claim__isnull=True,
                    )
                    | models.Q(
                        status="review_pending",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                        linked_business__isnull=True,
                        converted_claim__isnull=True,
                    )
                    & (
                        models.Q(email_verified_at__isnull=False)
                        | models.Q(credentials_supplied_at__isnull=False)
                    )
                    | models.Q(
                        status="converted",
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                        linked_business__isnull=False,
                        converted_claim__isnull=False,
                        review_policy_version__gt="",
                    )
                    & (
                        models.Q(email_verified_at__isnull=False)
                        | models.Q(credentials_supplied_at__isnull=False)
                    )
                    | models.Q(
                        status="rejected",
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                        linked_business__isnull=True,
                        converted_claim__isnull=True,
                        review_policy_version__gt="",
                    )
                    & (
                        models.Q(email_verified_at__isnull=False)
                        | models.Q(credentials_supplied_at__isnull=False)
                    )
                ),
                name="provider_registration_status_contract",
            ),
        ),
    ]
