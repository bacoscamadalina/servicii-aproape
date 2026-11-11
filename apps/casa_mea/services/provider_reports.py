"""Privacy-minimized intake for reports about visible provider snapshots."""

import hashlib
import hmac

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from .models import PublicProviderReport, PublicProviderReportCase


@transaction.atomic
def create_public_provider_report(*, submission, reason: str, details: str, session_key: str):
    """Persist at most one immutable report per browser session and snapshot."""

    if not session_key:
        raise ValueError(_("Sesiunea nu este disponibilă. Reîncarcă pagina și încearcă din nou."))
    normalized_details = " ".join(details.split())
    if reason not in PublicProviderReport.Reason.values or not normalized_details:
        raise ValueError(_("Sesizarea nu este validă."))
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"public-provider-report:{session_key}".encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        report, created = PublicProviderReport.objects.get_or_create(
            submission=submission,
            reporter_session_digest=digest,
            defaults={"reason": reason, "details": normalized_details},
        )
    except IntegrityError:
        report = PublicProviderReport.objects.get(
            submission=submission,
            reporter_session_digest=digest,
        )
        created = False
    # Every report owns a stable lock row before it enters the administrative queue.
    PublicProviderReportCase.objects.get_or_create(report=report)
    return report, created
