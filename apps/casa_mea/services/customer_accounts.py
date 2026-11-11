"""Transactional customer-account registration and access helpers."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from .models import CustomerAccount


@transaction.atomic
def register_customer_account(
    *, first_name: str, last_name: str, username: str, email: str, password: str,
    privacy_notice_version: str,
) -> CustomerAccount:
    """Create one immediately active customer account without an e-mail link."""

    user_model = get_user_model()
    normalized_email = email.strip().lower()
    if user_model.objects.select_for_update().filter(email__iexact=normalized_email).exists():
        raise ValueError(_("Există deja un cont cu această adresă de e-mail."))
    if user_model.objects.select_for_update().filter(username__iexact=username.strip()).exists():
        raise ValueError(_("Acest nume de utilizator este deja folosit."))
    try:
        user = user_model.objects.create_user(
            username=username.strip(),
            email=normalized_email,
            password=password,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            is_active=True,
        )
        return CustomerAccount.objects.create(
            user=user,
            normalized_email=normalized_email,
            privacy_notice_version=privacy_notice_version,
        )
    except IntegrityError as error:
        raise ValueError(_("Contul nu a putut fi creat. Verifică datele și încearcă din nou.")) from error


def active_customer_account(user) -> CustomerAccount | None:
    """Return the active customer identity, excluding provider-owner accounts."""

    if not user.is_authenticated or not user.is_active:
        return None
    try:
        account = user.customer_account
    except CustomerAccount.DoesNotExist:
        return None
    if user.provider_memberships.filter(state="active").exists():
        return None
    return account
