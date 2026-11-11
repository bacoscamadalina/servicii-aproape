"""Eligibility, submission, and moderation for verified customer reviews."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    ProviderCustomerReview,
    ProviderCustomerReviewEvent,
    ProviderCustomerReviewReply,
    ProviderCustomerReviewReplyEvent,
    ProviderLead,
    ProviderMembership,
    ProviderQuote,
)


MODERATION_ACKNOWLEDGEMENT = (
    "Confirm că am verificat recenzia și eligibilitatea solicitării asociate."
)
REPLY_MODERATION_ACKNOWLEDGEMENT = (
    "Confirm că am verificat răspunsul firmei și recenzia asociată."
)


def customer_may_review(lead: ProviderLead) -> bool:
    """Allow feedback only after this customer accepted a real platform quote."""

    return (
        lead.retention_applied_at is None
        and lead.quotes.filter(status=ProviderQuote.Status.ACCEPTED).exists()
    )


@transaction.atomic
def submit_customer_review(*, lead: ProviderLead, rating: int, body: str):
    """Create the customer's only immutable review in a pending state."""

    normalized_body = " ".join(body.split())
    if rating not in range(1, 6):
        raise ValueError(_("Evaluarea trebuie să fie între 1 și 5."))
    if not 30 <= len(normalized_body) <= 1200:
        raise ValueError(_("Recenzia trebuie să aibă între 30 și 1200 de caractere."))
    locked_lead = ProviderLead.objects.select_for_update().select_related(
        "submission__profile"
    ).get(pk=lead.pk)
    if not customer_may_review(locked_lead):
        raise ValueError(_("Recenzia devine disponibilă după acceptarea unei oferte."))
    if ProviderCustomerReview.objects.filter(lead=locked_lead).exists():
        raise ValueError(_("Ai trimis deja o recenzie pentru această lucrare."))
    name_parts = locked_lead.customer_name.split()
    display_name = name_parts[0]
    if len(name_parts) > 1:
        display_name = f"{display_name} {name_parts[-1][0].upper()}."
    return ProviderCustomerReview.objects.create(
        lead=locked_lead,
        profile=locked_lead.submission.profile,
        rating=rating,
        body=normalized_body,
        reviewer_display_name=display_name,
        consent_policy_version=settings.LEGAL_POLICY_VERSION,
    )


@transaction.atomic
def moderate_customer_review(
    *, review_id: int, actor, decision: str, internal_note: str, acknowledgement: str
):
    """Record one final moderation decision without changing review content."""

    if not actor.has_perm("services.moderate_customer_review"):
        raise PermissionError("Nu ai permisiunea de a modera recenzii.")
    if acknowledgement != MODERATION_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea deciziei nu este validă.")
    review = ProviderCustomerReview.objects.select_for_update().get(pk=review_id)
    if review.status != ProviderCustomerReview.Status.PENDING:
        raise ValueError("Recenzia are deja o decizie finală.")
    if decision not in {
        ProviderCustomerReview.Status.APPROVED,
        ProviderCustomerReview.Status.REJECTED,
    }:
        raise ValueError("Decizia nu este validă.")
    note = " ".join(internal_note.split())
    if not note:
        raise ValueError("Motivul deciziei este obligatoriu.")
    review.status = decision
    review.reviewed_at = timezone.now()
    review.reviewed_by = actor
    review.moderation_note = note
    review.save(
        update_fields=("status", "reviewed_at", "reviewed_by", "moderation_note")
    )
    ProviderCustomerReviewEvent.objects.create(
        review=review,
        decision=decision,
        internal_note=note,
        policy_version=settings.LEGAL_POLICY_VERSION,
        acknowledgement=acknowledgement,
        actor=actor,
    )
    return review


@transaction.atomic
def submit_provider_review_reply(*, user, review_id: int, body: str):
    """Create the active owner's only immutable response to an approved review."""

    review = ProviderCustomerReview.objects.select_for_update().select_related(
        "profile"
    ).get(pk=review_id)
    owns_profile = ProviderMembership.objects.filter(
        user=user,
        profile=review.profile,
        state=ProviderMembership.State.ACTIVE,
        user__is_active=True,
    ).exists()
    normalized_body = " ".join(body.split())
    if not owns_profile:
        raise PermissionError(_("Nu poți răspunde acestei recenzii."))
    if review.status != ProviderCustomerReview.Status.APPROVED:
        raise ValueError(_("Poți răspunde numai unei recenzii publicate."))
    if not 20 <= len(normalized_body) <= 1200:
        raise ValueError(_("Răspunsul trebuie să aibă între 20 și 1200 de caractere."))
    if ProviderCustomerReviewReply.objects.filter(review=review).exists():
        raise ValueError(_("Firma a răspuns deja acestei recenzii."))
    return ProviderCustomerReviewReply.objects.create(
        review=review,
        profile=review.profile,
        body=normalized_body,
        submitted_by=user,
    )


@transaction.atomic
def moderate_provider_review_reply(
    *, reply_id: int, actor, decision: str, internal_note: str, acknowledgement: str
):
    """Record one final moderation decision without changing response content."""

    if not actor.has_perm("services.moderate_customer_review_reply"):
        raise PermissionError("Nu ai permisiunea de a modera răspunsuri.")
    if acknowledgement != REPLY_MODERATION_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea deciziei nu este validă.")
    reply = ProviderCustomerReviewReply.objects.select_for_update().get(pk=reply_id)
    if reply.status != ProviderCustomerReviewReply.Status.PENDING:
        raise ValueError("Răspunsul are deja o decizie finală.")
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decizia nu este validă.")
    note = " ".join(internal_note.split())
    if not note:
        raise ValueError("Motivul deciziei este obligatoriu.")
    reply.status = decision
    reply.reviewed_at = timezone.now()
    reply.reviewed_by = actor
    reply.moderation_note = note
    reply.save(update_fields=("status", "reviewed_at", "reviewed_by", "moderation_note"))
    ProviderCustomerReviewReplyEvent.objects.create(
        reply=reply,
        decision=decision,
        internal_note=note,
        policy_version=settings.LEGAL_POLICY_VERSION,
        acknowledgement=acknowledgement,
        actor=actor,
    )
    return reply
