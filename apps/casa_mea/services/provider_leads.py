"""Private customer-request intake, notification, and provider-owned workflow."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from .catalog import CATEGORIES
from .models import (
    ProviderLead,
    ProviderLeadBatch,
    ProviderLeadEvent,
    ProviderLeadMessage,
    ProviderInvoiceDraft,
    ProviderMembership,
    ProviderProfile,
    ProviderQuote,
    ProviderQuoteLine,
    ProviderVisitProposal,
    ProviderWorkOrder,
    ProviderWorkAssignmentEvent,
    ProviderWorkOrderEvent,
)


LEAD_SEND_LIMIT = 3
LEAD_SEND_WINDOW = timedelta(hours=24)
GENERAL_REQUEST_SEND_LIMIT = 3
CUSTOMER_MESSAGE_LIMIT = 12
CUSTOMER_MESSAGE_WINDOW = timedelta(hours=1)
CATEGORY_LABELS = {slug: label for slug, label, _description in CATEGORIES}
ALLOWED_TRANSITIONS = {
    ProviderLead.Status.NEW: {
        ProviderLead.Status.CONTACTED,
        ProviderLead.Status.QUOTE_SENT,
        ProviderLead.Status.DECLINED,
    },
    ProviderLead.Status.CONTACTED: {
        ProviderLead.Status.VISIT_SCHEDULED,
        ProviderLead.Status.QUOTE_SENT,
        ProviderLead.Status.DECLINED,
    },
    ProviderLead.Status.VISIT_SCHEDULED: {
        ProviderLead.Status.QUOTE_SENT,
        ProviderLead.Status.DECLINED,
    },
    ProviderLead.Status.QUOTE_SENT: {
        ProviderLead.Status.WON,
        ProviderLead.Status.DECLINED,
    },
    ProviderLead.Status.WON: set(),
    ProviderLead.Status.COMPLETED: set(),
    ProviderLead.Status.DECLINED: set(),
}


def _session_digest(session_key: str) -> str:
    """Pseudonymize the visitor session used only for intake throttling."""

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"provider-lead:{session_key}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _customer_access_digest(token: str) -> str:
    """Bind a bearer token to this feature without persisting the secret."""

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"provider-lead-customer:{token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _batch_access_digest(token: str) -> str:
    """Bind a general-request bearer token to its own capability namespace."""

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"provider-lead-batch-customer:{token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _submission_nonce_digest(namespace: str, nonce: str) -> str:
    """Store a secret-keyed replay key without retaining the submitted nonce."""

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"provider-lead-{namespace}-submission:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_provider_lead(
    *,
    submission,
    category: str,
    county: str,
    siruta_code: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    project_address: str,
    description: str,
    budget: str,
    desired_start: str,
    session_key: str,
    submission_nonce: str = "",
    batch: ProviderLeadBatch | None = None,
    customer_account=None,
) -> tuple[ProviderLead, str]:
    """Create one bounded request only for a service and locality in the snapshot."""

    if not session_key:
        raise ValueError(_("Sesiunea nu este disponibilă. Reîncarcă pagina."))
    if not batch and not submission_nonce:
        raise ValueError(_("Reîncarcă formularul înainte de a trimite solicitarea."))
    nonce_digest = _submission_nonce_digest("direct", submission_nonce) if not batch else None
    duplicate_message = _(
        "Această solicitare a fost deja trimisă. Verifică e-mailul sau contul tău înainte să trimiți din nou."
    )
    if nonce_digest and ProviderLead.objects.filter(submission_nonce_digest=nonce_digest).exists():
        raise ValueError(duplicate_message)
    if category not in set(submission.services.values_list("category", flat=True)):
        raise ValueError(_("Serviciul ales nu este oferit de această firmă."))
    if not submission.coverage.filter(county=county, siruta_code=siruta_code).exists():
        raise ValueError(_("Localitatea nu mai face parte din acoperirea firmei."))
    digest = _session_digest(session_key)
    recent_count = ProviderLead.objects.filter(
        submission=submission,
        visitor_session_digest=digest,
        created_at__gte=timezone.now() - LEAD_SEND_WINDOW,
    ).count()
    if recent_count >= LEAD_SEND_LIMIT:
        raise ValueError(
            _("Ai trimis deja mai multe solicitări acestei firme. Reîncearcă mâine.")
        )
    customer_token = "" if batch else secrets.token_urlsafe(32)
    try:
        with transaction.atomic():
            lead = ProviderLead.objects.create(
                submission=submission,
                batch=batch,
                customer_account=customer_account,
                category=category,
                county=county,
                siruta_code=siruta_code,
                customer_name=" ".join(customer_name.split()),
                customer_email=customer_email.strip().lower(),
                customer_phone=" ".join(customer_phone.split()),
                project_address=" ".join(project_address.split()),
                description=" ".join(description.split()),
                budget=budget,
                desired_start=desired_start,
                visitor_session_digest=digest,
                submission_nonce_digest=nonce_digest,
                privacy_notice_version=settings.LEGAL_POLICY_VERSION,
                customer_access_digest=(
                    None if batch else _customer_access_digest(customer_token)
                ),
                customer_access_expires_at=(
                    None
                    if batch
                    else timezone.now()
                    + timedelta(days=settings.PROVIDER_LEAD_CUSTOMER_ACCESS_DAYS)
                ),
            )
    except IntegrityError as error:
        if nonce_digest and ProviderLead.objects.filter(submission_nonce_digest=nonce_digest).exists():
            raise ValueError(duplicate_message) from error
        raise
    return lead, customer_token


def create_provider_lead_batch(
    *,
    submissions,
    category: str,
    county: str,
    siruta_code: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    project_address: str,
    description: str,
    budget: str,
    desired_start: str,
    session_key: str,
    submission_nonce: str,
    customer_account=None,
) -> tuple[ProviderLeadBatch, str, tuple[ProviderLead, ...]]:
    """Atomically dispatch one project to every exact eligible public snapshot."""

    if not session_key:
        raise ValueError(_("Sesiunea nu este disponibilă. Reîncarcă pagina."))
    if not submission_nonce:
        raise ValueError(_("Reîncarcă formularul înainte de a trimite solicitarea."))
    nonce_digest = _submission_nonce_digest("batch", submission_nonce)
    duplicate_message = _(
        "Această solicitare a fost deja trimisă. Verifică e-mailul sau contul tău înainte să trimiți din nou."
    )
    if ProviderLeadBatch.objects.filter(submission_nonce_digest=nonce_digest).exists():
        raise ValueError(duplicate_message)
    candidates = tuple(submissions)
    if not candidates:
        raise ValueError(_("Nu există firme eligibile pentru această solicitare."))
    if len({submission.pk for submission in candidates}) != len(candidates):
        raise ValueError(_("Lista firmelor eligibile nu este validă."))
    if len({submission.profile_id for submission in candidates}) != len(candidates):
        raise ValueError(_("Lista firmelor eligibile nu este validă."))
    digest = _session_digest(session_key)
    if ProviderLeadBatch.objects.filter(
        visitor_session_digest=digest,
        created_at__gte=timezone.now() - LEAD_SEND_WINDOW,
    ).count() >= GENERAL_REQUEST_SEND_LIMIT:
        raise ValueError(_("Ai trimis deja mai multe solicitări. Reîncearcă mâine."))

    customer_token = secrets.token_urlsafe(32)
    try:
        # The unique database key, not the browser or a process-local lock, wins races.
        with transaction.atomic():
            batch = ProviderLeadBatch.objects.create(
                category=category,
                county=county,
                siruta_code=siruta_code,
                visitor_session_digest=digest,
                submission_nonce_digest=nonce_digest,
                privacy_notice_version=settings.LEGAL_POLICY_VERSION,
                customer_access_digest=_batch_access_digest(customer_token),
                customer_access_expires_at=timezone.now()
                + timedelta(days=settings.PROVIDER_LEAD_CUSTOMER_ACCESS_DAYS),
                customer_account=customer_account,
            )
            leads = tuple(
                create_provider_lead(
                    submission=submission,
                    category=category,
                    county=county,
                    siruta_code=siruta_code,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    project_address=project_address,
                    description=description,
                    budget=budget,
                    desired_start=desired_start,
                    session_key=session_key,
                    batch=batch,
                    customer_account=customer_account,
                )[0]
                for submission in candidates
            )
    except IntegrityError as error:
        if ProviderLeadBatch.objects.filter(submission_nonce_digest=nonce_digest).exists():
            raise ValueError(duplicate_message) from error
        raise
    return batch, customer_token, leads


def provider_lead_recipient(lead: ProviderLead) -> str:
    """Resolve the approved public mailbox or the active owner's account mailbox."""

    return lead.submission.public_email or (
        ProviderMembership.objects.filter(
            profile=lead.submission.profile,
            state=ProviderMembership.State.ACTIVE,
            user__is_active=True,
        )
        .values_list("user__email", flat=True)
        .first()
        or ""
    )


