"""Provider-private receivable ledger with no payment processing or fiscal claim."""

from datetime import timedelta
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    ProviderInvoiceDraft,
    ProviderLead,
    ProviderManualPayment,
    ProviderReceivable,
    ProviderReceivableFollowUpEvent,
    ProviderWorkOrder,
)
from .provider_leads import provider_leads_for_owner


@dataclass(frozen=True)
class ProviderOutstandingSummary:
    count: int
    overdue_count: int
    balance_ron: Decimal


def provider_outstanding_receivable_summary(*, user) -> ProviderOutstandingSummary:
    """Return owner-scoped manual-ledger totals without exposing customer data."""

    profile, _leads = provider_leads_for_owner(user)
    money_field = DecimalField(max_digits=12, decimal_places=2)
    rows = ProviderReceivable.objects.filter(
        work_order__lead__submission__profile=profile,
        work_order__lead__retention_applied_at__isnull=True,
    ).annotate(
        paid=Coalesce(
            Sum(
                "manual_payments__amount_ron",
                filter=Q(manual_payments__state=ProviderManualPayment.State.ACTIVE),
            ),
            Value(Decimal("0.00"), output_field=money_field),
        ),
    ).annotate(
        balance=ExpressionWrapper(F("amount_ron") - F("paid"), output_field=money_field),
    ).filter(balance__gt=0)
    totals = rows.aggregate(
        count=Count("id"),
        overdue_count=Count("id", filter=Q(due_date__lt=timezone.localdate())),
        balance_ron=Coalesce(
            Sum("balance"), Value(Decimal("0.00"), output_field=money_field),
        ),
    )
    return ProviderOutstandingSummary(**totals)


def provider_receivable_totals(receivable: ProviderReceivable) -> tuple[Decimal, Decimal]:
    """Return active manually declared receipts and remaining internal balance."""

    paid = receivable.manual_payments.filter(
        state=ProviderManualPayment.State.ACTIVE,
    ).aggregate(total=Sum("amount_ron"))["total"] or Decimal("0.00")
    return paid, receivable.amount_ron - paid


@transaction.atomic
def open_provider_receivable(*, user, lead_id: int, due_date, reference: str):
    """Snapshot one completed job draft as an internal amount due."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(
        lead=lead, status=ProviderWorkOrder.Status.COMPLETED,
    )
    draft = ProviderInvoiceDraft.objects.select_for_update().get(work_order=order)
    if ProviderReceivable.objects.filter(work_order=order).exists():
        raise ValueError(_("Evidența de încasare există deja pentru această lucrare."))
    completed_date = timezone.localtime(order.completed_at).date()
    if not completed_date <= due_date <= timezone.localdate() + timedelta(days=365):
        raise ValueError(_("Scadența trebuie să fie între data finalizării și cel mult un an de azi."))
    return ProviderReceivable.objects.create(
        work_order=order, amount_ron=draft.amount_ron, due_date=due_date,
        reference=" ".join(reference.split())[:200], opened_by=user,
    )


@transaction.atomic
def record_provider_manual_payment(
    *, user, lead_id: int, amount_ron, received_on, reference: str,
):
    """Append one owner-declared receipt without asserting bank confirmation."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(
        lead=lead, status=ProviderWorkOrder.Status.COMPLETED,
    )
    receivable = ProviderReceivable.objects.select_for_update().get(work_order=order)
    try:
        amount = Decimal(str(amount_ron))
    except (InvalidOperation, ValueError):
        raise ValueError(_("Introdu o sumă validă în lei.")) from None
    _paid, balance = provider_receivable_totals(receivable)
    if not amount.is_finite() or amount.as_tuple().exponent < -2 or not Decimal("0.01") <= amount <= balance:
        raise ValueError(_("Suma încasată trebuie să fie pozitivă și să nu depășească soldul."))
    completed_date = timezone.localtime(order.completed_at).date()
    if not completed_date <= received_on <= timezone.localdate():
        raise ValueError(_("Data încasării trebuie să fie între finalizarea lucrării și azi."))
    payment = ProviderManualPayment.objects.create(
        receivable=receivable, amount_ron=amount, received_on=received_on,
        reference=" ".join(reference.split())[:200], recorded_by=user,
    )
    if amount == balance and receivable.follow_up_on is not None:
        previous_on = receivable.follow_up_on
        receivable.follow_up_on = None
        receivable.follow_up_revision += 1
        receivable.save(update_fields=("follow_up_on", "follow_up_revision"))
        ProviderReceivableFollowUpEvent.objects.create(
            receivable=receivable, revision=receivable.follow_up_revision,
            action=ProviderReceivableFollowUpEvent.Action.CLEARED_AFTER_PAYMENT,
            previous_on=previous_on, new_on=None, actor=user,
        )
    return payment


