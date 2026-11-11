from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("services", "0021_providerloginthrottle")]

    operations = [
        migrations.RenameModel(
            old_name="ProviderLoginThrottle",
            new_name="AccountLoginThrottle",
        ),
        migrations.RenameIndex(
            model_name="accountloginthrottle",
            old_name="provider_login_window_idx",
            new_name="account_login_window_idx",
        ),
        migrations.RemoveConstraint(
            model_name="accountloginthrottle",
            name="provider_login_attempt_count_lte_5",
        ),
        migrations.AddConstraint(
            model_name="accountloginthrottle",
            constraint=models.CheckConstraint(
                condition=models.Q(("attempt_count__lte", 5)),
                name="account_login_attempt_count_lte_5",
            ),
        ),
    ]