def provider_lead_focus_url(request, lead: ProviderLead) -> str:
    """Build the owner-guarded, pagination-safe destination without customer details."""

    query = urlencode({"view": "requests", "focus": str(lead.public_id)})
    return request.build_absolute_uri(f'{reverse("services:provider_leads")}?{query}')


def deliver_provider_lead_notification(*, lead: ProviderLead, dashboard_url: str) -> bool:
    """Notify the verified owner without exposing request details in logs."""

    recipient = provider_lead_recipient(lead)
    if not recipient:
        ProviderLead.objects.filter(
            pk=lead.pk,
            notification_state=ProviderLead.NotificationState.PENDING,
        ).update(
            notification_state=ProviderLead.NotificationState.FAILED,
            notification_failed_at=timezone.now(),
        )
        return False
    try:
        sent_count = send_mail(
            _("Solicitare nouă prin ServiciiAproape / New request"),
            _(
                "%(customer)s caută o firmă pentru %(service)s în %(county)s. "
                "Deschide panoul pentru datele clientului și detaliile proiectului:\n%(url)s\n\n"
                "You received a new customer request. Open your dashboard to review it."
            )
            % {
                "customer": lead.customer_name,
                "service": CATEGORY_LABELS.get(lead.category, lead.category),
                "county": lead.county,
                "url": dashboard_url,
            },
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        if sent_count != 1:
            raise RuntimeError("Provider notification was not accepted by the mail backend")
    except Exception:
        ProviderLead.objects.filter(
            pk=lead.pk,
            notification_state=ProviderLead.NotificationState.PENDING,
        ).update(
            notification_state=ProviderLead.NotificationState.FAILED,
            notification_failed_at=timezone.now(),
        )
        return False
    ProviderLead.objects.filter(
        pk=lead.pk,
        notification_state=ProviderLead.NotificationState.PENDING,
    ).update(
        notification_state=ProviderLead.NotificationState.SENT,
        notified_at=timezone.now(),
    )
    return True


def deliver_customer_access_notification(*, lead: ProviderLead, access_url: str) -> bool:
    """Send the customer their private conversation link without project content."""

    try:
        sent_count = send_mail(
            _("Solicitarea ta prin ServiciiAproape / Your request"),
            _(
                "Solicitarea ta a ajuns la %(provider)s. Poți urmări oferta și conversația "
                "folosind linkul privat de mai jos:\n%(url)s\n\n"
                "Nu distribui acest link. ServiciiAproape nu îți va cere parola prin e-mail."
            )
            % {"provider": lead.submission.display_name, "url": access_url},
            settings.DEFAULT_FROM_EMAIL,
            [lead.customer_email],
            fail_silently=False,
        )
        if sent_count != 1:
            raise RuntimeError("Customer notification was not accepted by the mail backend")
    except Exception:
        ProviderLead.objects.filter(pk=lead.pk).update(
            customer_notification_failed_at=timezone.now(),
            customer_notified_at=None,
        )
        return False
    ProviderLead.objects.filter(pk=lead.pk).update(
        customer_notified_at=timezone.now(),
        customer_notification_failed_at=None,
    )
    return True


def deliver_customer_batch_access_notification(
    *, batch: ProviderLeadBatch, access_url: str
) -> bool:
    """Send one private comparison link for the complete multi-provider request."""

    first_lead = batch.leads.filter(retention_applied_at__isnull=True).order_by("pk").first()
    if first_lead is None:
        return False
    try:
        sent_count = send_mail(
            _("Solicitarea ta prin ServiciiAproape / Your request"),
            _(
                "Solicitarea ta a ajuns la %(count)s firme. Poți compara ofertele și "
                "continua fiecare conversație folosind linkul privat de mai jos:\n%(url)s\n\n"
                "Nu distribui acest link. ServiciiAproape nu îți va cere parola prin e-mail."
            )
            % {"count": batch.leads.count(), "url": access_url},
            settings.DEFAULT_FROM_EMAIL,
            [first_lead.customer_email],
            fail_silently=False,
        )
        if sent_count != 1:
            raise RuntimeError("Customer notification was not accepted by the mail backend")
    except Exception:
        ProviderLead.objects.filter(batch=batch).update(
            customer_notification_failed_at=timezone.now(),
            customer_notified_at=None,
        )
        return False
    ProviderLead.objects.filter(batch=batch).update(
        customer_notified_at=timezone.now(),
        customer_notification_failed_at=None,
    )
    return True


def rotate_and_deliver_customer_access_notification(*, request, lead=None, batch=None) -> bool:
    """Replace an undelivered anonymous capability and e-mail its new private URL.

    The caller must hold a row lock on the target through the bounded SMTP send.
    Rotation invalidates any old link, including one accepted before an ambiguous
    mail error; the original expiry is preserved rather than silently extended.
    """

    if (lead is None) == (batch is None):
        raise ValueError("Exactly one customer request is required")
    target = lead if lead is not None else batch
    if target.customer_account_id or target.retention_applied_at:
        raise ValueError("Only active anonymous requests can receive a capability")
    if target.customer_access_expires_at <= timezone.now():
        raise ValueError("The customer capability has expired")
    if lead is not None:
        if lead.batch_id or lead.customer_notification_failed_at is None or lead.customer_notified_at:
            raise ValueError("The customer notification is not eligible")
    elif (
        not batch.leads.filter(retention_applied_at__isnull=True).exists()
        or batch.leads.filter(
            retention_applied_at__isnull=True,
        ).exclude(
            customer_notification_failed_at__isnull=False,
            customer_notified_at__isnull=True,
        ).exists()
    ):
        raise ValueError("The comparison notification is not eligible")

    token = secrets.token_urlsafe(32)
    target.customer_access_digest = (
        _customer_access_digest(token) if lead is not None else _batch_access_digest(token)
    )
    target.save(update_fields=("customer_access_digest",))
    route = "services:provider_lead_customer" if lead is not None else "services:provider_lead_batch_customer"
    access_url = request.build_absolute_uri(reverse(route, args=(target.public_id, token)))
    return (
        deliver_customer_access_notification(lead=lead, access_url=access_url)
        if lead is not None
        else deliver_customer_batch_access_notification(batch=batch, access_url=access_url)
    )


def provider_lead_for_customer(*, public_id, token: str) -> ProviderLead:
    """Resolve one non-expired private lead from its opaque customer capability."""

    if not token:
        raise ProviderLead.DoesNotExist
    return ProviderLead.objects.select_related(
        "submission", "work_order__accepted_quote"
    ).prefetch_related("quotes__lines", "messages").get(
        public_id=public_id,
        customer_access_digest=_customer_access_digest(token),
        customer_access_expires_at__gt=timezone.now(),
        retention_applied_at__isnull=True,
    )


def provider_lead_batch_for_customer(*, public_id, token: str) -> ProviderLeadBatch:
    """Resolve one non-expired comparison workspace from its opaque capability."""

    if not token:
        raise ProviderLeadBatch.DoesNotExist
    return ProviderLeadBatch.objects.prefetch_related(
        "leads__submission", "leads__work_order__accepted_quote",
        "leads__quotes__lines", "leads__messages"
    ).filter(
        customer_access_digest=_batch_access_digest(token),
        customer_access_expires_at__gt=timezone.now(),
        retention_applied_at__isnull=True,
        leads__retention_applied_at__isnull=True,
    ).distinct().get(public_id=public_id)


def provider_lead_for_customer_account(*, public_id, customer_account) -> ProviderLead:
    """Resolve one retained standalone request through explicit account ownership."""

    return ProviderLead.objects.select_related("submission", "work_order__accepted_quote").prefetch_related(
        "quotes__lines", "messages"
    ).get(
        public_id=public_id,
        customer_account=customer_account,
        batch__isnull=True,
        retention_applied_at__isnull=True,
    )


def provider_lead_batch_for_customer_account(*, public_id, customer_account) -> ProviderLeadBatch:
    """Resolve one retained multi-provider project through explicit account ownership."""

    return ProviderLeadBatch.objects.prefetch_related(
        "leads__submission", "leads__work_order__accepted_quote",
        "leads__quotes__lines", "leads__messages"
    ).filter(
        public_id=public_id,
        customer_account=customer_account,
        retention_applied_at__isnull=True,
        leads__retention_applied_at__isnull=True,
    ).distinct().get()


def provider_leads_for_owner(user):
    """Return the caller's profile and private requests or fail closed."""

    memberships = list(
        ProviderMembership.objects.select_related("profile")
        .filter(
            user=user,
            user__is_active=True,
            state=ProviderMembership.State.ACTIVE,
            profile__state=ProviderProfile.State.DRAFT,
        )
        .order_by("pk")[:2]
    )
    if len(memberships) != 1:
        raise PermissionError(_("Accesul la solicitări nu mai este activ."))
    membership = memberships[0]
    leads = ProviderLead.objects.filter(
        submission__profile=membership.profile,
        retention_applied_at__isnull=True,
    ).select_related(
        "submission", "work_order__accepted_quote", "work_order__invoice_draft",
        "work_order__receivable", "crm_customer",
    ).prefetch_related(
        "quotes__lines", "messages", "visit_proposals",
        "work_order__receivable__manual_payments",
    )
    return membership.profile, leads


def provider_lead_metrics(leads) -> dict[str, int]:
    """Calculate identity-free funnel totals for the provider dashboard."""

    since = timezone.now() - timedelta(days=30)
    return leads.aggregate(
        total=Count("id"),
        new=Count("id", filter=Q(status=ProviderLead.Status.NEW)),
        active=Count(
            "id",
            filter=Q(
                status__in=(
                    ProviderLead.Status.CONTACTED,
                    ProviderLead.Status.VISIT_SCHEDULED,
                    ProviderLead.Status.QUOTE_SENT,
                )
            ),
        ),
        accepted=Count(
            "id",
            filter=Q(
                status__in=(ProviderLead.Status.WON, ProviderLead.Status.COMPLETED)
            ),
        ),
        declined=Count("id", filter=Q(status=ProviderLead.Status.DECLINED)),
        recent=Count("id", filter=Q(created_at__gte=since)),
        won=Count(
            "id",
            filter=Q(status__in=(ProviderLead.Status.WON, ProviderLead.Status.COMPLETED)),
        ),
    )


@transaction.atomic
def update_provider_lead_for_owner(
    *, user, lead_id: int, expected_revision: int, new_status: str, owner_notes: str
) -> ProviderLead:
    """Apply one valid owner transition and append its audit event."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id,
        submission__profile=profile,
        retention_applied_at__isnull=True,
    )
    if lead.revision != expected_revision:
        raise ValueError(_("Solicitarea a fost modificată. Reîncarcă pagina."))
    normalized_notes = " ".join(owner_notes.split())
    status_changed = new_status != lead.status
    if status_changed and new_status not in ALLOWED_TRANSITIONS[lead.status]:
        raise ValueError(_("Această schimbare de stare nu este permisă."))
    if status_changed and new_status == ProviderLead.Status.VISIT_SCHEDULED:
        raise ValueError(_("Vizita se programează după confirmarea propunerii de către client."))
    if status_changed and new_status == ProviderLead.Status.WON:
        raise ValueError(_("Lucrarea se deschide după acceptarea ofertei de către client."))
    if not status_changed and normalized_notes == lead.owner_notes:
        return lead
    previous_status = lead.status
    lead.status = new_status
    lead.owner_notes = normalized_notes
    lead.revision += 1
    lead.save(update_fields=("status", "owner_notes", "revision", "updated_at"))
    if status_changed:
        ProviderLeadEvent.objects.create(
            lead=lead,
            previous_status=previous_status,
            new_status=new_status,
            revision=lead.revision,
            actor=user,
        )
    return lead


@transaction.atomic
def schedule_provider_work_order(*, user, lead_id: int, expected_revision: int, starts_at, ends_at=None):
    """Record an owner-planned interval, distinct from a customer visit."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(lead=lead)
    if order.revision != expected_revision:
        raise ValueError(_("Lucrarea a fost modificată. Reîncarcă pagina."))
    if lead.status != ProviderLead.Status.WON or order.status not in {
        ProviderWorkOrder.Status.AWAITING_SCHEDULE, ProviderWorkOrder.Status.SCHEDULED,
    }:
        raise ValueError(_("Numai o lucrare acceptată și nefinalizată poate fi programată."))
    if order.started_at is not None:
        raise ValueError(_("Lucrarea a început deja și nu mai poate fi reprogramată."))
    now = timezone.now()
    if timezone.is_naive(starts_at) or not now + timedelta(minutes=5) <= starts_at <= now + timedelta(days=365):
        raise ValueError(_("Alege o dată și o oră între 5 minute și un an de acum."))
    if ends_at is not None and (timezone.is_naive(ends_at) or not starts_at < ends_at <= starts_at + timedelta(days=14)):
        raise ValueError(_("Ora de încheiere trebuie să fie după început și la cel mult 14 zile distanță."))
    if order.status == ProviderWorkOrder.Status.SCHEDULED and order.scheduled_start == starts_at and order.scheduled_end == ends_at:
        return order
    previous_status, previous_start, previous_end = order.status, order.scheduled_start, order.scheduled_end
    order.status = ProviderWorkOrder.Status.SCHEDULED
    order.scheduled_start = starts_at
    order.scheduled_end = ends_at
    order.revision += 1
    order.save(update_fields=("status", "scheduled_start", "scheduled_end", "revision"))
    ProviderWorkOrderEvent.objects.create(
        work_order=order, revision=order.revision,
        previous_status=previous_status, new_status=order.status,
        previous_start=previous_start, new_start=starts_at,
        previous_end=previous_end, new_end=ends_at, actor=user,
    )
    return order


@transaction.atomic
def cancel_provider_work_schedule(*, user, lead_id: int, expected_revision: int):
    """Remove a future booking while preserving the accepted job and its audit trail."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(lead=lead)
    if order.revision != expected_revision:
        raise ValueError(_("Lucrarea a fost modificată. Reîncarcă pagina."))
    if lead.status != ProviderLead.Status.WON or order.status != ProviderWorkOrder.Status.SCHEDULED:
        raise ValueError(_("Numai o lucrare acceptată și programată poate fi anulată."))
    if order.started_at is not None:
        raise ValueError(_("Lucrarea a început deja și nu mai poate fi anulată."))
    if order.scheduled_start <= timezone.now():
        raise ValueError(_("Programarea începută nu mai poate fi anulată aici."))
    previous_start, previous_end = order.scheduled_start, order.scheduled_end
    order.status = ProviderWorkOrder.Status.AWAITING_SCHEDULE
    order.scheduled_start = None
    order.scheduled_end = None
    order.revision += 1
    update_fields = ["status", "scheduled_start", "scheduled_end", "revision"]
    if order.assigned_technician_id is not None:
        previous_technician = order.assigned_technician
        order.assigned_technician = None
        order.assignment_revision += 1
        update_fields.extend(("assigned_technician", "assignment_revision"))
        ProviderWorkAssignmentEvent.objects.create(
            work_order=order, revision=order.assignment_revision,
            previous_technician=previous_technician, new_technician=None, actor=user,
        )
    order.save(update_fields=update_fields)
    ProviderWorkOrderEvent.objects.create(
        work_order=order, revision=order.revision,
        previous_status=ProviderWorkOrder.Status.SCHEDULED, new_status=order.status,
        previous_start=previous_start, new_start=None,
        previous_end=previous_end, new_end=None, actor=user,
    )
    return order


@transaction.atomic
def complete_provider_work_order(*, user, lead_id: int, expected_revision: int):
    """Close a scheduled job and its sales funnel without creating a fiscal invoice."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(lead=lead)
    if order.revision != expected_revision:
        raise ValueError(_("Lucrarea a fost modificată. Reîncarcă pagina."))
    if lead.status != ProviderLead.Status.WON or order.status != ProviderWorkOrder.Status.SCHEDULED:
        raise ValueError(_("Programează lucrarea înainte de finalizare."))
    now = timezone.now()
    if order.scheduled_start > now:
        raise ValueError(_("Lucrarea nu poate fi finalizată înainte de data programată."))
    order.status = ProviderWorkOrder.Status.COMPLETED
    order.completed_at = now
    order.revision += 1
    order.save(update_fields=("status", "completed_at", "revision"))
    ProviderWorkOrderEvent.objects.create(
        work_order=order, revision=order.revision,
        previous_status=ProviderWorkOrder.Status.SCHEDULED, new_status=order.status,
        previous_start=order.scheduled_start, new_start=order.scheduled_start,
        previous_end=order.scheduled_end, new_end=order.scheduled_end,
        previous_started_at=order.started_at, new_started_at=order.started_at,
        actor=user,
    )
    lead.status = ProviderLead.Status.COMPLETED
    lead.revision += 1
    lead.save(update_fields=("status", "revision", "updated_at"))
    ProviderLeadEvent.objects.create(
        lead=lead, previous_status=ProviderLead.Status.WON,
        new_status=lead.status, revision=lead.revision, actor=user,
    )
    return order


@transaction.atomic
def save_provider_invoice_draft(*, user, lead_id: int, expected_revision: int, amount_ron, description: str):
    """Save owner-only billing preparation without issuing an invoice or notifying a customer."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(lead=lead)
    if lead.status != ProviderLead.Status.COMPLETED or order.status != ProviderWorkOrder.Status.COMPLETED:
        raise ValueError(_("Finalizează lucrarea înainte de a pregăti facturarea."))
    try:
        amount = Decimal(str(amount_ron))
    except (InvalidOperation, ValueError):
        raise ValueError(_("Introdu o sumă validă în lei.")) from None
    if not amount.is_finite() or not 0 < amount <= Decimal("99999999.99") or amount.as_tuple().exponent < -2:
        raise ValueError(_("Suma trebuie să fie între 0,01 și 99.999.999,99 lei, cu maximum două zecimale."))
    text = " ".join(description.split())
    if not 10 <= len(text) <= 2000:
        raise ValueError(_("Descrierea trebuie să aibă între 10 și 2.000 de caractere."))
    draft = ProviderInvoiceDraft.objects.select_for_update().filter(work_order=order).first()
    if hasattr(order, "receivable"):
        raise ValueError(_("Ciorna este blocată după deschiderea evidenței de încasare."))
    if (draft.revision if draft else 0) != expected_revision:
        raise ValueError(_("Ciorna s-a modificat. Reîncarcă pagina."))
    if draft is None:
        return ProviderInvoiceDraft.objects.create(
            work_order=order, amount_ron=amount, description=text, updated_by=user,
        ), True
    if draft.amount_ron == amount and draft.description == text:
        return draft, False
    draft.amount_ron = amount
    draft.description = text
    draft.revision += 1
    draft.updated_by = user
    draft.updated_at = timezone.now()
    draft.save(update_fields=("amount_ron", "description", "revision", "updated_by", "updated_at"))
    return draft, True


@transaction.atomic
def propose_provider_visit(*, user, lead_id: int, starts_at, note: str) -> ProviderVisitProposal:
    """Propose one future visit to the exact provider-owned active request."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True
    )
    if ProviderVisitProposal.objects.filter(lead=lead, status=ProviderVisitProposal.Status.ACCEPTED).exists():
        raise ValueError(_("Anulează vizita confirmată înainte de a propune altă dată."))
    if lead.status not in {
        ProviderLead.Status.NEW,
        ProviderLead.Status.CONTACTED,
        ProviderLead.Status.QUOTE_SENT,
        ProviderLead.Status.WON,
    }:
        raise ValueError(_("Vizita poate fi propusă numai pentru o solicitare deschisă."))
    ProviderVisitProposal.objects.filter(
        lead=lead, status=ProviderVisitProposal.Status.PROPOSED,
        starts_at__lte=timezone.now(),
    ).update(status=ProviderVisitProposal.Status.EXPIRED)
    if ProviderVisitProposal.objects.filter(lead=lead, status=ProviderVisitProposal.Status.PROPOSED).exists():
        raise ValueError(_("Există deja o propunere în așteptarea clientului."))
    if not timezone.now() + timedelta(hours=1) <= starts_at <= timezone.now() + timedelta(days=90):
        raise ValueError(_("Alege o oră între o oră și 90 de zile de acum."))
    proposal = ProviderVisitProposal.objects.create(
        lead=lead, starts_at=starts_at, note=" ".join(note.split())
    )
    if lead.status == ProviderLead.Status.NEW:
        lead.status = ProviderLead.Status.CONTACTED
        lead.revision += 1
        lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=lead, previous_status=ProviderLead.Status.NEW,
            new_status=ProviderLead.Status.CONTACTED, revision=lead.revision, actor=user,
        )
    return proposal


