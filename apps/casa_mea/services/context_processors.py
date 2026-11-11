"""Shared language navigation for every non-administrative page."""

from django.conf import settings
from django.urls import translate_url
from django.utils.translation import get_language


def language_navigation(request):
    """Build equivalent Romanian and English URLs while preserving query state."""

    current_path = request.get_full_path()
    language_url_ro = translate_url(current_path, "ro")
    language_url_en = translate_url(current_path, "en")
    current_language = get_language() or "ro"
    return {
        "current_language": current_language,
        "language_url_ro": language_url_ro,
        "language_url_en": language_url_en,
        "absolute_language_url_ro": request.build_absolute_uri(language_url_ro),
        "absolute_language_url_en": request.build_absolute_uri(language_url_en),
        "absolute_language_url_current": request.build_absolute_uri(
            language_url_en if current_language == "en" else language_url_ro
        ),
    }


def legal_information(request):
    """Expose deployment-owned legal identity without duplicating view context."""

    return {
        "legal_operator_name": settings.LEGAL_OPERATOR_NAME,
        "legal_operator_address": settings.LEGAL_OPERATOR_ADDRESS,
        "privacy_email": settings.PRIVACY_EMAIL,
        "commercial_email": settings.COMMERCIAL_EMAIL,
        "legal_policy_version": settings.LEGAL_POLICY_VERSION,
        "retention_unverified_claim_days": settings.RETENTION_UNVERIFIED_CLAIM_DAYS,
        "retention_rejected_claim_days": settings.RETENTION_REJECTED_CLAIM_DAYS,
        "retention_closed_report_days": settings.RETENTION_CLOSED_REPORT_DAYS,
        "retention_closed_data_request_days": settings.RETENTION_CLOSED_DATA_REQUEST_DAYS,
        "retention_closed_provider_lead_days": settings.RETENTION_CLOSED_PROVIDER_LEAD_DAYS,
        "retention_managed_site_inquiry_days": settings.RETENTION_MANAGED_SITE_INQUIRY_DAYS,
    }


def provider_shortlist_navigation(request):
    """Expose only bounded saved-record counts needed by public navigation."""

    entries = (
        request.session.get("provider_shortlist_v1", ())
        if hasattr(request, "session")
        else ()
    )
    registry_entries = (
        request.session.get("registry_shortlist_v1", ())
        if hasattr(request, "session")
        else ()
    )
    return {
        "saved_provider_count": (
            (min(len(entries), 6) if isinstance(entries, list) else 0)
            + (min(len(registry_entries), 6) if isinstance(registry_entries, list) else 0)
        )
    }
