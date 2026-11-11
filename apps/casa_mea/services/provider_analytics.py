"""Privacy-minimized public-profile engagement measurement."""

from datetime import timedelta
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import ProviderEngagementEvent


ANALYTICS_PERIODS = (7, 30, 90)


def _daily_session_digest(*, session_key: str, occurred_on) -> str:
    """Pseudonymize a session with a daily salt so it cannot form a long-term profile."""

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"provider-engagement:{occurred_on.isoformat()}:{session_key}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def record_provider_engagement(*, submission, event_type: str, session_key: str) -> bool:
    """Record at most one event of each kind per snapshot, session, and local day."""

    if not session_key or event_type not in ProviderEngagementEvent.EventType.values:
        raise ValueError("Invalid provider engagement event.")
    available_events = {
        ProviderEngagementEvent.EventType.PROFILE_VIEW,
        ProviderEngagementEvent.EventType.QUOTE_REQUEST,
    }
    if submission.public_phone:
        available_events.add(ProviderEngagementEvent.EventType.PHONE)
    if submission.public_email:
        available_events.add(ProviderEngagementEvent.EventType.EMAIL)
    if submission.website:
        available_events.add(ProviderEngagementEvent.EventType.WEBSITE)
    if event_type not in available_events:
        raise ValueError("Unavailable provider engagement event.")

    occurred_on = timezone.localdate()
    _event, created = ProviderEngagementEvent.objects.get_or_create(
        submission=submission,
        event_type=event_type,
        visitor_session_digest=_daily_session_digest(
            session_key=session_key,
            occurred_on=occurred_on,
        ),
        occurred_on=occurred_on,
    )
    return created


def provider_engagement_metrics(*, profile, days: int) -> dict[str, int]:
    """Aggregate identity-free profile and contact totals for an allowed period."""

    if days not in ANALYTICS_PERIODS:
        raise ValueError("Unsupported analytics period.")
    since = timezone.localdate() - timedelta(days=days - 1)
    events = ProviderEngagementEvent.objects.filter(
        submission__profile=profile,
        occurred_on__gte=since,
    )
    totals = events.aggregate(
        profile_views=Count(
            "id", filter=Q(event_type=ProviderEngagementEvent.EventType.PROFILE_VIEW)
        ),
        phone=Count("id", filter=Q(event_type=ProviderEngagementEvent.EventType.PHONE)),
        email=Count("id", filter=Q(event_type=ProviderEngagementEvent.EventType.EMAIL)),
        website=Count(
            "id", filter=Q(event_type=ProviderEngagementEvent.EventType.WEBSITE)
        ),
        quote_requests=Count(
            "id", filter=Q(event_type=ProviderEngagementEvent.EventType.QUOTE_REQUEST)
        ),
        interested_visitors=Count(
            "visitor_session_digest",
            filter=Q(
                event_type__in=(
                    ProviderEngagementEvent.EventType.PHONE,
                    ProviderEngagementEvent.EventType.EMAIL,
                    ProviderEngagementEvent.EventType.WEBSITE,
                    ProviderEngagementEvent.EventType.QUOTE_REQUEST,
                )
            ),
            distinct=True,
        ),
    )
    totals["contact_actions"] = (
        totals["phone"]
        + totals["email"]
        + totals["website"]
        + totals["quote_requests"]
    )
    totals["interest_rate"] = (
        min(
            100,
            round(totals["interested_visitors"] * 100 / totals["profile_views"]),
        )
        if totals["profile_views"]
        else 0
    )
    totals["days"] = days
    return totals
