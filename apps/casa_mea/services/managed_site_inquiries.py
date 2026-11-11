"""Audited operator transitions for separately contracted Partner work."""

from django.db import transaction

from .models import ManagedSiteInquiry, ManagedSiteInquiryEvent


WORKFLOW_POLICY_VERSION = "2026-09-15-v1"
PROCESS_ACKNOWLEDGEMENT = "PARTNER_INQUIRY_STATUS_REVIEWED"

ALLOWED_TRANSITIONS = {
    ManagedSiteInquiry.Status.RECEIVED: (
        ManagedSiteInquiry.Status.CONTACTED,
        ManagedSiteInquiry.Status.CLOSED,
    ),
    ManagedSiteInquiry.Status.CONTACTED: (
        ManagedSiteInquiry.Status.PROPOSAL_SENT,
        ManagedSiteInquiry.Status.CLOSED,
    ),
    ManagedSiteInquiry.Status.PROPOSAL_SENT: (
        ManagedSiteInquiry.Status.ACCEPTED,
        ManagedSiteInquiry.Status.CLOSED,
    ),
}


def allowed_managed_site_inquiry_transitions(status):
    """Return the only forward transitions permitted from one persisted status."""

    return ALLOWED_TRANSITIONS.get(status, ())


def transition_managed_site_inquiry(
    *, inquiry_id, actor, expected_revision, new_status, internal_note, acknowledgement
):
    """Lock, validate and journal one state transition without changing entitlements."""

    if not actor.has_perm("services.process_managed_site_inquiry"):
        raise PermissionError("Lipsește permisiunea de procesare a solicitării.")
    if acknowledgement != PROCESS_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea regulilor de procesare lipsește.")
    normalized_note = " ".join(internal_note.split())
    if len(normalized_note) < 10:
        raise ValueError("Nota internă trebuie să explice acțiunea efectuată.")

    with transaction.atomic():
        inquiry = ManagedSiteInquiry.objects.select_for_update().get(pk=inquiry_id)
        if inquiry.retention_applied_at is not None:
            raise ValueError("Solicitarea a trecut prin retenție și nu mai poate fi procesată.")
        if inquiry.revision != expected_revision:
            raise ValueError("Solicitarea a fost modificată. Reîncarcă pagina și reia acțiunea.")
        if new_status not in allowed_managed_site_inquiry_transitions(inquiry.status):
            raise ValueError("Tranziția solicitată nu este permisă din starea curentă.")

        previous_status = inquiry.status
        inquiry.status = new_status
        inquiry.revision += 1
        inquiry.save(update_fields=("status", "revision", "updated_at"))
        ManagedSiteInquiryEvent.objects.create(
            inquiry=inquiry,
            previous_status=previous_status,
            new_status=new_status,
            revision=inquiry.revision,
            internal_note=normalized_note,
            policy_version=WORKFLOW_POLICY_VERSION,
            acknowledgement=acknowledgement,
            actor=actor,
        )
    return inquiry
