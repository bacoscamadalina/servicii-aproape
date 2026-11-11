"""Reusable fixtures and focused tests for private representation evidence."""

import hashlib

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils import timezone

from .models import ProviderRepresentationEvidence
from .representation_evidence import representation_evidence_values


EVIDENCE_BYTES = b"%PDF-1.4\n% ServiciiAproape synthetic test proof\n%%EOF\n"


def representation_evidence_upload():
    """Return a fresh upload because Django consumes file objects during validation."""

    return SimpleUploadedFile(
        "dovada-reprezentare.pdf",
        EVIDENCE_BYTES,
        content_type="application/pdf",
    )


def create_representation_evidence(*, claim=None, registration=None):
    """Attach one internally consistent synthetic proof to exactly one request."""

    return ProviderRepresentationEvidence.objects.create(
        claim=claim,
        registration=registration,
        evidence_type=ProviderRepresentationEvidence.EvidenceType.ONRC_DOCUMENT,
        document=EVIDENCE_BYTES,
        mime_type="application/pdf",
        byte_size=len(EVIDENCE_BYTES),
        sha256=hashlib.sha256(EVIDENCE_BYTES).hexdigest(),
        declaration_version="test-representation-v1",
        declared_at=timezone.now(),
    )


class RepresentationEvidenceValidationTests(SimpleTestCase):
    """Reject mislabeled or undeclared private documents."""

    def test_validation_uses_file_signature_not_browser_content_type(self):
        upload = SimpleUploadedFile(
            "pretinsa-dovada.pdf", b"not a pdf", content_type="application/pdf"
        )

        with self.assertRaisesMessage(ValueError, "PDF, JPEG sau PNG valide"):
            representation_evidence_values(
                evidence_type="onrc_document", upload=upload, declaration=True
            )

    def test_declaration_is_required_before_document_is_read(self):
        with self.assertRaisesMessage(ValueError, "dreptul de a transmite"):
            representation_evidence_values(
                evidence_type="onrc_document",
                upload=representation_evidence_upload(),
                declaration=False,
            )
