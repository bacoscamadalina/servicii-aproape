"""Narrow technician access to owner-assigned, active execution work."""

from datetime import timedelta
import hashlib
import secrets

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    ProviderLead,
    ProviderLeadEvent,
    ProviderProfile,
    ProviderTeamMember,
    ProviderTeamInvitation,
    ProviderMembership,
    ProviderWorkAssignmentEvent,
    ProviderWorkOrder,
    ProviderWorkOrderEvent,
)
from .provider_leads import provider_leads_for_owner


TEAM_INVITATION_LIFETIME = timedelta(hours=48)
MAX_TEAM_MEMBERS_AND_INVITES = 10


def _invitation_digest(token: str) -> str:
    """Store only a non-recoverable lookup key for a high-entropy invitation."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def active_provider_team_member(user):
    """Return exactly one live technician membership or no access."""

    if not user.is_authenticated or not user.is_active:
        return None
    members = list(
        ProviderTeamMember.objects.select_related("profile")
        .filter(
            user=user, state=ProviderTeamMember.State.ACTIVE,
            profile__state=ProviderProfile.State.DRAFT,
        )[:2]
    )
    return members[0] if len(members) == 1 else None


@transaction.atomic
def issue_provider_team_invitation(*, user, email: str):
    """Create one bounded mailbox invitation from the current provider owner."""

    profile, _leads = provider_leads_for_owner(user)
    ProviderProfile.objects.select_for_update().get(pk=profile.pk)
    normalized_email = email.strip().lower()
    try:
        validate_email(normalized_email)
    except ValidationError as error:
        raise ValueError(_("Introdu o adresă de e-mail validă.")) from error
    if len(normalized_email) > 254 or normalized_email == user.email.strip().lower():
        raise ValueError(_("Această adresă nu poate fi invitată."))
    if ProviderTeamMember.objects.filter(
        profile=profile, user__email__iexact=normalized_email,
        state=ProviderTeamMember.State.ACTIVE,
    ).exists():
        raise ValueError(_("Acest tehnician este deja activ în echipă."))
    now = timezone.now()
    pending = ProviderTeamInvitation.objects.select_for_update().filter(
        profile=profile, normalized_email=normalized_email,
        accepted_at__isnull=True, revoked_at__isnull=True,
    ).first()
    if pending:
        if pending.expires_at > now:
            raise ValueError(_("Există deja o invitație activă pentru această adresă."))
        pending.revoked_at = now
        pending.revoked_by = user
        pending.save(update_fields=("revoked_at", "revoked_by"))
    active_count = ProviderTeamMember.objects.filter(
        profile=profile, state=ProviderTeamMember.State.ACTIVE,
    ).count()
    pending_count = ProviderTeamInvitation.objects.filter(
        profile=profile, accepted_at__isnull=True, revoked_at__isnull=True,
        expires_at__gt=now,
    ).count()
    if active_count + pending_count >= MAX_TEAM_MEMBERS_AND_INVITES:
        raise ValueError(_("Echipa a atins limita de invitații și tehnicieni activi."))
    token = secrets.token_urlsafe(32)
    invitation = ProviderTeamInvitation.objects.create(
        profile=profile, normalized_email=normalized_email,
        token_digest=_invitation_digest(token), invited_by=user,
        created_at=now, expires_at=now + TEAM_INVITATION_LIFETIME,
    )
    return invitation, token


def pending_provider_team_invitation(token: str):
    """Resolve only a live invitation; never reveal its digest or expired content."""

    if not 32 <= len(token) <= 128:
        raise ProviderTeamInvitation.DoesNotExist
    return ProviderTeamInvitation.objects.select_related("profile").get(
        token_digest=_invitation_digest(token), accepted_at__isnull=True,
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    )


@transaction.atomic
def accept_provider_team_invitation(*, token: str, existing_user=None, new_account=None):
    """Activate technician access only after mailbox proof and account validation."""

    invitation = ProviderTeamInvitation.objects.select_for_update().get(
        pk=pending_provider_team_invitation(token).pk,
    )
    if invitation.accepted_at or invitation.revoked_at or invitation.expires_at <= timezone.now():
        raise ValueError(_("Invitația nu mai este disponibilă."))
    if (existing_user is None) == (new_account is None):
        raise ValueError(_("Alege un singur mod de activare a contului."))
    User = get_user_model()
    if existing_user is not None:
        account = User.objects.select_for_update().get(pk=existing_user.pk)
        if not account.is_active or account.email.strip().lower() != invitation.normalized_email:
            raise PermissionError(_("Contul nu corespunde invitației."))
    else:
        username = new_account["username"].strip()
        if User.objects.filter(username__iexact=username).exists() or User.objects.filter(
            email__iexact=invitation.normalized_email
        ).exists():
            raise ValueError(_("Contul există deja. Autentifică-te pentru a accepta invitația."))
        account = User(
            username=username, email=invitation.normalized_email,
            first_name=new_account["first_name"].strip(),
            last_name=new_account["last_name"].strip(),
        )
        password_validation.validate_password(new_account["password"], account)
        account.set_password(new_account["password"])
        account.save()
    if ProviderMembership.objects.filter(user=account, state=ProviderMembership.State.ACTIVE).exists():
        raise ValueError(_("Acest cont are deja rol de proprietar. Folosește un cont separat pentru tehnician."))
    if ProviderTeamMember.objects.filter(user=account, state=ProviderTeamMember.State.ACTIVE).exclude(
        profile=invitation.profile
    ).exists():
        raise ValueError(_("Acest cont aparține deja altei echipe active."))
    member, created = ProviderTeamMember.objects.select_for_update().get_or_create(
        profile=invitation.profile, user=account,
    )
    if not created and member.state == ProviderTeamMember.State.ACTIVE:
        raise ValueError(_("Acest cont este deja activ în echipă."))
    if not created:
        member.state = ProviderTeamMember.State.ACTIVE
        member.activated_at = timezone.now()
        member.revoked_at = None
        member.revoked_by = None
        member.save(update_fields=("state", "activated_at", "revoked_at", "revoked_by"))
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = account
    invitation.save(update_fields=("accepted_at", "accepted_by"))
    return member


@transaction.atomic
def revoke_provider_team_invitation(*, user, invitation_id: int):
    """Invalidate a pending invitation before its recipient activates access."""

    profile, _leads = provider_leads_for_owner(user)
    invitation = ProviderTeamInvitation.objects.select_for_update().get(
        pk=invitation_id, profile=profile,
        accepted_at__isnull=True, revoked_at__isnull=True,
    )
    invitation.revoked_at = timezone.now()
    invitation.revoked_by = user
    invitation.save(update_fields=("revoked_at", "revoked_by"))
    return invitation


def assigned_provider_work_for_technician(user):
    """Return only scheduled jobs assigned to this one active technician."""

    member = active_provider_team_member(user)
    if member is None:
        raise PermissionError(_("Accesul la lucrările echipei nu este activ."))
    conflicting = ProviderWorkOrder.objects.filter(
        assigned_technician=member,
        status=ProviderWorkOrder.Status.SCHEDULED,
        lead__retention_applied_at__isnull=True,
        scheduled_end__isnull=False,
        scheduled_start__lt=OuterRef("scheduled_end"),
        scheduled_end__gt=OuterRef("scheduled_start"),
    ).exclude(pk=OuterRef("pk"))
    return ProviderWorkOrder.objects.filter(
        assigned_technician=member,
        assigned_technician__state=ProviderTeamMember.State.ACTIVE,
        assigned_technician__user__is_active=True,
        assigned_technician__profile__state=ProviderProfile.State.DRAFT,
        status=ProviderWorkOrder.Status.SCHEDULED,
        lead__status=ProviderLead.Status.WON,
        lead__retention_applied_at__isnull=True,
        lead__submission__profile=member.profile,
    ).annotate(
        known_assignee_overlap=Exists(conflicting),
    ).select_related("lead", "accepted_quote").order_by("scheduled_start", "pk")


@transaction.atomic
def update_assigned_work_execution(*, user, order_id: int, action: str, expected_revision: int):
    """Record a technician's start or finish under a freshly locked assignment."""

    member = active_provider_team_member(user)
    if member is None:
        raise PermissionError(_("Accesul la lucrările echipei nu este activ."))
    member = ProviderTeamMember.objects.select_for_update().get(
        pk=member.pk, user=user, state=ProviderTeamMember.State.ACTIVE,
        profile__state=ProviderProfile.State.DRAFT,
    )
    order = ProviderWorkOrder.objects.select_related("lead").filter(pk=order_id).first()
    if order is None:
        raise ProviderWorkOrder.DoesNotExist
    lead = ProviderLead.objects.select_for_update().get(
        pk=order.lead_id, submission__profile=member.profile,
        retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(
        pk=order_id, lead=lead, assigned_technician=member,
    )
    if order.revision != expected_revision:
        raise ValueError(_("Lucrarea a fost modificată. Reîncarcă pagina."))
    if lead.status != ProviderLead.Status.WON or order.status != ProviderWorkOrder.Status.SCHEDULED:
        raise ValueError(_("Lucrarea nu mai este programată pentru tine."))
    now = timezone.now()
    if order.scheduled_start > now:
        raise ValueError(_("Lucrarea nu poate începe înainte de ora programată."))
    if action == "start":
        if order.started_at is not None:
            raise ValueError(_("Începerea lucrării a fost deja confirmată."))
        order.started_at = now
        order.revision += 1
        order.save(update_fields=("started_at", "revision"))
        ProviderWorkOrderEvent.objects.create(
            work_order=order, revision=order.revision,
            previous_status=order.status, new_status=order.status,
            previous_start=order.scheduled_start, new_start=order.scheduled_start,
            previous_end=order.scheduled_end, new_end=order.scheduled_end,
            previous_started_at=None, new_started_at=now, actor=user,
        )
    elif action == "complete":
        if order.started_at is None:
            raise ValueError(_("Confirmă mai întâi începutul lucrării."))
        order.status = ProviderWorkOrder.Status.COMPLETED
        order.completed_at = now
        order.revision += 1
        order.save(update_fields=("status", "completed_at", "revision"))
        ProviderWorkOrderEvent.objects.create(
            work_order=order, revision=order.revision,
            previous_status=ProviderWorkOrder.Status.SCHEDULED, new_status=order.status,
            previous_start=order.scheduled_start, new_start=order.scheduled_start,
            previous_end=order.scheduled_end, new_end=order.scheduled_end,
            previous_started_at=order.started_at, new_started_at=order.started_at, actor=user,
        )
        lead.status = ProviderLead.Status.COMPLETED
        lead.revision += 1
        lead.save(update_fields=("status", "revision", "updated_at"))
        ProviderLeadEvent.objects.create(
            lead=lead, previous_status=ProviderLead.Status.WON,
            new_status=lead.status, revision=lead.revision, actor=user,
        )
    else:
        raise ValueError(_("Acțiune necunoscută pentru lucrare."))
    return order


@transaction.atomic
def assign_provider_technician(*, user, lead_id: int, member_id: int | None, expected_revision: int):
    """Assign or unassign one scheduled job under the active owner's boundary."""

    profile, _leads = provider_leads_for_owner(user)
    member = None
    if member_id is not None:
        member = ProviderTeamMember.objects.select_for_update().get(
            pk=member_id, profile=profile, state=ProviderTeamMember.State.ACTIVE,
            user__is_active=True,
        )
        if member.user_id == user.pk:
            raise ValueError(_("Proprietarul nu poate fi adăugat ca tehnician."))
    lead = ProviderLead.objects.select_for_update().get(
        pk=lead_id, submission__profile=profile, retention_applied_at__isnull=True,
    )
    order = ProviderWorkOrder.objects.select_for_update().get(lead=lead)
    if order.assignment_revision != expected_revision:
        raise ValueError(_("Atribuirea a fost modificată. Reîncarcă pagina."))
    if lead.status != ProviderLead.Status.WON or order.status != ProviderWorkOrder.Status.SCHEDULED:
        raise ValueError(_("Numai o lucrare programată și nefinalizată poate fi atribuită."))
    if order.started_at is not None:
        raise ValueError(_("Lucrarea a început deja și atribuirea nu mai poate fi schimbată."))
    if order.assigned_technician_id == (member.pk if member else None):
        return order
    previous_member = order.assigned_technician
    order.assigned_technician = member
    order.assignment_revision += 1
    order.save(update_fields=("assigned_technician", "assignment_revision"))
    ProviderWorkAssignmentEvent.objects.create(
        work_order=order, revision=order.assignment_revision,
        previous_technician=previous_member, new_technician=member, actor=user,
    )
    return order


@transaction.atomic
def revoke_provider_technician(*, user, member_id: int):
    """Revoke team access immediately without changing accepted job history."""

    profile, _leads = provider_leads_for_owner(user)
    member = ProviderTeamMember.objects.select_for_update().get(
        pk=member_id, profile=profile, state=ProviderTeamMember.State.ACTIVE,
    )
    member.state = ProviderTeamMember.State.REVOKED
    member.revoked_at = timezone.now()
    member.revoked_by = user
    member.save(update_fields=("state", "revoked_at", "revoked_by"))
    return member