def _cancel_provider_visit_locked(*, lead: ProviderLead, proposal_id: int, actor, actor_role: str):
    """Cancel one locked proposal and audit any resulting funnel correction."""

    proposal = ProviderVisitProposal.objects.select_for_update().get(
        pk=proposal_id,
        lead=lead,
        status__in=(ProviderVisitProposal.Status.PROPOSED, ProviderVisitProposal.Status.ACCEPTED),
    )
    if lead.status in {ProviderLead.Status.COMPLETED, ProviderLead.Status.DECLINED}:
        raise ValueError(_("Solicitarea este închisă; vizita nu mai poate fi anulată aici."))
    if proposal.status == ProviderVisitProposal.Status.PROPOSED and actor_role == ProviderLeadMessage.SenderRole.CUSTOMER:
        raise ValueError(_("Poți refuza propunerea folosind butonul de răspuns."))
    was_accepted = proposal.status == ProviderVisitProposal.Status.ACCEPTED
    proposal.status = ProviderVisitProposal.Status.CANCELLED
    proposal.cancelled_at = timezone.now()
    proposal.cancelled_by = actor_role
    proposal.save(update_fields=("status", "cancelled_at", "cancelled_by"))
    if was_accepted and lead.status == ProviderLead.Status.VISIT_SCHEDULED:
        lead.status = ProviderLead.Status.CONTACTED
        lead.revision += 1
        lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=lead,
            previous_status=ProviderLead.Status.VISIT_SCHEDULED,
            new_status=ProviderLead.Status.CONTACTED,
            revision=lead.revision,
            actor=actor,
            actor_role=actor_role,
        )
    return proposal