@transaction.atomic
def void_provider_manual_payment(*, user, lead_id: int, payment_id: int, reason: str):
    """Void an erroneous declaration while retaining its complete audit record."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    payment = ProviderManualPayment.objects.select_for_update().get(
        pk=payment_id, receivable__work_order__lead=lead,
        state=ProviderManualPayment.State.ACTIVE,
    )
    normalized_reason = " ".join(reason.split())
    if not 8 <= len(normalized_reason) <= 500:
        raise ValueError(_("Motivul anulării trebuie să aibă între 8 și 500 de caractere."))
    payment.state = ProviderManualPayment.State.VOID
    payment.voided_by = user
    payment.voided_at = timezone.now()
    payment.void_reason = normalized_reason
    payment.save(update_fields=("state", "voided_by", "voided_at", "void_reason"))
    return payment


@transaction.atomic
def schedule_provider_receivable_follow_up(
    *, user, lead_id: int, expected_revision: int, follow_up_on,
):
    """Schedule one private reminder after applying payment and contact cooldowns."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    receivable = ProviderReceivable.objects.select_for_update().get(
        work_order__lead=lead,
    )
    _paid, balance = provider_receivable_totals(receivable)
    if balance <= 0:
        raise ValueError(_("Nu poți programa urmărirea unui sold închis."))
    if receivable.follow_up_revision != expected_revision:
        raise ValueError(_("Reminderul intern s-a modificat. Reîncarcă pagina."))
    minimum_date = timezone.localdate()
    if receivable.last_followed_up_at:
        minimum_date = max(
            minimum_date,
            timezone.localtime(receivable.last_followed_up_at).date() + timedelta(days=7),
        )
    latest_payment = receivable.manual_payments.filter(
        state=ProviderManualPayment.State.ACTIVE,
    ).order_by("-received_on", "-pk").first()
    if latest_payment:
        minimum_date = max(minimum_date, latest_payment.received_on + timedelta(days=7))
    if not minimum_date <= follow_up_on <= timezone.localdate() + timedelta(days=180):
        raise ValueError(
            _("Data reminderului trebuie să respecte pauza de 7 zile și să fie în următoarele 180 de zile.")
        )
    previous_on = receivable.follow_up_on
    receivable.follow_up_on = follow_up_on
    receivable.follow_up_revision += 1
    receivable.save(update_fields=("follow_up_on", "follow_up_revision"))
    ProviderReceivableFollowUpEvent.objects.create(
        receivable=receivable, revision=receivable.follow_up_revision,
        action=ProviderReceivableFollowUpEvent.Action.SCHEDULED,
        previous_on=previous_on, new_on=follow_up_on, actor=user,
    )
    return receivable


@transaction.atomic
def complete_provider_receivable_follow_up(*, user, lead_id: int, expected_revision: int):
    """Mark one private reminder done without sending anything to the customer."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    receivable = ProviderReceivable.objects.select_for_update().get(
        work_order__lead=lead,
    )
    _paid, balance = provider_receivable_totals(receivable)
    if balance <= 0 or receivable.follow_up_on is None:
        raise ValueError(_("Nu există un reminder intern activ pentru acest sold."))
    if receivable.follow_up_revision != expected_revision:
        raise ValueError(_("Reminderul intern s-a modificat. Reîncarcă pagina."))
    previous_on = receivable.follow_up_on
    now = timezone.now()
    receivable.follow_up_on = None
    receivable.last_followed_up_at = now
    receivable.follow_up_revision += 1
    receivable.save(update_fields=(
        "follow_up_on", "last_followed_up_at", "follow_up_revision",
    ))
    ProviderReceivableFollowUpEvent.objects.create(
        receivable=receivable, revision=receivable.follow_up_revision,
        action=ProviderReceivableFollowUpEvent.Action.COMPLETED,
        previous_on=previous_on, new_on=None, actor=user, created_at=now,
    )
    return receivable
