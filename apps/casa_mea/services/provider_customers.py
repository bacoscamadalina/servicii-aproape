"""Owner-scoped CRM contacts that never become customer accounts implicitly."""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    ProviderCRMCustomer,
    ProviderCRMCustomerEvent,
    ProviderLead,
    ProviderLeadCustomerLinkEvent,
)
from .provider_leads import provider_leads_for_owner


def provider_customers_for_owner(user):
    """Return the active provider profile and its bounded private contacts."""

    profile, _leads = provider_leads_for_owner(user)
    return profile, ProviderCRMCustomer.objects.filter(profile=profile)


@transaction.atomic
def save_provider_customer(*, user, expected_revision: int, customer_id=None, **values):
    """Create or update one contact after exact provider ownership checks."""

    profile, customers = provider_customers_for_owner(user)
    email = values["email"]
    if email and customers.filter(email__iexact=email).exclude(pk=customer_id).exists():
        raise ValueError(_("Există deja un client cu această adresă de e-mail."))
    now = timezone.now()
    if customer_id is None:
        if expected_revision != 0:
            raise ValueError(_("Fișa clientului s-a modificat. Reîncarcă pagina."))
        customer = ProviderCRMCustomer.objects.create(
            profile=profile, created_by=user, updated_by=user,
            lawful_use_confirmed_at=now,
            **{key: values[key] for key in ("name", "email", "phone", "address", "notes")},
        )
        ProviderCRMCustomerEvent.objects.create(
            customer=customer, revision=1,
            action=ProviderCRMCustomerEvent.Action.CREATED, actor=user, created_at=now,
        )
        return customer, True
    customer = customers.select_for_update().get(
        pk=customer_id, state=ProviderCRMCustomer.State.ACTIVE,
    )
    if customer.revision != expected_revision:
        raise ValueError(_("Fișa clientului s-a modificat. Reîncarcă pagina."))
    changed = any(
        getattr(customer, key) != values[key]
        for key in ("name", "email", "phone", "address", "notes")
    )
    if not changed:
        return customer, False
    for key in ("name", "email", "phone", "address", "notes"):
        setattr(customer, key, values[key])
    customer.revision += 1
    customer.updated_by = user
    customer.updated_at = now
    customer.lawful_use_confirmed_at = now
    customer.save(update_fields=(
        "name", "email", "phone", "address", "notes", "revision", "updated_by",
        "updated_at", "lawful_use_confirmed_at",
    ))
    ProviderCRMCustomerEvent.objects.create(
        customer=customer, revision=customer.revision,
        action=ProviderCRMCustomerEvent.Action.UPDATED, actor=user, created_at=now,
    )
    return customer, True


@transaction.atomic
def archive_provider_customer(*, user, customer_id: int, expected_revision: int):
    """Archive one owned contact while keeping a minimal audit trail."""

    _profile, customers = provider_customers_for_owner(user)
    customer = customers.select_for_update().get(
        pk=customer_id, state=ProviderCRMCustomer.State.ACTIVE,
    )
    if customer.revision != expected_revision:
        raise ValueError(_("Fișa clientului s-a modificat. Reîncarcă pagina."))
    now = timezone.now()
    customer.state = ProviderCRMCustomer.State.ARCHIVED
    customer.archived_at = now
    customer.revision += 1
    customer.updated_by = user
    customer.updated_at = now
    customer.save(update_fields=(
        "state", "archived_at", "revision", "updated_by", "updated_at",
    ))
    ProviderCRMCustomerEvent.objects.create(
        customer=customer, revision=customer.revision,
        action=ProviderCRMCustomerEvent.Action.ARCHIVED, actor=user, created_at=now,
    )
    return customer


@transaction.atomic
def link_provider_customer_to_lead(
    *, user, lead_id: int, customer_id: int | None, expected_revision: int,
):
    """Explicitly associate or disassociate one owner-scoped request and contact."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id,
        submission__profile=profile,
        retention_applied_at__isnull=True,
    )
    if lead.crm_customer_revision != expected_revision:
        raise ValueError(_("Asocierea clientului s-a modificat. Reîncarcă pagina."))
    customer = None
    if customer_id is not None:
        customer = ProviderCRMCustomer.objects.get(
            pk=customer_id,
            profile=profile,
            state=ProviderCRMCustomer.State.ACTIVE,
        )
    if lead.crm_customer_id == (customer.pk if customer else None):
        return lead, False
    previous_customer_id = lead.crm_customer_id
    lead.crm_customer = customer
    lead.crm_customer_revision += 1
    lead.save(update_fields=("crm_customer", "crm_customer_revision", "updated_at"))
    ProviderLeadCustomerLinkEvent.objects.create(
        lead=lead,
        revision=lead.crm_customer_revision,
        previous_customer_id=previous_customer_id,
        new_customer=customer,
        actor=user,
    )
    return lead, True


@transaction.atomic
def create_and_link_provider_customer_from_lead(
    *, user, lead_id: int, expected_link_revision: int, name: str, email: str,
    phone: str, address: str, notes: str,
):
    """Create one private contact and link it to its source request atomically."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id,
        submission__profile=profile,
        retention_applied_at__isnull=True,
    )
    if lead.crm_customer_revision != expected_link_revision:
        raise ValueError(_("Asocierea clientului s-a modificat. Reîncarcă pagina."))
    if lead.crm_customer_id is not None:
        raise ValueError(_("Solicitarea este deja asociată unui client din registru."))
    customer, _created = save_provider_customer(
        user=user,
        expected_revision=0,
        name=name,
        email=email,
        phone=phone,
        address=address,
        notes=notes,
    )
    lead.crm_customer = customer
    lead.crm_customer_revision += 1
    lead.save(update_fields=("crm_customer", "crm_customer_revision", "updated_at"))
    ProviderLeadCustomerLinkEvent.objects.create(
        lead=lead,
        revision=lead.crm_customer_revision,
        previous_customer=None,
        new_customer=customer,
        actor=user,
    )
    return customer, lead