@transaction.atomic
def cancel_provider_visit_for_owner(*, user, lead_id: int, proposal_id: int) -> ProviderVisitProposal:
    """Withdraw a pending or confirmed visit from the owner-only workspace."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True
    )
    return _cancel_provider_visit_locked(
        lead=lead, proposal_id=proposal_id, actor=user,
        actor_role=ProviderLeadMessage.SenderRole.PROVIDER,
    )


@transaction.atomic
def cancel_provider_visit_for_customer(*, lead: ProviderLead, proposal_id: int) -> ProviderVisitProposal:
    """Cancel an accepted visit from an already authorized customer workspace."""

    locked_lead = ProviderLead.objects.select_for_update().get(
        pk=lead.pk, retention_applied_at__isnull=True
    )
    return _cancel_provider_visit_locked(
        lead=locked_lead, proposal_id=proposal_id, actor=None,
        actor_role=ProviderLeadMessage.SenderRole.CUSTOMER,
    )


@transaction.atomic
def respond_to_provider_visit(*, lead: ProviderLead, proposal_id: int, decision: str) -> ProviderVisitProposal:
    """Record one customer decision and schedule only an accepted future proposal."""

    locked_lead = ProviderLead.objects.select_for_update().get(pk=lead.pk, retention_applied_at__isnull=True)
    proposal = ProviderVisitProposal.objects.select_for_update().get(
        pk=proposal_id, lead=locked_lead, status=ProviderVisitProposal.Status.PROPOSED
    )
    if decision not in {ProviderVisitProposal.Status.ACCEPTED, ProviderVisitProposal.Status.DECLINED}:
        raise ValueError(_("Răspunsul la programare nu este valid."))
    if proposal.starts_at <= timezone.now():
        raise ValueError(_("Ora propusă a trecut. Cere firmei o nouă programare."))
    if locked_lead.status not in {
        ProviderLead.Status.CONTACTED,
        ProviderLead.Status.QUOTE_SENT,
        ProviderLead.Status.WON,
    }:
        raise ValueError(_("Solicitarea nu mai poate fi programată."))
    proposal.status = decision
    proposal.responded_at = timezone.now()
    proposal.save(update_fields=("status", "responded_at"))
    if decision == ProviderVisitProposal.Status.ACCEPTED and locked_lead.status == ProviderLead.Status.CONTACTED:
        locked_lead.status = ProviderLead.Status.VISIT_SCHEDULED
        locked_lead.revision += 1
        locked_lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=locked_lead, previous_status=ProviderLead.Status.CONTACTED,
            new_status=ProviderLead.Status.VISIT_SCHEDULED, revision=locked_lead.revision,
            actor=None, actor_role=ProviderLeadMessage.SenderRole.CUSTOMER,
        )
    return proposal


@transaction.atomic
def send_provider_quote(
    *, user, lead_id: int, amount_ron, summary: str, estimated_duration: str,
    valid_until, line_items=(),
) -> ProviderQuote:
    """Send an immutable offer and advance the lead through its audited funnel."""

    profile, _leads = provider_leads_for_owner(user)
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id,
        submission__profile=profile,
        retention_applied_at__isnull=True,
    )
    if lead.status not in {
        ProviderLead.Status.NEW,
        ProviderLead.Status.CONTACTED,
        ProviderLead.Status.VISIT_SCHEDULED,
        ProviderLead.Status.QUOTE_SENT,
    }:
        raise ValueError(_("Solicitarea este închisă și nu mai poate primi oferte."))
    if valid_until < timezone.localdate():
        raise ValueError(_("Data de valabilitate a ofertei nu poate fi în trecut."))
    amount_ron = Decimal(str(amount_ron))
    now = timezone.now()
    ProviderQuote.objects.filter(
        lead=lead, status=ProviderQuote.Status.SENT
    ).update(status=ProviderQuote.Status.WITHDRAWN, responded_at=now)
    revision = (
        ProviderQuote.objects.filter(lead=lead).aggregate(latest=Max("revision"))["latest"]
        or 0
    ) + 1
    quote = ProviderQuote.objects.create(
        lead=lead,
        revision=revision,
        amount_ron=amount_ron,
        summary=" ".join(summary.split()),
        estimated_duration=" ".join(estimated_duration.split()),
        valid_until=valid_until,
        sent_by=user,
    )
    normalized_lines = list(line_items) or [{
        "position": 1,
        "description": summary,
        "quantity": Decimal("1.00"),
        "unit": "lucrare",
        "unit_price_ron": amount_ron,
    }]
    calculated_total = sum(
        (item["quantity"] * item["unit_price_ron"] for item in normalized_lines),
        Decimal("0.00"),
    )
    if calculated_total != amount_ron:
        raise ValueError(_("Totalul pozițiilor nu corespunde totalului ofertei."))
    ProviderQuoteLine.objects.bulk_create([
        ProviderQuoteLine(
            quote=quote,
            position=index,
            description=" ".join(item["description"].split()),
            quantity=item["quantity"],
            unit=" ".join(item["unit"].split()),
            unit_price_ron=item["unit_price_ron"],
        )
        for index, item in enumerate(normalized_lines, start=1)
    ])
    if lead.status != ProviderLead.Status.QUOTE_SENT:
        previous_status = lead.status
        lead.status = ProviderLead.Status.QUOTE_SENT
        lead.revision += 1
        lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=lead,
            previous_status=previous_status,
            new_status=lead.status,
            revision=lead.revision,
            actor=user,
            actor_role=ProviderLeadMessage.SenderRole.PROVIDER,
        )
    return quote


@transaction.atomic
def respond_to_provider_quote(*, lead: ProviderLead, quote_id: int, decision: str) -> ProviderQuote:
    """Accept or decline the current offer using the customer's private capability."""

    locked_lead = ProviderLead.objects.select_for_update().get(pk=lead.pk)
    quote = ProviderQuote.objects.select_for_update().get(
        pk=quote_id,
        lead=locked_lead,
        status=ProviderQuote.Status.SENT,
    )
    if quote.valid_until < timezone.localdate():
        raise ValueError(_("Oferta a expirat și nu mai poate primi un răspuns."))
    if decision not in {ProviderQuote.Status.ACCEPTED, ProviderQuote.Status.DECLINED}:
        raise ValueError(_("Răspunsul la ofertă nu este valid."))
    quote.status = decision
    quote.responded_at = timezone.now()
    quote.save(update_fields=("status", "responded_at"))
    target_status = (
        ProviderLead.Status.WON
        if decision == ProviderQuote.Status.ACCEPTED
        else ProviderLead.Status.CONTACTED
    )
    previous_status = locked_lead.status
    if previous_status != target_status:
        locked_lead.status = target_status
        locked_lead.revision += 1
        locked_lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=locked_lead,
            previous_status=previous_status,
            new_status=target_status,
            revision=locked_lead.revision,
            actor=None,
            actor_role=ProviderLeadMessage.SenderRole.CUSTOMER,
        )
    if decision == ProviderQuote.Status.ACCEPTED:
        ProviderWorkOrder.objects.create(lead=locked_lead, accepted_quote=quote)
    return quote


