"""Read-only, identity-free delivery health for active customer projects."""

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from .models import ProviderLead, ProviderLeadBatch


def audit_request_delivery() -> dict:
    """Count unresolved delivery states without loading private request content.

    A comparison is one customer project even when several providers received it.
    Retained requests are outside the live delivery queue.
    """

    now = timezone.now()
    active_leads = ProviderLead.objects.filter(retention_applied_at__isnull=True)
    provider = active_leads.aggregate(
        failed=Count("pk", filter=Q(notification_state=ProviderLead.NotificationState.FAILED)),
        pending=Count("pk", filter=Q(notification_state=ProviderLead.NotificationState.PENDING)),
    )
    single = active_leads.filter(
        batch__isnull=True,
        customer_account__isnull=True,
        customer_notification_failed_at__isnull=False,
        customer_notified_at__isnull=True,
    ).aggregate(
        recoverable=Count("pk", filter=Q(customer_access_expires_at__gt=now)),
        expired=Count("pk", filter=Q(customer_access_expires_at__lte=now)),
    )

    # Batch-child delivery flags are expected to move together; count a mixed batch
    # separately instead of treating one failed child as a recoverable parent.
    active_children = active_leads.filter(batch_id=OuterRef("pk"))
    batches = ProviderLeadBatch.objects.filter(
        retention_applied_at__isnull=True,
        customer_account__isnull=True,
    ).annotate(
        _failed=Exists(active_children.filter(
            customer_notification_failed_at__isnull=False,
            customer_notified_at__isnull=True,
        )),
        _other=Exists(active_children.exclude(
            customer_notification_failed_at__isnull=False,
            customer_notified_at__isnull=True,
        )),
    )
    comparison = batches.filter(_failed=True, _other=False).aggregate(
        recoverable=Count("pk", filter=Q(customer_access_expires_at__gt=now)),
        expired=Count("pk", filter=Q(customer_access_expires_at__lte=now)),
    )
    mixed = batches.filter(_failed=True, _other=True).count()
    counts = (
        *provider.values(), *single.values(), *comparison.values(), mixed,
    )
    return {
        "schema_version": 1,
        "valid": not any(counts),
        "provider": provider,
        "customer_single": single,
        "customer_comparison": {**comparison, "mixed": mixed},
    }
