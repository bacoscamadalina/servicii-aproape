"""Validation for private documents proving a claimant's representation status."""

import hashlib

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import ProviderRepresentationEvidence


MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
DECLARATION_VERSION = f"{settings.LEGAL_POLICY_VERSION}-representation-v1"


def representation_evidence_values(*, evidence_type: str, upload, declaration: bool):
    """Read and validate one bounded PDF/JPEG/PNG proof for transactional storage."""

    if not declaration:
        raise ValueError(_("Confirmă dreptul de a transmite documentul."))
    if evidence_type not in ProviderRepresentationEvidence.EvidenceType.values:
        raise ValueError(_("Alege un tip valid de dovadă."))
    if upload is None:
        raise ValueError(_("Încarcă documentul care dovedește dreptul de reprezentare."))
    if getattr(upload, "size", MAX_EVIDENCE_BYTES + 1) > MAX_EVIDENCE_BYTES:
        raise ValueError(_("Documentul poate avea maximum 5 MB."))
    content = upload.read(MAX_EVIDENCE_BYTES + 1)
    if not content or len(content) > MAX_EVIDENCE_BYTES:
        raise ValueError(_("Documentul este gol sau depășește limita de 5 MB."))
    mime_type = (
        "application/pdf"
        if content.startswith(b"%PDF-")
        else "image/jpeg"
        if content.startswith(b"\xff\xd8\xff")
        else "image/png"
        if content.startswith(b"\x89PNG\r\n\x1a\n")
        else ""
    )
    if not mime_type:
        raise ValueError(_("Sunt acceptate numai documente PDF, JPEG sau PNG valide."))
    return {
        "evidence_type": evidence_type,
        "document": content,
        "mime_type": mime_type,
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "declaration_version": DECLARATION_VERSION,
        "declared_at": timezone.now(),
    }


def representation_evidence_is_valid(evidence) -> bool:
    """Recheck immutable bytes and metadata at the approval boundary."""

    if evidence is None:
        return False
    content = bytes(evidence.document)
    return bool(
        evidence.evidence_type in ProviderRepresentationEvidence.EvidenceType.values
        and content
        and len(content) == evidence.byte_size
        and len(content) <= MAX_EVIDENCE_BYTES
        and hashlib.sha256(content).hexdigest() == evidence.sha256
        and evidence.declaration_version
        and evidence.declared_at
    )