@transaction.atomic
def respond_to_batch_provider_quote(
    *, batch: ProviderLeadBatch, lead: ProviderLead, quote_id: int, decision: str
) -> ProviderQuote:
    """Respond to one offer and close competing live offers after acceptance."""

    locked_batch = ProviderLeadBatch.objects.select_for_update().get(pk=batch.pk)
    locked_lead = ProviderLead.objects.select_for_update().get(
        pk=lead.pk,
        batch=locked_batch,
        retention_applied_at__isnull=True,
    )
    if decision == ProviderQuote.Status.ACCEPTED and ProviderQuote.objects.filter(
        lead__batch=locked_batch,
        status=ProviderQuote.Status.ACCEPTED,
    ).exclude(lead=locked_lead).exists():
        raise ValueError(_("Ai acceptat deja oferta altei firme."))

    quote = respond_to_provider_quote(
        lead=locked_lead,
        quote_id=quote_id,
        decision=decision,
    )
    if decision != ProviderQuote.Status.ACCEPTED:
        return quote

    now = timezone.now()
    competing_leads = ProviderLead.objects.select_for_update().filter(
        batch=locked_batch,
        retention_applied_at__isnull=True,
    ).exclude(pk=locked_lead.pk)
    ProviderQuote.objects.filter(
        lead__in=competing_leads,
        status=ProviderQuote.Status.SENT,
    ).update(status=ProviderQuote.Status.DECLINED, responded_at=now)
    for competing_lead in competing_leads.exclude(
        status__in=(ProviderLead.Status.COMPLETED, ProviderLead.Status.DECLINED)
    ):
        previous_status = competing_lead.status
        competing_lead.status = ProviderLead.Status.DECLINED
        competing_lead.revision += 1
        competing_lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=competing_lead,
            previous_status=previous_status,
            new_status=ProviderLead.Status.DECLINED,
            revision=competing_lead.revision,
            actor=None,
            actor_role=ProviderLeadMessage.SenderRole.CUSTOMER,
        )
    return quote


def add_provider_lead_message(*, lead: ProviderLead, sender_role: str, body: str, actor=None):
    """Append one message after enforcing role ownership and customer throttling."""

    if sender_role == ProviderLeadMessage.SenderRole.PROVIDER and actor is None:
        raise ValueError(_("Expeditorul firmei nu este valid."))
    if sender_role == ProviderLeadMessage.SenderRole.PROVIDER:
        profile, _leads = provider_leads_for_owner(actor)
        if lead.submission.profile_id != profile.pk:
            raise PermissionError(_("Solicitarea nu aparține acestei firme."))
    if sender_role == ProviderLeadMessage.SenderRole.CUSTOMER:
        if actor is not None:
            raise ValueError(_("Expeditorul clientului nu este valid."))
        recent = ProviderLeadMessage.objects.filter(
            lead=lead,
            sender_role=sender_role,
            created_at__gte=timezone.now() - CUSTOMER_MESSAGE_WINDOW,
        ).count()
        if recent >= CUSTOMER_MESSAGE_LIMIT:
            raise ValueError(_("Ai trimis prea multe mesaje. Reîncearcă mai târziu."))
    return ProviderLeadMessage.objects.create(
        lead=lead,
        sender_role=sender_role,
        actor=actor,
        body=" ".join(body.split()),
    )


def deliver_conversation_notification(*, lead: ProviderLead, recipient: str, access_url: str) -> bool:
    """Notify one participant about activity without copying private content."""

    if not recipient:
        return False
    try:
        send_mail(
            _("Actualizare în solicitarea ServiciiAproape / Request update"),
            _(
                "Ai o actualizare în spațiul privat al solicitării către %(provider)s. "
                "Deschide solicitarea aici:\n%(url)s"
            )
            % {"provider": lead.submission.display_name, "url": access_url},
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except Exception:
        return False
    return True


def allowed_provider_lead_statuses(lead: ProviderLead):
    """Expose the current state plus only its valid next states."""

    allowed = {lead.status, *ALLOWED_TRANSITIONS[lead.status]} - {
        ProviderLead.Status.VISIT_SCHEDULED, ProviderLead.Status.WON,
    }
    allowed.add(lead.status)
    return tuple((value, label) for value, label in ProviderLead.Status.choices if value in allowed)
