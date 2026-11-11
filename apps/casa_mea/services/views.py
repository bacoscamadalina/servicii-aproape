import logging
import secrets
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    JsonResponse,
)
from django.db import transaction
from django.db.models import Avg, BooleanField, Case, Count, DateTimeField, DecimalField, Exists, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, Greatest, TruncDate
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse, reverse_lazy
from django.utils import formats
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .catalogue_activation import catalogue_state
from .catalog import CATEGORIES, PROVIDERS
from .service_category_policies import (
    editable_provider_service_slugs,
    new_provider_service_categories,
    publicly_discoverable_service_categories,
    service_category_records,
)
from .registry_catalogue import catalogue_categories
from .forms import (
    ProviderActivationForm,
    ProviderClaimForm,
    ProviderRegistrationForm,
    ProviderLoginForm,
    CustomerLoginForm,
    CustomerPasswordResetForm,
    CustomerRegistrationForm,
    ProviderLeadForm,
    GeneralProviderLeadForm,
    ManagedSiteInquiryForm,
    ProviderCustomerReviewForm,
    ProviderCustomerReviewReplyForm,
    ProviderLeadMessageForm,
    ProviderVisitProposalForm,
    ProviderLeadUpdateForm,
    ProviderQuoteForm,
    ProviderOwnerCommandForm,
    ProviderCRMCustomerForm,
    ProviderCRMCustomerArchiveForm,
    ProviderCRMCustomerFromLeadForm,
    ProviderCRMCustomerLinkForm,
    ProviderWorkOrderScheduleForm,
    ProviderWorkOrderCancelForm,
    ProviderWorkOrderCompleteForm,
    ProviderTeamInviteForm,
    ProviderTeamNewAccountForm,
    ProviderTeamExistingAccountForm,
    ProviderWorkAssignmentForm,
    ProviderInvoiceDraftForm,
    ProviderReceivableForm,
    ProviderManualPaymentForm,
    ProviderManualPaymentVoidForm,
    ProviderReceivableFollowUpForm,
    ProviderReceivableFollowUpCompleteForm,
    ProviderBillingIdentityForm,
    AccountPasswordChangeForm,
    ProviderPasswordResetForm,
    ProviderProfileForm,
    ProviderPortfolioUploadForm,
    ProviderPublicationSubmitForm,
    ProviderSimulatedCheckoutForm,
    PublicProviderReportForm,
    ProviderSearchForm,
    ProviderServiceAreaSubmitForm,
    ProviderServicesCoverageForm,
)
from .locations import county_choices, locality_choices, locality_code, locality_name
from .owner_commands import owner_command_kind, parse_quote_command
from .models import (
    BusinessIdentity,
    CustomerAccount,
    ManagedSiteInquiry,
    ProviderLead,
    ProviderLeadBatch,
    ProviderCustomerReview,
    ProviderCustomerReviewReply,
    ProviderLeadMessage,
    ProviderQuote,
    ProviderWorkOrder,
    ProviderManualPayment,
    ProviderInvoiceDraft,
    ProviderReceivable,
    ProviderCRMCustomer,
    ProviderTeamMember,
    ProviderTeamInvitation,
    ProviderVisitProposal,
    ProviderProfile,
    ProviderPortfolioItem,
    ProviderPublicationScope,
    ProviderPublicationSubmission,
    ProviderRegistrationRequest,
    ProviderServiceAreaDraft,
    ProviderServiceAreaSubmission,
    ProviderSubscriptionEvent,
)
from .provider_claims import (
    PRIVACY_NOTICE_VERSION,
    create_provider_claim_request,
    provider_claim_for_token,
    verify_provider_claim_email,
)


security_logger = logging.getLogger("services.security")
from .provider_registrations import (
    create_provider_registration_request,
    provider_registration_for_token,
    verify_provider_registration_email,
)
from .provider_access import (
    activate_provider_invitation,
    active_provider_membership,
    claim_account_login_attempt,
    claim_password_reset_send_slot,
    clear_account_login_attempts,
    provider_invitation_for_token,
)
from .provider_team import (
    active_provider_team_member,
    assigned_provider_work_for_technician,
    issue_provider_team_invitation,
    pending_provider_team_invitation,
    accept_provider_team_invitation,
    revoke_provider_team_invitation,
    revoke_provider_technician,
    assign_provider_technician,
    update_assigned_work_execution,
)
from .provider_analytics import (
    ANALYTICS_PERIODS,
    provider_engagement_metrics,
    record_provider_engagement,
)
from .provider_offerings import (
    ProviderDraftRevisionConflict,
    may_prepare_unverified_offering_draft,
    provider_authorization,
    replace_provider_services_and_coverage_for_owner,
    submit_provider_service_area_for_review,
)
from .provider_publication import (
    add_portfolio_images_for_owner,
    portfolio_asset_for_request,
    provider_publication_effective_visibility,
    provider_publication_readiness,
    published_provider_detail,
    published_provider_search,
    remove_portfolio_item_for_owner,
    save_provider_profile_for_owner,
    submit_provider_publication_for_review,
    unpublish_provider_profile,
    visible_provider_submission,
)
from .provider_subscriptions import (
    SIMULATED_CHECKOUT_ACKNOWLEDGEMENT,
    SIMULATED_CHECKOUT_POLICY_VERSION,
    activate_provider_subscription_from_simulated_checkout,
    provider_subscription_state,
)
from .provider_leads import (
    allowed_provider_lead_statuses,
    create_provider_lead,
    create_provider_lead_batch,
    add_provider_lead_message,
    deliver_conversation_notification,
    deliver_customer_access_notification,
    deliver_customer_batch_access_notification,
    deliver_provider_lead_notification,
    provider_lead_for_customer,
    provider_lead_for_customer_account,
    provider_lead_batch_for_customer,
    provider_lead_batch_for_customer_account,
    provider_lead_metrics,
    provider_lead_focus_url,
    provider_lead_recipient,
    provider_leads_for_owner,
    respond_to_provider_quote,
    respond_to_provider_visit,
    cancel_provider_visit_for_customer,
    cancel_provider_visit_for_owner,
    respond_to_batch_provider_quote,
    send_provider_quote,
    propose_provider_visit,
    schedule_provider_work_order,
    cancel_provider_work_schedule,
    complete_provider_work_order,
    save_provider_invoice_draft,
    update_provider_lead_for_owner,
)
from .provider_billing import save_provider_billing_identity
from .provider_receivables import (
    open_provider_receivable,
    provider_receivable_totals,
    provider_outstanding_receivable_summary,
    record_provider_manual_payment,
    schedule_provider_receivable_follow_up,
    complete_provider_receivable_follow_up,
    void_provider_manual_payment,
)
from .provider_reports import create_public_provider_report
from .provider_customers import (
    archive_provider_customer,
    create_and_link_provider_customer_from_lead,
    link_provider_customer_to_lead,
    provider_customers_for_owner,
    save_provider_customer,
)
from .provider_reviews import (
    customer_may_review,
    submit_customer_review,
    submit_provider_review_reply,
)
from .customer_accounts import active_customer_account, register_customer_account
from .registry_catalogue import registry_company_detail, registry_search
from . import preview_catalogue


PROVIDER_SHORTLIST_SESSION_KEY = "provider_shortlist_v1"
PROVIDER_SHORTLIST_LIMIT = 6
REGISTRY_SHORTLIST_SESSION_KEY = "registry_shortlist_v1"
PROVIDER_LEAD_PAGE_SIZE = 6
PROVIDER_LEAD_STATUS_FILTERS = {
    "all": (),
    "new": (ProviderLead.Status.NEW,),
    "active": (
        ProviderLead.Status.CONTACTED,
        ProviderLead.Status.VISIT_SCHEDULED,
        ProviderLead.Status.QUOTE_SENT,
    ),
    "accepted": (ProviderLead.Status.WON, ProviderLead.Status.COMPLETED),
    "declined": (ProviderLead.Status.DECLINED,),
}


def _public_category_choices():
    """Project the current discoverable taxonomy into trusted form choices."""

    return tuple(
        (record.slug, record.label)
        for record in publicly_discoverable_service_categories()
    )


def _shortlist_entries(request):
    """Return structurally valid, bounded shortlist entries from this browser session."""

    if not hasattr(request, "session"):
        return ()
    entries = request.session.get(PROVIDER_SHORTLIST_SESSION_KEY, ())
    if not isinstance(entries, list):
        return ()
    valid = []
    for entry in entries[:PROVIDER_SHORTLIST_LIMIT]:
        if not isinstance(entry, dict):
            continue
        try:
            UUID(str(entry.get("public_id", "")))
        except (TypeError, ValueError):
            continue
        if all(isinstance(entry.get(key), str) for key in ("county", "locality", "category")):
            valid.append(entry)
    return tuple(valid)


def _registry_shortlist_entries(request):
    """Read only bounded catalogue identities and exact scopes from the session."""

    entries = request.session.get(REGISTRY_SHORTLIST_SESSION_KEY, ()) if hasattr(request, "session") else ()
    if not isinstance(entries, list):
        return ()
    return tuple(
        entry for entry in entries[:PROVIDER_SHORTLIST_LIMIT]
        if isinstance(entry, dict)
        and type(entry.get("business_id")) is int
        and entry["business_id"] > 0
        and all(isinstance(entry.get(key), str) for key in ("county", "locality", "category"))
    )


def _local_service_url(county: str, siruta_code: str, category: str) -> str:
    """Build the one canonical, collision-safe URL for a local service page."""

    try:
        return reverse(
            "services:local_service",
            kwargs={
                "category": category,
                "county_slug": slugify(county),
                "locality_slug": slugify(locality_name(county, siruta_code)),
                "siruta_code": siruta_code,
            },
        )
    except NoReverseMatch:
        # The packaged read-only preview deliberately exposes a reduced URLconf.
        query = urlencode(
            {"county": county, "locality": siruta_code, "category": category}
        )
        return f'{reverse("services:home")}?{query}#rezultate'


def _catalogue_search_context(request, form: ProviderSearchForm) -> dict:
    """Project one valid location/service search through the active catalogue boundary."""

    county = form.cleaned_data["county"]
    siruta_code = form.cleaned_data["locality"]
    selected_locality = locality_name(county, siruta_code) if siruta_code else ""
    category = form.cleaned_data["category"]
    read_only = getattr(settings, "READ_ONLY_PREVIEW", False)
    packaged_catalogue = getattr(settings, "PACKAGED_CATALOGUE", False)
    state = (
        preview_catalogue.catalogue_state(county)
        if read_only or packaged_catalogue
        else catalogue_state(county)
    )
    results = ()
    catalogue_mode = "none"
    registry_page = None
    registry_source = None
    result_count = 0
    category_unsupported = False
    published_profiles = ()

    if state.status == "active":
        catalogue_mode = "registry_preview" if state.preview else "registry"
        category_unsupported = bool(
            category and category not in catalogue_categories(state.run)
        )
        if not category_unsupported:
            published_profiles = () if read_only else published_provider_search(
                county=county,
                siruta_code=siruta_code or None,
                category=category,
            )
            search = (
                preview_catalogue.registry_search
                if read_only or packaged_catalogue
                else registry_search
            )
            registry_source = search(
                run=state.run,
                county=county,
                allow_direct_evidence=state.preview,
                siruta_code=siruta_code or None,
                locality_label=selected_locality,
                category=category,
                page_number=request.GET.get("page", "1"),
                exclude_business_ids=tuple(
                    provider.business_id for provider in published_profiles
                ),
            )
            registry_page = registry_source.page
            results = registry_page.object_list
            result_count = registry_source.total
    elif state.status == "unavailable":
        catalogue_mode = "unavailable"
    else:
        catalogue_mode = "demo"
        results = tuple(
            provider
            for provider in PROVIDERS
            if provider.county.casefold() == county.casefold()
            and (
                not selected_locality
                or provider.locality.casefold() == selected_locality.casefold()
            )
            and (not category or provider.category == category)
        )
        result_count = len(results)

    preserved_query = request.GET.copy()
    preserved_query.pop("page", None)
    return {
        "results": results,
        "selected_county": county,
        "selected_locality_code": siruta_code,
        "selected_locality": selected_locality,
        "catalogue_mode": catalogue_mode,
        "category_unsupported": category_unsupported,
        "registry_page": registry_page,
        "registry_source": registry_source,
        "result_count": result_count,
        "result_count_display": formats.number_format(
            result_count, use_l10n=True, force_grouping=True
        ),
        "result_count_is_singular": result_count == 1,
        "pagination_query": preserved_query.urlencode(),
        "published_profiles": published_profiles,
        "write_features_enabled": not read_only,
    }


def home(request):
    """Search an active registry catalogue or a clearly marked demo fallback."""

    searched = any(request.GET.get(field) for field in ("county", "locality", "category"))
    form_data = request.GET.copy() if searched else None
    if form_data and form_data.get("locality") and not form_data["locality"].isdigit():
        resolved_code = locality_code(form_data.get("county", ""), form_data["locality"])
        if resolved_code:
            form_data["locality"] = resolved_code
    public_categories = publicly_discoverable_service_categories()
    form = ProviderSearchForm(
        form_data,
        category_choices=tuple(
            (record.slug, record.label) for record in public_categories
        ),
    )
    search_context = (
        _catalogue_search_context(request, form)
        if searched and form.is_valid()
        else {
            "results": (),
            "selected_county": "",
            "selected_locality_code": "",
            "selected_locality": "",
            "catalogue_mode": "none",
            "category_unsupported": False,
            "registry_page": None,
            "registry_source": None,
            "result_count": 0,
            "result_count_display": "0",
            "result_count_is_singular": False,
            "pagination_query": "",
            "published_profiles": (),
            "write_features_enabled": not getattr(settings, "READ_ONLY_PREVIEW", False),
        }
    )
    card_county = search_context["selected_county"] or "Iași"
    card_locality = search_context["selected_locality_code"] or "95079"

    return render(
        request,
        "services/home.html",
        {
            "categories": tuple(
                (record.slug, record.label, record.description)
                for record in public_categories
            ),
            "form": form,
            "searched": searched,
            "category_cards": tuple(
                (
                    slug,
                    label,
                    description,
                    _local_service_url(card_county, card_locality, slug),
                )
                for slug, label, description in (
                    (record.slug, record.label, record.description)
                    for record in public_categories
                )
            ),
            **search_context,
        },
    )


def local_service(request, category, county_slug, locality_slug, siruta_code):
    """Render one canonical locality/category landing page through normal search gates."""

    public_categories = publicly_discoverable_service_categories()
    category_record = next(
        (record for record in public_categories if record.slug == category), None
    )
    county = next(
        (name for name, _label in county_choices() if slugify(name) == county_slug), ""
    )
    selected_locality = locality_name(county, siruta_code)
    if category_record is None or not county or not selected_locality:
        raise Http404(_("Pagina locală nu este disponibilă"))

    canonical_url = _local_service_url(county, siruta_code, category)
    if request.path != canonical_url:
        page = request.GET.get("page", "")
        suffix = f"?{urlencode({'page': page})}" if page.isdigit() and int(page) > 1 else ""
        return HttpResponsePermanentRedirect(f"{canonical_url}{suffix}")

    form = ProviderSearchForm(
        {"county": county, "locality": siruta_code, "category": category},
        category_choices=tuple(
            (record.slug, record.label) for record in public_categories
        ),
    )
    if not form.is_valid():
        raise Http404(_("Pagina locală nu este disponibilă"))
    search_context = _catalogue_search_context(request, form)
    response = render(
        request,
        "services/local_service.html",
        {
            "form": form,
            "category_slug": category_record.slug,
            "category_label": category_record.label,
            "category_description": category_record.description,
            "art_photo": f"services/category-photos/{category_record.slug}.webp",
            "alternative_categories": tuple(
                (
                    slug,
                    label,
                    _local_service_url(county, siruta_code, slug),
                )
                for slug, label in (
                    (record.slug, record.label) for record in public_categories
                )
                if slug != category
            ),
            **search_context,
        },
    )
    if search_context["catalogue_mode"] != "registry":
        response.headers["X-Robots-Tag"] = "noindex, follow"
    return response


def professionals(request):
    """Explain the controlled path from catalogue record to provider account."""

    return render(request, "services/professionals.html")


def subscription_plan(request):
    """Publish the offer and expose only the explicitly enabled simulation path."""

    return render(
        request,
        "services/subscription_plan.html",
        {
            "monthly_price_ron": settings.SUBSCRIPTION_MONTHLY_PRICE_RON,
            "managed_site_monthly_price_ron": settings.MANAGED_SITE_MONTHLY_PRICE_RON,
            "simulated_checkout_enabled": settings.SIMULATED_CHECKOUT_ENABLED,
        },
    )


@never_cache
@login_required(login_url="services:provider_login")
def provider_simulated_checkout(request):
    """Simulate checkout without accepting or transmitting financial data."""

    if (
        not settings.SIMULATED_CHECKOUT_ENABLED
        or getattr(settings, "READ_ONLY_PREVIEW", False)
    ):
        raise Http404(_("Fluxul demonstrativ de abonare nu este disponibil."))
    membership = active_provider_membership(request.user)
    if membership is None:
        raise PermissionDenied
    profile = membership.profile
    subscription_state = provider_subscription_state(profile)
    simulated_event_exists = ProviderSubscriptionEvent.objects.filter(
        subscription__profile=profile,
        actor=request.user,
        policy_version=SIMULATED_CHECKOUT_POLICY_VERSION,
    ).exists()
    if subscription_state.is_active:
        if simulated_event_exists:
            return redirect("services:provider_simulated_checkout_success")
        messages.info(request, _("Abonamentul profilului este deja activ."))
        return redirect("services:provider_dashboard")

    form = ProviderSimulatedCheckoutForm(
        request.POST or None,
        initial={"expected_revision": subscription_state.revision},
    )
    if request.method == "POST" and form.is_valid():
        try:
            _subscription, activated = activate_provider_subscription_from_simulated_checkout(
                profile_id=profile.pk,
                actor=request.user,
                expected_revision=form.cleaned_data["expected_revision"],
                acknowledgement=SIMULATED_CHECKOUT_ACKNOWLEDGEMENT,
            )
        except (PermissionError, ValueError) as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Simularea a fost finalizată, iar abonamentul demo este activ 30 de zile.")
                if activated
                else _("Abonamentul demo era deja activ."),
            )
            return redirect("services:provider_simulated_checkout_success")

    response = render(
        request,
        "services/provider_simulated_checkout.html",
        {
            "profile": profile,
            "checkout_form": form,
            "monthly_price_ron": settings.SUBSCRIPTION_MONTHLY_PRICE_RON,
        },
    )
    response.headers["X-Robots-Tag"] = "noindex, noarchive"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@never_cache
@login_required(login_url="services:provider_login")
def provider_simulated_checkout_success(request):
    """Show the audited result of the current provider's simulated activation."""

    if (
        not settings.SIMULATED_CHECKOUT_ENABLED
        or getattr(settings, "READ_ONLY_PREVIEW", False)
    ):
        raise Http404(_("Fluxul demonstrativ de abonare nu este disponibil."))
    membership = active_provider_membership(request.user)
    if membership is None:
        raise PermissionDenied
    profile = membership.profile
    subscription_state = provider_subscription_state(profile)
    checkout_event = (
        ProviderSubscriptionEvent.objects.filter(
            subscription__profile=profile,
            actor=request.user,
            policy_version=SIMULATED_CHECKOUT_POLICY_VERSION,
        )
        .select_related("subscription")
        .order_by("-created_at", "-id")
        .first()
    )
    if not subscription_state.is_active:
        return redirect("services:provider_simulated_checkout")
    if checkout_event is None:
        messages.info(request, _("Abonamentul profilului este activ, fără o simulare asociată."))
        return redirect("services:provider_dashboard")
    response = render(
        request,
        "services/provider_simulated_checkout_success.html",
        {
            "profile": profile,
            "subscription_state": subscription_state,
            "checkout_event": checkout_event,
        },
    )
    response.headers["X-Robots-Tag"] = "noindex, noarchive"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@never_cache
@login_required(login_url="services:provider_login")
def managed_site_inquiry(request):
    """Record a bounded Partner brief for one authenticated provider owner."""

    if getattr(settings, "READ_ONLY_PREVIEW", False):
        raise Http404(_("Solicitările pentru planul Partener nu sunt disponibile."))
    membership = active_provider_membership(request.user)
    if membership is None:
        raise PermissionDenied
    form = ManagedSiteInquiryForm(request.POST or None)
    inquiry = None
    if request.method == "POST" and form.is_valid():
        now = timezone.now()
        with transaction.atomic():
            profile = ProviderProfile.objects.select_for_update().get(
                pk=membership.profile_id
            )
            recent_count = ManagedSiteInquiry.objects.filter(
                profile=profile,
                created_at__gte=now - timedelta(days=1),
            ).count()
            if recent_count >= 3:
                form.add_error(
                    None,
                    _(
                        "Ai trimis deja mai multe solicitări astăzi. Echipa noastră te va contacta în baza celor existente."
                    ),
                )
            else:
                inquiry = ManagedSiteInquiry.objects.create(
                    profile=profile,
                    created_by=request.user,
                    goal=form.cleaned_data["goal"],
                    desired_launch=form.cleaned_data["desired_launch"],
                    current_website=form.cleaned_data["current_website"],
                    brief=form.cleaned_data["brief"],
                    privacy_notice_version=PRIVACY_NOTICE_VERSION,
                    consented_at=now,
                )
        if inquiry is not None:
            try:
                send_mail(
                    subject=f"Solicitare nouă pentru planul Partener — #{inquiry.pk}",
                    message=(
                        "A fost înregistrată o solicitare pentru serviciul Partener.\n\n"
                        f"Solicitare: #{inquiry.pk}\n"
                        f"Profil furnizor: {inquiry.profile.public_id}\n\n"
                        "Brief-ul și datele furnizorului sunt disponibile numai în "
                        "administrația ServiciiAproape."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.COMMERCIAL_EMAIL],
                    fail_silently=False,
                )
            except Exception:
                ManagedSiteInquiry.objects.filter(pk=inquiry.pk).update(
                    notification_state=ManagedSiteInquiry.NotificationState.FAILED
                )
                security_logger.exception(
                    "Managed-site inquiry notification failed.",
                    extra={
                        "event": "managed_site_inquiry_notification_failed",
                        "scope": "provider",
                    },
                )
            else:
                ManagedSiteInquiry.objects.filter(pk=inquiry.pk).update(
                    notification_state=ManagedSiteInquiry.NotificationState.SENT
                )
            return redirect("services:managed_site_inquiry_success")

    response = render(
        request,
        "services/managed_site_inquiry.html",
        {
            "profile": membership.profile,
            "inquiry_form": form,
            "managed_site_monthly_price_ron": settings.MANAGED_SITE_MONTHLY_PRICE_RON,
        },
    )
    response.headers["X-Robots-Tag"] = "noindex, noarchive"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@never_cache
@login_required(login_url="services:provider_login")
def managed_site_inquiry_success(request):
    """Confirm intake without exposing the private brief or a record identifier."""

    if getattr(settings, "READ_ONLY_PREVIEW", False):
        raise Http404(_("Solicitările pentru planul Partener nu sunt disponibile."))
    if active_provider_membership(request.user) is None:
        raise PermissionDenied
    response = render(request, "services/managed_site_inquiry_success.html")
    response.headers["X-Robots-Tag"] = "noindex, noarchive"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def privacy(request):
    """Explain the personal-data and necessary-cookie boundaries."""

    return render(request, "services/privacy.html")


def terms(request):
    """Publish the catalogue's operating limits and acceptable-use terms."""

    return render(request, "services/terms.html")


def localities(request):
    """Return locality options for a valid county as progressive enhancement."""

    county = request.GET.get("county", "")
    options = locality_choices(county)
    return JsonResponse(
        {"localities": [{"value": value, "label": label} for value, label in options]}
    )


def _active_company_context(request, business_id: int, scope=None) -> dict:
    """Resolve shared company-page context through the active catalogue reader."""

    read_only = getattr(settings, 'READ_ONLY_PREVIEW', False)
    packaged_catalogue = getattr(settings, 'PACKAGED_CATALOGUE', False)
    form = ProviderSearchForm(
        request.GET if scope is None else scope,
        category_choices=_public_category_choices(),
    )
    if not form.is_valid():
        raise Http404(_("Căutarea asociată firmei nu este validă"))
    county = form.cleaned_data["county"]
    siruta_code = form.cleaned_data["locality"]
    category = form.cleaned_data["category"]
    state = (
        preview_catalogue.catalogue_state(county)
        if read_only or packaged_catalogue
        else catalogue_state(county)
    )
    if (
        state.status != "active"
        or (category and category not in catalogue_categories(state.run))
    ):
        raise Http404(_("Firma nu este disponibilă în catalogul activ"))
    locality_label = locality_name(county, siruta_code) if siruta_code else ""
    detail_reader = (
        preview_catalogue.registry_company_detail
        if read_only or packaged_catalogue
        else registry_company_detail
    )
    detail = detail_reader(
        run=state.run,
        county=county,
        allow_direct_evidence=state.preview,
        siruta_code=siruta_code or None,
        locality_label=locality_label,
        category=category,
        business_id=business_id,
    )
    if detail is None:
        raise Http404(_("Firma nu este disponibilă pentru această căutare"))
    locality_label = detail.listing.registered_office_label

    back_parameters = {
        "county": county,
        "locality": siruta_code,
        "category": category,
    }
    return_page = request.GET.get("return_page", "") if scope is None else ""
    if return_page.isdigit() and int(return_page) > 1:
        back_parameters["page"] = return_page
    back_url = f'{reverse("services:home")}?{urlencode(back_parameters)}#rezultate'
    query = urlencode(
        {"county": county, "locality": siruta_code, "category": category}
    )
    # The editorial image follows a verified service slug, never company-supplied media.
    art_category = (
        category if category in detail.listing.category_slugs
        else next(iter(detail.listing.category_slugs), "reparatii")
    )
    return {
        "detail": detail,
        "company": detail.listing,
        "search_scope": {"county": county, "locality": siruta_code, "category": category},
        "art_category": art_category,
        "art_photo": f"services/category-photos/{art_category}.webp",
        "county": county,
        "locality_label": locality_label,
        "back_url": back_url,
        "detail_url": (
            f'{reverse("services:company_detail", args=(business_id,))}?{query}'
        ),
        "save_url": (
            f'{reverse("services:company_shortlist_toggle", args=(business_id,))}?{query}'
        ) if not read_only else "",
        "company_is_saved": any(
            entry["business_id"] == business_id
            for entry in _registry_shortlist_entries(request)
        ),
        "claim_url": '' if read_only else f'{reverse("services:company_claim", args=(business_id,))}?{query}',
        "preview": state.preview,
    }


def company_detail(request, business_id: int):
    """Show one whitelisted company record only through an active catalogue scope."""

    return render(
        request,
        "services/company_detail.html",
        _active_company_context(request, business_id),
    )


def provider_public_detail(request, public_id):
    """Show only one currently visible provider snapshot in the requested context."""

    form = ProviderSearchForm(request.GET, category_choices=_public_category_choices())
    if not form.is_valid():
        raise Http404(_("Căutarea asociată profilului nu este validă"))
    county = form.cleaned_data["county"]
    siruta_code = form.cleaned_data["locality"]
    category = form.cleaned_data["category"]
    provider = published_provider_detail(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    if provider is None:
        raise Http404(_("Profilul nu este disponibil pentru această căutare"))
    submission = visible_provider_submission(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    reviews = ProviderCustomerReview.objects.filter(
        profile=submission.profile,
        status=ProviderCustomerReview.Status.APPROVED,
    ).select_related("provider_reply")[:6]
    review_summary = ProviderCustomerReview.objects.filter(
        profile=submission.profile,
        status=ProviderCustomerReview.Status.APPROVED,
    ).aggregate(count=Count("id"), average=Avg("rating"))
    back_url = f'{reverse("services:home")}?{urlencode(request.GET)}#rezultate'
    report_url = (
        f'{reverse("services:provider_report", args=(public_id,))}?{urlencode(request.GET)}'
    )
    request_quote_url = (
        f'{reverse("services:provider_lead_create", args=(public_id,))}?{urlencode(request.GET)}'
    )
    return render(
        request,
        "services/provider_public_detail.html",
        {
            "provider": provider,
            "county": county,
            "back_url": back_url,
            "report_url": report_url,
            "request_quote_url": request_quote_url,
            "customer_reviews": reviews,
            "review_count": review_summary["count"],
            "review_average": review_summary["average"],
            "provider_is_saved": any(
                entry["public_id"] == str(public_id)
                for entry in _shortlist_entries(request)
            ),
        },
    )


def provider_shortlist(request):
    """Resolve the browser's saved firms through the current public visibility gates."""

    if getattr(settings, "READ_ONLY_PREVIEW", False):
        raise Http404
    providers = []
    retained_entries = []
    for entry in _shortlist_entries(request):
        form = ProviderSearchForm(
            {
                "county": entry["county"],
                "locality": entry["locality"],
                "category": entry["category"],
            },
            category_choices=_public_category_choices(),
        )
        if not form.is_valid():
            continue
        provider = published_provider_detail(
            public_id=entry["public_id"],
            county=form.cleaned_data["county"],
            siruta_code=form.cleaned_data["locality"],
            category=form.cleaned_data["category"],
        )
        if provider is None:
            continue
        query = urlencode(
            {
                "county": form.cleaned_data["county"],
                "locality": form.cleaned_data["locality"],
                "category": form.cleaned_data["category"],
            }
        )
        providers.append(
            {
                "profile": provider,
                "profile_url": (
                    f'{reverse("services:provider_public_detail", args=(provider.public_id,))}?{query}'
                ),
                "toggle_url": (
                    f'{reverse("services:provider_shortlist_toggle", args=(provider.public_id,))}?{query}'
                ),
            }
        )
        retained_entries.append(entry)
    if list(_shortlist_entries(request)) != retained_entries:
        request.session[PROVIDER_SHORTLIST_SESSION_KEY] = retained_entries
    companies = []
    retained_companies = []
    for entry in _registry_shortlist_entries(request):
        try:
            context = _active_company_context(request, entry["business_id"], entry)
        except Http404:
            continue
        companies.append(context)
        retained_companies.append(entry)
    if list(_registry_shortlist_entries(request)) != retained_companies:
        request.session[REGISTRY_SHORTLIST_SESSION_KEY] = retained_companies
    response = render(
        request,
        "services/provider_shortlist.html",
        {"saved_providers": providers, "saved_companies": companies},
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@require_POST
def company_shortlist_toggle(request, business_id: int):
    """Toggle a registry record only after its current catalogue scope validates."""

    if getattr(settings, "READ_ONLY_PREVIEW", False):
        raise Http404
    context = _active_company_context(request, business_id)
    entries = list(_registry_shortlist_entries(request))
    existing = next((entry for entry in entries if entry["business_id"] == business_id), None)
    if existing:
        entries.remove(existing)
    else:
        entries.insert(0, {"business_id": business_id, **context["search_scope"]})
        entries = entries[:PROVIDER_SHORTLIST_LIMIT]
    request.session[REGISTRY_SHORTLIST_SESSION_KEY] = entries
    return_to = request.POST.get("return_to")
    if return_to == "shortlist":
        return redirect("services:provider_shortlist")
    if return_to == "detail":
        return redirect(context["detail_url"])
    return redirect(context["back_url"])


@require_POST
def provider_shortlist_toggle(request, public_id):
    """Add or remove one currently visible provider from this browser's shortlist."""

    if getattr(settings, "READ_ONLY_PREVIEW", False):
        raise Http404
    form = ProviderSearchForm(request.GET, category_choices=_public_category_choices())
    if not form.is_valid():
        raise Http404(_("Căutarea asociată profilului nu este validă"))
    county = form.cleaned_data["county"]
    locality = form.cleaned_data["locality"]
    category = form.cleaned_data["category"]
    if published_provider_detail(
        public_id=public_id,
        county=county,
        siruta_code=locality,
        category=category,
    ) is None:
        raise Http404(_("Profilul nu este disponibil pentru această căutare"))

    entries = list(_shortlist_entries(request))
    existing = next(
        (entry for entry in entries if entry["public_id"] == str(public_id)),
        None,
    )
    if existing:
        entries.remove(existing)
    else:
        entries.insert(
            0,
            {
                "public_id": str(public_id),
                "county": county,
                "locality": locality,
                "category": category,
            },
        )
        entries = entries[:PROVIDER_SHORTLIST_LIMIT]
    request.session[PROVIDER_SHORTLIST_SESSION_KEY] = entries

    query = urlencode({"county": county, "locality": locality, "category": category})
    return_to = request.POST.get("return_to")
    if return_to == "profile":
        return redirect(
            f'{reverse("services:provider_public_detail", args=(public_id,))}?{query}'
        )
    if return_to == "shortlist":
        return redirect("services:provider_shortlist")
    return redirect(f'{reverse("services:home")}?{query}#rezultate')


@require_POST
def provider_engagement(request, public_id):
    """Record a bounded anonymous interaction only for the visible snapshot."""

    search_form = ProviderSearchForm(
        request.GET, category_choices=_public_category_choices()
    )
    if not search_form.is_valid():
        raise Http404
    submission = visible_provider_submission(
        public_id=public_id,
        county=search_form.cleaned_data["county"],
        siruta_code=search_form.cleaned_data["locality"],
        category=search_form.cleaned_data["category"],
    )
    if submission is None:
        raise Http404
    if not request.session.session_key:
        request.session.create()
    try:
        record_provider_engagement(
            submission=submission,
            event_type=request.POST.get("event_type", ""),
            session_key=request.session.session_key,
        )
    except ValueError:
        return JsonResponse({"error": _("Interacțiunea nu este validă.")}, status=400)
    response = HttpResponse(status=204)
    response.headers["Cache-Control"] = "no-store"
    return response


def _issue_or_validate_lead_submission_token(post_data, *, salt):
    """Issue a new form token or keep a valid, bounded token after form errors."""

    submitted = post_data.get("submission_token", "") if post_data is not None else ""
    if submitted and len(submitted) <= 256:
        try:
            nonce = signing.loads(submitted, salt=salt, max_age=24 * 60 * 60)
            if isinstance(nonce, str) and 16 <= len(nonce) <= 64:
                return submitted, nonce
        except signing.BadSignature:
            pass
    return signing.dumps(secrets.token_urlsafe(24), salt=salt), ""


@never_cache
def provider_lead_create(request, public_id):
    """Send a structured customer request to one currently visible provider."""

    search_form = ProviderSearchForm(
        request.GET, category_choices=_public_category_choices()
    )
    if not search_form.is_valid():
        raise Http404(_("Căutarea asociată profilului nu este validă"))
    county = search_form.cleaned_data["county"]
    siruta_code = search_form.cleaned_data["locality"]
    category = search_form.cleaned_data["category"]
    provider = published_provider_detail(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )


    submission = visible_provider_submission(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    if provider is None or submission is None:
        raise Http404(_("Profilul nu este disponibil pentru această solicitare"))
    labels = {slug: label for slug, label, _description in CATEGORIES}
    service_choices = tuple((slug, labels[slug]) for slug in provider.category_slugs)
    initial_category = category if category in provider.category_slugs else provider.category_slugs[0]
    submission_token, submission_nonce = _issue_or_validate_lead_submission_token(
        request.POST if request.method == "POST" else None,
        salt="provider-lead-direct-submit",
    )
    customer_account = active_customer_account(request.user)
    form = ProviderLeadForm(
        request.POST or None,
        service_choices=service_choices,
        initial={"category": initial_category},
        customer_account=customer_account,
    )
    if request.method == "POST" and not submission_nonce:
        form.add_error(None, _("Reîncarcă formularul înainte de a trimite solicitarea."))
    lead_sent = False
    customer_access_path = None
    if request.method == "POST" and form.is_valid():
        if not request.session.session_key:
            request.session.create()
        try:
            lead, customer_token = create_provider_lead(
                submission=submission,
                category=form.cleaned_data["category"],
                county=county,
                siruta_code=siruta_code,
                customer_name=form.cleaned_data["customer_name"],
                customer_email=form.cleaned_data["customer_email"],
                customer_phone=form.cleaned_data["customer_phone"],
                project_address=form.cleaned_data["project_address"],
                description=form.cleaned_data["description"],
                budget=form.cleaned_data["budget"],
                desired_start=form.cleaned_data["desired_start"],
                session_key=request.session.session_key,
                submission_nonce=submission_nonce,
                customer_account=customer_account,
            )
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            deliver_provider_lead_notification(
                lead=lead, dashboard_url=provider_lead_focus_url(request, lead),
            )
            access_path = reverse(
                "services:provider_lead_customer",
                args=(lead.public_id, customer_token),
            )
            customer_notified = bool(customer_account) or deliver_customer_access_notification(
                lead=lead, access_url=request.build_absolute_uri(access_path)
            )
            if not customer_notified:
                customer_access_path = access_path
            lead_sent = True
    profile_url = (
        f'{reverse("services:provider_public_detail", args=(public_id,))}?{urlencode(request.GET)}'
    )
    response = render(
        request,
        "services/provider_lead_create.html",
        {
            "provider": provider,
            "lead_form": form,
            "submission_token": submission_token,
            "lead_sent": lead_sent,
            "customer_notified": customer_notified if lead_sent else False,
            "customer_access_path": customer_access_path,
            "customer_portal_available": bool(customer_account),
            "profile_url": profile_url,
            "county": county,
            "locality": provider.searched_locality_label,
        },
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@never_cache
def provider_lead_batch_create(request):
    """Dispatch one project to every subscribed provider matching its exact scope."""

    submission_token, submission_nonce = _issue_or_validate_lead_submission_token(
        request.POST if request.method == "POST" else None,
        salt="provider-lead-batch-submit",
    )
    search_data = request.POST if request.method == "POST" else (request.GET or None)
    search_form = ProviderSearchForm(
        search_data, category_choices=_public_category_choices()
    )
    customer_account = active_customer_account(request.user)
    lead_form = GeneralProviderLeadForm(
        request.POST or None, customer_account=customer_account
    )
    if request.method == "POST" and not submission_nonce:
        lead_form.add_error(None, _("Reîncarcă formularul înainte de a trimite solicitarea."))
    filters_valid = search_form.is_valid() if search_form.is_bound else False
    if request.method == "POST" and filters_valid:
        if not search_form.cleaned_data["locality"]:
            search_form.add_error(
                "locality", _("Alege localitatea în care va fi realizată lucrarea.")
            )
            filters_valid = False
        if not search_form.cleaned_data["category"]:
            search_form.add_error("category", _("Alege serviciul de care ai nevoie."))
            filters_valid = False

    candidates = ()
    if filters_valid:
        candidates = published_provider_search(
            county=search_form.cleaned_data["county"],
            siruta_code=search_form.cleaned_data["locality"],
            category=search_form.cleaned_data["category"],
        )

    batch_sent = False
    customer_notified = False
    customer_access_path = None
    dispatched_providers = ()
    if request.method == "POST" and filters_valid and lead_form.is_valid():
        if not candidates:
            search_form.add_error(
                None,
                _(
                    "Nu există încă firme cu profil complet care pot primi această "
                    "solicitare. Schimbă localitatea sau serviciul."
                ),
            )
        else:
            if not request.session.session_key:
                request.session.create()
            dispatched_providers = tuple(candidates)
            submissions = tuple(
                visible_provider_submission(
                    public_id=provider.public_id,
                    county=search_form.cleaned_data["county"],
                    siruta_code=search_form.cleaned_data["locality"],
                    category=search_form.cleaned_data["category"],
                )
                for provider in dispatched_providers
            )
            if any(submission is None for submission in submissions):
                search_form.add_error(
                    None,
                    _("Lista firmelor s-a schimbat. Reîncarcă pagina și încearcă din nou."),
                )
            else:
                try:
                    batch, customer_token, leads = create_provider_lead_batch(
                        submissions=submissions,
                        category=search_form.cleaned_data["category"],
                        county=search_form.cleaned_data["county"],
                        siruta_code=search_form.cleaned_data["locality"],
                        customer_name=lead_form.cleaned_data["customer_name"],
                        customer_email=lead_form.cleaned_data["customer_email"],
                        customer_phone=lead_form.cleaned_data["customer_phone"],
                        project_address=lead_form.cleaned_data["project_address"],
                        description=lead_form.cleaned_data["description"],
                        budget=lead_form.cleaned_data["budget"],
                        desired_start=lead_form.cleaned_data["desired_start"],
                        session_key=request.session.session_key,
                        submission_nonce=submission_nonce,
                        customer_account=customer_account,
                    )
                except ValueError as error:
                    lead_form.add_error(None, str(error))
                else:
                    for lead in leads:
                        deliver_provider_lead_notification(
                            lead=lead, dashboard_url=provider_lead_focus_url(request, lead)
                        )
                    access_path = reverse(
                        "services:provider_lead_batch_customer",
                        args=(batch.public_id, customer_token),
                    )
                    customer_notified = bool(customer_account) or deliver_customer_batch_access_notification(
                        batch=batch, access_url=request.build_absolute_uri(access_path)
                    )
                    if not customer_notified:
                        customer_access_path = access_path
                    batch_sent = True

    category_label = ""
    locality_label = ""
    if search_form.is_bound and search_form.is_valid():
        category_label = dict(
            (slug, label) for slug, label, _description in CATEGORIES
        ).get(search_form.cleaned_data["category"], "")
        locality_label = locality_name(
            search_form.cleaned_data["county"], search_form.cleaned_data["locality"]
        )
    response = render(
        request,
        "services/provider_lead_batch_create.html",
        {
            "search_form": search_form,
            "lead_form": lead_form,
            "submission_token": submission_token,
            "batch_sent": batch_sent,
            "customer_notified": customer_notified,
            "customer_access_path": customer_access_path,
            "customer_portal_available": bool(customer_account),
            "recipient_count": len(dispatched_providers),
            "category_label": category_label,
            "locality_label": locality_label,
            "matching_provider_count": (
                len(candidates)
                if filters_valid and search_form.cleaned_data["locality"]
                and search_form.cleaned_data["category"] else None
            ),
        },
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@never_cache
@require_GET
def provider_lead_batch_availability(request):
    """Report only the current public recipient count for one exact request scope."""

    form = ProviderSearchForm(
        request.GET, category_choices=_public_category_choices()
    )
    if not form.is_valid() or not form.cleaned_data["locality"] or not form.cleaned_data["category"]:
        return JsonResponse({"error": "invalid_scope"}, status=400)
    return JsonResponse({
        "count": len(published_provider_search(
            county=form.cleaned_data["county"],
            siruta_code=form.cleaned_data["locality"],
            category=form.cleaned_data["category"],
        )),
    })


@never_cache
def provider_lead_customer(request, public_id, token):
    """Show one customer their private request, messages, and current offer."""

    return _customer_lead_workspace(request, public_id=public_id, token=token)


def _customer_lead_workspace(request, *, public_id, token=None, customer_account=None):
    """Render one request for either a legacy capability or its owning account."""

    try:
        lead = (
            provider_lead_for_customer_account(
                public_id=public_id, customer_account=customer_account
            )
            if customer_account is not None
            else provider_lead_for_customer(public_id=public_id, token=token)
        )
    except ProviderLead.DoesNotExist as error:
        raise Http404(_("Linkul privat nu este valid sau a expirat.")) from error
    message_form = ProviderLeadMessageForm(prefix="customer-message")
    review_form = ProviderCustomerReviewForm(prefix="customer-review")
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "message":
            message_form = ProviderLeadMessageForm(
                request.POST, prefix="customer-message"
            )
            if message_form.is_valid():
                try:
                    add_provider_lead_message(
                        lead=lead,
                        sender_role=ProviderLeadMessage.SenderRole.CUSTOMER,
                        body=message_form.cleaned_data["body"],
                    )
                except ValueError as error:
                    message_form.add_error(None, str(error))
                else:
                    deliver_conversation_notification(
                        lead=lead,
                        recipient=provider_lead_recipient(lead),
                        access_url=provider_lead_focus_url(request, lead),
                    )
                    messages.success(request, _("Mesajul a fost trimis firmei."))
                    return redirect(request.path)
        elif action == "review":
            review_form = ProviderCustomerReviewForm(
                request.POST, prefix="customer-review"
            )
            if review_form.is_valid():
                try:
                    submit_customer_review(
                        lead=lead,
                        rating=review_form.cleaned_data["rating"],
                        body=review_form.cleaned_data["body"],
                    )
                except ValueError as error:
                    review_form.add_error(None, str(error))
                else:
                    messages.success(
                        request,
                        _("Recenzia a fost trimisă și va apărea după verificare."),
                    )
                    return redirect(request.path)
        elif action in {ProviderQuote.Status.ACCEPTED, ProviderQuote.Status.DECLINED}:
            try:
                respond_to_provider_quote(
                    lead=lead,
                    quote_id=int(request.POST.get("quote_id", "")),
                    decision=action,
                )
            except (TypeError, ValueError, ProviderQuote.DoesNotExist):
                messages.error(request, _("Oferta nu mai este disponibilă."))
            else:
                deliver_conversation_notification(
                    lead=lead,
                    recipient=provider_lead_recipient(lead),
                    access_url=provider_lead_focus_url(request, lead),
                )
                messages.success(request, _("Răspunsul tău la ofertă a fost înregistrat."))
                return redirect(request.path)
        elif action in {"visit_accepted", "visit_declined"}:
            try:
                respond_to_provider_visit(
                    lead=lead,
                    proposal_id=int(request.POST.get("proposal_id", "")),
                    decision=(
                        ProviderVisitProposal.Status.ACCEPTED
                        if action == "visit_accepted" else ProviderVisitProposal.Status.DECLINED
                    ),
                )
            except (TypeError, ValueError, ProviderVisitProposal.DoesNotExist):
                messages.error(request, _("Programarea nu mai este disponibilă. Reîncarcă pagina."))
            else:
                deliver_conversation_notification(
                    lead=lead,
                    recipient=provider_lead_recipient(lead),
                    access_url=provider_lead_focus_url(request, lead),
                )
                messages.success(request, _("Răspunsul la programare a fost înregistrat."))
                return redirect(request.path)
        elif action == "visit_cancel":
            try:
                cancel_provider_visit_for_customer(
                    lead=lead, proposal_id=int(request.POST.get("proposal_id", ""))
                )
            except (TypeError, ValueError, ProviderVisitProposal.DoesNotExist):
                messages.error(request, _("Vizita nu mai poate fi anulată. Reîncarcă pagina."))
            else:
                deliver_conversation_notification(
                    lead=lead,
                    recipient=provider_lead_recipient(lead),
                    access_url=provider_lead_focus_url(request, lead),
                )
                messages.success(request, _("Vizita a fost anulată. Poți cere o altă dată în conversație."))
                return redirect(request.path)
        else:
            raise Http404
    latest_quote = lead.quotes.first()
    customer_review = ProviderCustomerReview.objects.filter(lead=lead).first()
    context = {
        "lead": lead,
        "latest_quote": latest_quote,
        "latest_visit": lead.visit_proposals.first(),
        "work_order": getattr(lead, "work_order", None),
        "quote_is_expired": bool(
            latest_quote and latest_quote.valid_until < timezone.localdate()
        ),
        "conversation": lead.messages.all(),
        "message_form": message_form,
        "review_form": review_form,
        "customer_review": customer_review,
        "customer_may_review": not customer_review and customer_may_review(lead),
        "locality": locality_name(lead.county, lead.siruta_code),
        "category_label": dict(
            (slug, label) for slug, label, _description in CATEGORIES
        ).get(lead.category, lead.category),
        "customer_portal": customer_account is not None,
        "now": timezone.now(),
    }
    response = render(request, "services/provider_lead_customer.html", context)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@never_cache
def provider_lead_batch_customer(request, public_id, token):
    """Show one private project workspace with all provider responses side by side."""

    return _customer_batch_workspace(request, public_id=public_id, token=token)


def _customer_batch_workspace(request, *, public_id, token=None, customer_account=None):
    """Render one comparison for either a legacy capability or its owning account."""

    try:
        batch = (
            provider_lead_batch_for_customer_account(
                public_id=public_id, customer_account=customer_account
            )
            if customer_account is not None
            else provider_lead_batch_for_customer(public_id=public_id, token=token)
        )
    except ProviderLeadBatch.DoesNotExist as error:
        raise Http404(_("Linkul privat nu este valid sau a expirat.")) from error

    active_leads = tuple(
        lead for lead in batch.leads.prefetch_related("visit_proposals")
        if lead.retention_applied_at is None
    )
    if not active_leads:
        raise Http404(_("Linkul privat nu este valid sau a expirat."))

    posted_lead = next(
        (
            lead
            for lead in active_leads
            if str(lead.public_id) == request.POST.get("lead_id", "")
        ),
        None,
    )
    invalid_message_form = None
    if request.method == "POST":
        if posted_lead is None:
            raise Http404
        action = request.POST.get("action", "")
        if action == "message":
            invalid_message_form = ProviderLeadMessageForm(
                request.POST, prefix=f"message-{posted_lead.pk}"
            )
            if invalid_message_form.is_valid():
                try:
                    add_provider_lead_message(
                        lead=posted_lead,
                        sender_role=ProviderLeadMessage.SenderRole.CUSTOMER,
                        body=invalid_message_form.cleaned_data["body"],
                    )
                except ValueError as error:
                    invalid_message_form.add_error(None, str(error))
                else:
                    deliver_conversation_notification(
                        lead=posted_lead,
                        recipient=provider_lead_recipient(posted_lead),
                        access_url=provider_lead_focus_url(request, posted_lead),
                    )
                    messages.success(request, _("Mesajul a fost trimis firmei."))
                    return redirect(request.path)
        elif action in {ProviderQuote.Status.ACCEPTED, ProviderQuote.Status.DECLINED}:
            try:
                respond_to_batch_provider_quote(
                    batch=batch,
                    lead=posted_lead,
                    quote_id=int(request.POST.get("quote_id", "")),
                    decision=action,
                )
            except (TypeError, ValueError, ProviderQuote.DoesNotExist):
                messages.error(request, _("Oferta nu mai este disponibilă."))
            else:
                deliver_conversation_notification(
                    lead=posted_lead,
                    recipient=provider_lead_recipient(posted_lead),
                    access_url=provider_lead_focus_url(request, posted_lead),
                )
                messages.success(
                    request, _("Răspunsul tău la ofertă a fost înregistrat.")
                )
                return redirect(request.path)
        elif action in {"visit_accepted", "visit_declined"}:
            try:
                respond_to_provider_visit(
                    lead=posted_lead,
                    proposal_id=int(request.POST.get("proposal_id", "")),
                    decision=(
                        ProviderVisitProposal.Status.ACCEPTED
                        if action == "visit_accepted" else ProviderVisitProposal.Status.DECLINED
                    ),
                )
            except (TypeError, ValueError, ProviderVisitProposal.DoesNotExist):
                messages.error(request, _("Programarea nu mai este disponibilă. Reîncarcă pagina."))
            else:
                deliver_conversation_notification(
                    lead=posted_lead,
                    recipient=provider_lead_recipient(posted_lead),
                    access_url=provider_lead_focus_url(request, posted_lead),
                )
                messages.success(request, _("Răspunsul la programare a fost înregistrat."))
                return redirect(request.path)
        elif action == "visit_cancel":
            try:
                cancel_provider_visit_for_customer(
                    lead=posted_lead, proposal_id=int(request.POST.get("proposal_id", ""))
                )
            except (TypeError, ValueError, ProviderVisitProposal.DoesNotExist):
                messages.error(request, _("Vizita nu mai poate fi anulată. Reîncarcă pagina."))
            else:
                deliver_conversation_notification(
                    lead=posted_lead,
                    recipient=provider_lead_recipient(posted_lead),
                    access_url=provider_lead_focus_url(request, posted_lead),
                )
                messages.success(request, _("Vizita a fost anulată. Poți cere o altă dată în conversație."))
                return redirect(request.path)
        else:
            raise Http404

    lead_cards = []
    for lead in active_leads:
        latest_quote = lead.quotes.first()
        lead_cards.append(
            {
                "lead": lead,
                "latest_quote": latest_quote,
                "latest_visit": lead.visit_proposals.first(),
                "work_order": getattr(lead, "work_order", None),
                "quote_is_expired": bool(
                    latest_quote
                    and latest_quote.valid_until < timezone.localdate()
                ),
                "conversation": lead.messages.all(),
                "message_form": (
                    invalid_message_form
                    if posted_lead == lead and invalid_message_form is not None
                    else ProviderLeadMessageForm(prefix=f"message-{lead.pk}")
                ),
            }
        )
    first_lead = active_leads[0]
    context = {
        "batch": batch,
        "project": first_lead,
        "lead_cards": lead_cards,
        "locality": locality_name(batch.county, batch.siruta_code),
        "category_label": dict(
            (slug, label) for slug, label, _description in CATEGORIES
        ).get(batch.category, batch.category),
        "customer_portal": customer_account is not None,
        "now": timezone.now(),
    }
    response = render(request, "services/provider_lead_batch_customer.html", context)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def provider_report(request, public_id):
    """Accept a privacy-minimized report only for the exact visible snapshot."""

    search_form = ProviderSearchForm(
        request.GET, category_choices=_public_category_choices()
    )
    if not search_form.is_valid():
        raise Http404(_("Căutarea asociată profilului nu este validă"))
    county = search_form.cleaned_data["county"]
    siruta_code = search_form.cleaned_data["locality"]
    category = search_form.cleaned_data["category"]
    provider = published_provider_detail(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    submission = visible_provider_submission(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    if provider is None or submission is None:
        raise Http404(_("Profilul nu este disponibil pentru această sesizare"))

    form = PublicProviderReportForm(request.POST or None)
    report_sent = False
    report_created = False
    if request.method == "POST" and form.is_valid():
        if not request.session.session_key:
            request.session.create()
        try:
            _report, report_created = create_public_provider_report(
                submission=submission,
                reason=form.cleaned_data["reason"],
                details=form.cleaned_data["details"],
                session_key=request.session.session_key,
            )
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            report_sent = True
    elif request.method == "POST":
        first_invalid_field = next(
            (
                name
                for name, field in form.fields.items()
                if name in form.errors and not field.widget.is_hidden
            ),
            None,
        )
        if first_invalid_field:
            form.fields[first_invalid_field].widget.attrs["autofocus"] = True

    query = urlencode(request.GET)
    return render(
        request,
        "services/provider_report.html",
        {
            "provider": provider,
            "report_form": form,
            "report_sent": report_sent,
            "report_created": report_created,
            "profile_url": (
                f'{reverse("services:provider_public_detail", args=(public_id,))}?{query}'
            ),
        },
    )


def provider_portfolio_image(request, opaque_id):
    """Serve a sanitized derivative only to its owner or through an active publication."""

    asset = portfolio_asset_for_request(opaque_id=opaque_id, user=request.user)
    if asset is None:
        raise Http404
    try:
        handle = asset.image.open("rb")
    except OSError as error:
        raise Http404 from error
    response = FileResponse(handle, content_type=asset.mime_type)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300" if request.user.is_authenticated else "public, max-age=3600"
    return response


def company_claim(request, business_id: int):
    """Start a minimum-data provider claim only for a currently visible company."""

    context = _active_company_context(request, business_id)
    form = ProviderClaimForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            claim = create_provider_claim_request(
                business=BusinessIdentity.objects.get(pk=business_id),
                legal_name=context["company"].legal_name,
                contact_name=(
                    f"{form.cleaned_data['first_name']} {form.cleaned_data['last_name']}"
                ),
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password1"],
                role=form.cleaned_data["role"],
                email=form.cleaned_data["email"],
                evidence_type=form.cleaned_data["evidence_type"],
                evidence_document=form.cleaned_data["evidence_document"],
                representation_declaration=form.cleaned_data[
                    "representation_declaration"
                ],
            )
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            context.update(
                {
                    "claim_sent": True,
                    "claim_email": claim.email,
                }
            )
    context["claim_form"] = form
    return render(request, "services/company_claim.html", context)


def company_claim_confirm(request, token: str):
    """Require an explicit CSRF-protected POST before confirming an e-mail token."""

    claim = provider_claim_for_token(token)
    if claim is None:
        return render(
            request,
            "services/company_claim_confirm.html",
            {"invalid_token": True},
            status=410,
        )
    verified = claim.status == claim.Status.REVIEW_PENDING
    if request.method == "POST" and not verified:
        try:
            claim = verify_provider_claim_email(token)
        except ValueError:
            return render(
                request,
                "services/company_claim_confirm.html",
                {"invalid_token": True},
                status=410,
            )
        verified = True
    return render(
        request,
        "services/company_claim_confirm.html",
        {"claim": claim, "verified": verified},
    )


def company_registration(request):
    """Accept a verification-gated intake when a company is absent from the catalogue."""

    form = ProviderRegistrationForm(
        request.POST or None,
        request.FILES or None,
        category_choices=tuple(
            (record.slug, record.label)
            for record in new_provider_service_categories()
        ),
    )
    context = {"registration_form": form}
    if request.method == "POST" and form.is_valid():
        try:
            registration = create_provider_registration_request(
                legal_name=form.cleaned_data["legal_name"],
                cui=form.cleaned_data["cui"],
                registration_number=form.cleaned_data["registration_number"],
                requested_category=form.cleaned_data["requested_category"],
                registered_county=form.cleaned_data["registered_county"],
                registered_office_siruta=form.cleaned_data[
                    "registered_office_siruta"
                ],
                contact_name=(
                    f"{form.cleaned_data['first_name']} {form.cleaned_data['last_name']}"
                ),
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password1"],
                role=form.cleaned_data["role"],
                email=form.cleaned_data["email"],
                evidence_type=form.cleaned_data["evidence_type"],
                evidence_document=form.cleaned_data["evidence_document"],
                representation_declaration=form.cleaned_data[
                    "representation_declaration"
                ],
            )
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            context.update(
                {
                    "registration_sent": True,
                    "registration_email": registration.email,
                }
            )
    return render(request, "services/company_registration.html", context)


def company_registration_confirm(request, token: str):
    """Require a CSRF-protected POST before confirming an unlisted-company intake."""

    registration = provider_registration_for_token(token)
    if registration is None:
        return render(
            request,
            "services/company_registration_confirm.html",
            {"invalid_token": True},
            status=410,
        )
    verified = registration.status == registration.Status.REVIEW_PENDING
    if request.method == "POST" and not verified:
        try:
            registration = verify_provider_registration_email(token)
        except ValueError:
            return render(
                request,
                "services/company_registration_confirm.html",
                {"invalid_token": True},
                status=410,
            )
        verified = True
    return render(
        request,
        "services/company_registration_confirm.html",
        {"registration": registration, "verified": verified},
    )


def customer_register(request):
    """Create and authenticate one customer account without e-mail confirmation."""

    existing = active_customer_account(request.user)
    if existing:
        return redirect("services:customer_dashboard")
    if request.user.is_authenticated:
        return redirect("services:provider_dashboard")
    form = CustomerRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            account = register_customer_account(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
                privacy_notice_version=settings.LEGAL_POLICY_VERSION,
            )
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            login(request, account.user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, _("Contul tău de client este pregătit."))
            return redirect("services:customer_dashboard")
    return render(request, "services/customer_register.html", {"customer_form": form})


def customer_login(request):
    """Authenticate one customer by e-mail using a separate throttle namespace."""

    requested_next = request.POST.get("next") or request.GET.get("next", "")
    safe_next = (
        requested_next
        if requested_next and url_has_allowed_host_and_scheme(
            requested_next, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ) else ""
    )
    if active_customer_account(request.user):
        return redirect(safe_next or "services:customer_dashboard")
    form = CustomerLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if not claim_account_login_attempt(scope="customer", identifier=email):
            form.add_error(None, _("Prea multe încercări. Reîncearcă peste 15 minute."))
        else:
            users = list(get_user_model().objects.filter(email__iexact=email, is_active=True)[:2])
            user = authenticate(
                request, username=users[0].username, password=form.cleaned_data["password"]
            ) if len(users) == 1 else None
            if user and active_customer_account(user):
                clear_account_login_attempts(scope="customer", identifier=email)
                login(request, user)
                return redirect(safe_next or "services:customer_dashboard")
            form.add_error(None, _("E-mailul sau parola nu sunt corecte."))
    return render(request, "services/customer_login.html", {"customer_login_form": form, "next": safe_next})


def _customer_account_or_redirect(request):
    """Resolve customer ownership while preserving the requested internal path."""

    account = active_customer_account(request.user)
    if account:
        return account, None
    login_url = reverse("services:customer_login")
    return None, redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")


@never_cache
def customer_dashboard(request):
    """Page owned projects, prioritizing live offers and customer-visible activity."""

    account, denied = _customer_account_or_redirect(request)
    if denied:
        return denied
    today = timezone.localdate()
    offer_view = request.GET.get("view") == "offers"
    standalone_query = account.leads.filter(
        batch__isnull=True, retention_applied_at__isnull=True,
    ).select_related("submission").annotate(
        has_quote=Exists(ProviderQuote.objects.filter(lead_id=OuterRef("pk"))),
        has_valid_offer=Exists(ProviderQuote.objects.filter(
            lead_id=OuterRef("pk"), status=ProviderQuote.Status.SENT, valid_until__gte=today,
        )),
        last_quote_at=Subquery(ProviderQuote.objects.filter(
            lead_id=OuterRef("pk"),
        ).order_by("-sent_at").values("sent_at")[:1]),
        last_provider_message_at=Subquery(ProviderLeadMessage.objects.filter(
            lead_id=OuterRef("pk"), sender_role=ProviderLeadMessage.SenderRole.PROVIDER,
        ).order_by("-created_at").values("created_at")[:1]),
    ).annotate(
        needs_response=Case(
            When(status=ProviderLead.Status.QUOTE_SENT, has_valid_offer=True, then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ),
        visible_activity_at=Greatest(
            F("created_at"), Coalesce("last_quote_at", "created_at"),
            Coalesce("last_provider_message_at", "created_at"),
        ),
    ).order_by("-needs_response", "-visible_activity_at", "-pk")
    batch_query = account.lead_batches.filter(
        retention_applied_at__isnull=True,
        leads__pk__isnull=False,
        leads__retention_applied_at__isnull=True,
    ).annotate(
        active_count=Count("leads", filter=Q(leads__retention_applied_at__isnull=True), distinct=True),
        offer_count=Count(
            "leads", filter=Q(leads__retention_applied_at__isnull=True, leads__quotes__isnull=False),
            distinct=True,
        ),
        valid_offer_count=Count(
            "leads", filter=Q(
                leads__retention_applied_at__isnull=True,
                leads__status=ProviderLead.Status.QUOTE_SENT,
                leads__quotes__status=ProviderQuote.Status.SENT,
                leads__quotes__valid_until__gte=today,
            ), distinct=True,
        ),
        last_quote_at=Subquery(ProviderQuote.objects.filter(
            lead__batch_id=OuterRef("pk"), lead__retention_applied_at__isnull=True,
        ).order_by("-sent_at").values("sent_at")[:1]),
        last_provider_message_at=Subquery(ProviderLeadMessage.objects.filter(
            lead__batch_id=OuterRef("pk"), lead__retention_applied_at__isnull=True,
            sender_role=ProviderLeadMessage.SenderRole.PROVIDER,
        ).order_by("-created_at").values("created_at")[:1]),
    ).annotate(
        visible_activity_at=Greatest(
            F("created_at"), Coalesce("last_quote_at", "created_at"),
            Coalesce("last_provider_message_at", "created_at"),
        ),
    ).order_by("-valid_offer_count", "-visible_activity_at", "-pk")
    standalone_page = Paginator(
        standalone_query.filter(needs_response=True) if offer_view else standalone_query, 10,
    ).get_page(request.GET.get("requests_page"))
    batch_page = Paginator(
        batch_query.filter(valid_offer_count__gt=0) if offer_view else batch_query, 10,
    ).get_page(request.GET.get("comparisons_page"))
    labels = {slug: label for slug, label, _description in CATEGORIES}
    standalone_cards = tuple({
        "lead": lead,
        "category_label": labels.get(lead.category, lead.category),
        "locality": locality_name(lead.county, lead.siruta_code),
        "latest_quote": lead.has_quote,
        "needs_response": lead.needs_response,
        "visible_activity_at": lead.visible_activity_at,
    } for lead in standalone_page)
    batch_cards = tuple({
        "batch": batch,
        "category_label": labels.get(batch.category, batch.category),
        "locality": locality_name(batch.county, batch.siruta_code),
        "active_count": batch.active_count,
        "offer_count": batch.offer_count,
        "valid_offer_count": batch.valid_offer_count,
        "visible_activity_at": batch.visible_activity_at,
    } for batch in batch_page)
    return render(request, "services/customer_dashboard.html", {
        "customer_account": account,
        "standalone_cards": standalone_cards,
        "batch_cards": batch_cards,
        "request_count": standalone_page.paginator.count + batch_page.paginator.count,
        "standalone_page": standalone_page,
        "batch_page": batch_page,
        "offer_view": offer_view,
    })


@never_cache
def customer_lead_detail(request, public_id):
    """Open one account-owned request without exposing a bearer token."""

    account, denied = _customer_account_or_redirect(request)
    if denied:
        return denied
    return _customer_lead_workspace(request, public_id=public_id, customer_account=account)


@never_cache
def customer_batch_detail(request, public_id):
    """Open one account-owned comparison without exposing a bearer token."""

    account, denied = _customer_account_or_redirect(request)
    if denied:
        return denied
    return _customer_batch_workspace(request, public_id=public_id, customer_account=account)


@require_POST
def customer_logout(request):
    """End only an authenticated customer session through a CSRF-protected action."""

    logout(request)
    return redirect("services:home")


@never_cache
def customer_password_change(request):
    """Change only the current customer's password and keep this session active."""

    account, denied = _customer_account_or_redirect(request)
    if denied:
        return denied
    form = AccountPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(
            request,
            _("Parola a fost schimbată. Celelalte sesiuni ale contului au fost închise."),
        )
        return redirect("services:customer_dashboard")
    return render(
        request,
        "services/customer_password_change.html",
        {"password_change_form": form, "customer_account": account},
    )


def provider_activate(request, token: str):
    """Show an inert invitation on GET and activate the provider only on valid POST."""

    invitation = provider_invitation_for_token(token)
    if invitation is None:
        return render(
            request,
            "services/provider_activate.html",
            {"invalid_invitation": True},
            status=410,
        )
    user = invitation.membership.user
    form = ProviderActivationForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            membership = activate_provider_invitation(
                token=token, new_password=form.cleaned_data["new_password1"]
            )
        except ValueError:
            return render(
                request,
                "services/provider_activate.html",
                {"invalid_invitation": True},
                status=410,
            )
        user.refresh_from_db()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Contul a fost activat. Profilul tău este încă o ciornă."))
        return redirect("services:provider_dashboard")
    return render(
        request,
        "services/provider_activate.html",
        {"activation_form": form, "profile": invitation.membership.profile},
    )


def provider_login(request):
    """Authenticate one active provider by e-mail with bounded failed attempts."""

    requested_next = request.POST.get("next") or request.GET.get("next", "")
    safe_next = (
        requested_next
        if requested_next
        and url_has_allowed_host_and_scheme(
            requested_next,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
        else ""
    )
    if request.user.is_authenticated:
        if active_provider_membership(request.user):
            return redirect(safe_next or "services:provider_dashboard")
        if active_provider_team_member(request.user):
            return redirect(safe_next or "services:technician_work")
    form = ProviderLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if not claim_account_login_attempt(scope="provider", identifier=email):
            form.add_error(None, _("Prea multe încercări. Reîncearcă peste 15 minute."))
        else:
            users = list(
                get_user_model().objects.filter(
                    email__iexact=email, is_active=True
                )[:2]
            )
            user = (
                authenticate(
                    request,
                    username=users[0].username,
                    password=form.cleaned_data["password"],
                )
                if len(users) == 1
                else None
            )
            owner = active_provider_membership(user) if user else None
            technician = active_provider_team_member(user) if user else None
            if user and (owner or technician):
                clear_account_login_attempts(scope="provider", identifier=email)
                login(request, user)
                return redirect(safe_next or ("services:provider_dashboard" if owner else "services:technician_work"))
            form.add_error(None, _("E-mailul sau parola nu sunt corecte."))
    return render(
        request,
        "services/provider_login.html",
        {"provider_login_form": form, "next": safe_next},
    )


class ProviderPasswordResetView(PasswordResetView):
    """Issue provider-only reset e-mails with a generic response and bounded sends."""

    template_name = "services/provider_password_reset.html"
    email_template_name = "services/emails/provider_password_reset.txt"
    subject_template_name = "services/emails/provider_password_reset_subject.txt"
    form_class = ProviderPasswordResetForm
    success_url = reverse_lazy("services:provider_password_reset_done")

    def form_valid(self, form):
        """Silently suppress repeated sends without exposing account existence."""

        email = form.cleaned_data["email"].strip().lower()
        client_address = self.request.META.get("REMOTE_ADDR", "unknown")
        if not claim_password_reset_send_slot(
            email=email, client_address=client_address
        ):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class ProviderPasswordResetDoneView(PasswordResetDoneView):
    """Confirm the request without revealing whether the address matched."""

    template_name = "services/provider_password_reset_done.html"


class ProviderPasswordResetConfirmView(PasswordResetConfirmView):
    """Validate Django's single-use reset credential and collect a new password."""

    template_name = "services/provider_password_reset_confirm.html"
    form_class = ProviderActivationForm
    success_url = reverse_lazy("services:provider_password_reset_complete")

    def get_user(self, uidb64):
        """Invalidate an issued link as soon as provider ownership is revoked."""

        user = super().get_user(uidb64)
        return user if user and (active_provider_membership(user) or active_provider_team_member(user)) else None


class ProviderPasswordResetCompleteView(PasswordResetCompleteView):
    """Return the provider to the dedicated login surface after reset."""

    template_name = "services/provider_password_reset_complete.html"


class CustomerPasswordResetView(PasswordResetView):
    """Issue customer-only reset links with the same privacy and send budget."""

    template_name = "services/customer_password_reset.html"
    email_template_name = "services/emails/customer_password_reset.txt"
    subject_template_name = "services/emails/provider_password_reset_subject.txt"
    form_class = CustomerPasswordResetForm
    success_url = reverse_lazy("services:customer_password_reset_done")

    def form_valid(self, form):
        """Suppress excess sends without revealing if the account exists."""

        if not claim_password_reset_send_slot(
            email=form.cleaned_data["email"],
            client_address=self.request.META.get("REMOTE_ADDR", "unknown"),
            scope="customer",
        ):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class CustomerPasswordResetDoneView(PasswordResetDoneView):
    """Give the same confirmation for known and unknown customer addresses."""

    template_name = "services/customer_password_reset_done.html"


class CustomerPasswordResetConfirmView(PasswordResetConfirmView):
    """Accept a single-use link only while customer access remains active."""

    template_name = "services/customer_password_reset_confirm.html"
    form_class = ProviderActivationForm
    success_url = reverse_lazy("services:customer_password_reset_complete")

    def get_user(self, uidb64):
        """Invalidate an issued link as soon as customer access is lost."""

        user = super().get_user(uidb64)
        return user if user and active_customer_account(user) else None


class CustomerPasswordResetCompleteView(PasswordResetCompleteView):
    """Return the customer to the dedicated login surface."""

    template_name = "services/customer_password_reset_complete.html"


@login_required(login_url="services:provider_login")
def provider_password_change(request):
    """Replace an active provider account password and preserve this session."""

    owner = active_provider_membership(request.user)
    membership = owner or active_provider_team_member(request.user)
    if membership is None:
        raise PermissionDenied
    form = AccountPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(
            request,
            _("Parola a fost schimbată. Celelalte sesiuni ale contului au fost închise."),
        )
        return redirect("services:provider_dashboard" if owner else "services:technician_work")
    return render(
        request,
        "services/provider_password_change.html",
        {
            "password_change_form": form, "profile": membership.profile,
            "return_route": "services:provider_dashboard" if owner else "services:technician_work",
        },
    )


@login_required(login_url="services:provider_login")
@never_cache
def provider_billing_identity(request):
    """Edit provider-declared issuer details without implying fiscal verification."""

    membership = active_provider_membership(request.user)
    if membership is None:
        raise PermissionDenied
    profile = membership.profile
    identity = getattr(profile, "billing_identity", None)
    if request.method == "POST" and request.POST.get("action") != "save_billing_identity":
        raise Http404
    form = ProviderBillingIdentityForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_revision": identity.revision if identity else 0,
            "legal_name": identity.legal_name if identity else "",
            "fiscal_identifier": identity.fiscal_identifier if identity else "",
            "registration_number": identity.registration_number if identity else "",
            "registered_address": identity.registered_address if identity else "",
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            identity, changed = save_provider_billing_identity(
                user=request.user,
                expected_revision=form.cleaned_data["expected_revision"],
                values={field: form.cleaned_data[field] for field in (
                    "legal_name", "fiscal_identifier", "registration_number", "registered_address"
                )},
            )
        except (PermissionError, ValueError) as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Datele declarate ale emitentului au fost salvate. Nu sunt verificate pentru emiterea unei facturi.")
                if changed else _("Datele declarate sunt deja la zi."),
            )
            return redirect(request.path)
    return render(
        request, "services/provider_billing_identity.html",
        {"profile": profile, "identity": identity, "form": form},
    )


@login_required(login_url="services:provider_login")
@never_cache
def provider_team(request):
    """Let the owner invite or revoke technicians without sharing owner access."""

    membership = active_provider_membership(request.user)
    if membership is None:
        raise PermissionDenied
    profile = membership.profile
    action = request.POST.get("action", "") if request.method == "POST" else ""
    form = ProviderTeamInviteForm(request.POST if action == "invite" else None)
    if request.method == "POST":
        if action == "invite":
            if form.is_valid():
                try:
                    invitation, token = issue_provider_team_invitation(
                        user=request.user, email=form.cleaned_data["email"],
                    )
                except (PermissionError, ValueError) as error:
                    form.add_error(None, str(error))
                else:
                    link = request.build_absolute_uri(reverse("services:provider_team_accept", args=(token,)))
                    try:
                        send_mail(
                            subject=_("Invitație în echipa ServiciiAproape"),
                            message=_("Ai fost invitat(ă) ca tehnician în echipa %(company)s. Activează accesul în 48 de ore: %(link)s") % {
                                "company": profile.display_name, "link": link,
                            },
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[invitation.normalized_email],
                            fail_silently=False,
                        )
                    except Exception:
                        revoke_provider_team_invitation(user=request.user, invitation_id=invitation.pk)
                        form.add_error(None, _("Invitația nu a putut fi trimisă. Încearcă din nou."))
                        security_logger.exception("Provider team invitation delivery failed.")
                    else:
                        messages.success(request, _("Invitația a fost trimisă. Accesul începe numai după acceptare."))
                        return redirect("services:provider_team")
        elif action in {"revoke_invitation", "revoke_member"}:
            try:
                record_id = int(request.POST.get("record_id", ""))
                if record_id <= 0:
                    raise ValueError
                if action == "revoke_invitation":
                    revoke_provider_team_invitation(user=request.user, invitation_id=record_id)
                else:
                    revoke_provider_technician(user=request.user, member_id=record_id)
            except (ValueError, ProviderTeamInvitation.DoesNotExist, ProviderTeamMember.DoesNotExist) as error:
                raise Http404(_("Accesul echipei nu este disponibil.")) from error
            messages.success(request, _("Accesul a fost revocat."))
            return redirect("services:provider_team")
        else:
            raise Http404
    now = timezone.now()
    return render(request, "services/provider_team.html", {
        "profile": profile, "form": form,
        "members": ProviderTeamMember.objects.filter(
            profile=profile, state=ProviderTeamMember.State.ACTIVE,
        ).select_related("user").order_by("user__first_name", "user__last_name", "pk")[:20],
        "invitations": ProviderTeamInvitation.objects.filter(
            profile=profile, accepted_at__isnull=True, revoked_at__isnull=True,
            expires_at__gt=now,
        ).order_by("-created_at")[:20],
    })


@never_cache
def provider_team_accept(request, token):
    """Bind a live mailbox invitation to a new or authenticated existing account."""

    try:
        invitation = pending_provider_team_invitation(token)
    except ProviderTeamInvitation.DoesNotExist as error:
        raise Http404(_("Invitația nu mai este disponibilă.")) from error
    users = list(get_user_model().objects.filter(email__iexact=invitation.normalized_email)[:2])
    if len(users) > 1:
        raise Http404(_("Invitația nu poate fi activată pentru acest cont."))
    existing = bool(users)
    form = (
        ProviderTeamExistingAccountForm(request.POST or None)
        if existing else ProviderTeamNewAccountForm(request.POST or None)
    )
    if request.method == "POST" and form.is_valid():
        account = None
        if existing:
            if not claim_account_login_attempt(scope="team_invitation", identifier=invitation.normalized_email):
                form.add_error(None, _("Prea multe încercări. Reîncearcă peste 15 minute."))
            else:
                account = authenticate(
                    request, username=users[0].username,
                    password=form.cleaned_data["password"],
                )
                if account is None:
                    form.add_error(None, _("Parola contului nu este corectă."))
        if not form.errors:
            try:
                member = accept_provider_team_invitation(
                    token=token, existing_user=account if existing else None,
                    new_account=None if existing else {
                        "first_name": form.cleaned_data["first_name"],
                        "last_name": form.cleaned_data["last_name"],
                        "username": form.cleaned_data["username"],
                        "password": form.cleaned_data["password1"],
                    },
                )
            except (ValueError, PermissionError, ValidationError, ProviderTeamInvitation.DoesNotExist) as error:
                form.add_error(None, str(error))
            else:
                if existing:
                    clear_account_login_attempts(scope="team_invitation", identifier=invitation.normalized_email)
                login(request, member.user, backend="django.contrib.auth.backends.ModelBackend")
                messages.success(request, _("Accesul de tehnician este activ. Vezi doar lucrările atribuite ție."))
                return redirect("services:technician_work")
    response = render(request, "services/provider_team_accept.html", {
        "invitation": invitation, "form": form, "existing": existing,
    })
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@login_required(login_url="services:provider_login")
@never_cache
def technician_work(request):
    """Show or update only this technician's current assigned scheduled jobs."""

    member = active_provider_team_member(request.user)
    if member is None:
        raise PermissionDenied
    if request.method == "POST":
        try:
            order_id = int(request.POST.get("order_id", ""))
            revision = int(request.POST.get("expected_revision", ""))
            action = request.POST.get("action", "")
            if order_id <= 0 or revision < 0 or action not in {"start", "complete"}:
                raise ValueError
            if action == "complete" and request.POST.get("confirm_completion") != "on":
                messages.error(request, _("Confirmă explicit că lucrarea este terminată."))
                return redirect("services:technician_work")
            order = update_assigned_work_execution(
                user=request.user, order_id=order_id,
                action=action, expected_revision=revision,
            )
        except (TypeError, ValueError) as error:
            if str(error):
                messages.error(request, str(error))
                return redirect("services:technician_work")
            raise Http404 from error
        except (ProviderWorkOrder.DoesNotExist, ProviderLead.DoesNotExist, ProviderTeamMember.DoesNotExist) as error:
            raise Http404 from error
        if action == "complete":
            if not deliver_conversation_notification(
                lead=order.lead, recipient=order.lead.customer_email,
                access_url=_customer_activity_access_url(request, order.lead),
            ):
                messages.warning(request, _("Lucrarea este finalizată, dar e-mailul către client nu a putut fi livrat."))
            messages.success(request, _("Ai confirmat finalizarea lucrării. Nu a fost emisă nicio factură."))
        else:
            messages.success(request, _("Începerea lucrării a fost înregistrată."))
        return redirect("services:technician_work")
    if request.method != "GET":
        raise Http404
    work = assigned_provider_work_for_technician(request.user)
    page = Paginator(work, 20).get_page(request.GET.get("page", "1"))
    return render(request, "services/technician_work.html", {
        "profile": member.profile, "work_page": page, "now": timezone.now(),
    })


@login_required(login_url="services:provider_login")
def provider_dashboard(request):
    """Edit private provider content and a versioned service-area declaration."""

    membership = active_provider_membership(request.user)
    if membership is None:
        raise PermissionDenied
    profile = membership.profile
    action = request.POST.get("action", "save_profile" if request.method == "POST" else "")
    profile_form = ProviderProfileForm(
        request.POST if action == "save_profile" else None,
        instance=profile,
    )
    if action == "save_profile" and profile_form.is_valid():
        try:
            _profile, changed = save_provider_profile_for_owner(
                user=request.user, values=profile_form.cleaned_data
            )
        except (PermissionError, ValueError) as error:
            profile_form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Ciorna profilului a fost salvată.")
                if changed
                else _("Profilul este deja la zi."),
            )
            return redirect("services:provider_dashboard")

    portfolio_form = ProviderPortfolioUploadForm(
        request.POST if action == "add_portfolio" else None,
        request.FILES if action == "add_portfolio" else None,
    )
    if action == "add_portfolio" and portfolio_form.is_valid():
        try:
            added_items = add_portfolio_images_for_owner(
                user=request.user,
                uploads=portfolio_form.cleaned_data["images"],
                caption=portfolio_form.cleaned_data["caption"],
            )
        except (PermissionError, ValueError) as error:
            portfolio_form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("%(count)s fotografii au fost adăugate în ciorna portofoliului.")
                % {"count": len(added_items)},
            )
            return redirect("services:provider_dashboard")
    if action == "remove_portfolio":
        try:
            remove_portfolio_item_for_owner(
                user=request.user, item_id=int(request.POST.get("item_id", "0"))
            )
        except (PermissionError, ValueError):
            raise PermissionDenied
        messages.success(request, _("Fotografia a fost eliminată din ciornă."))
        return redirect("services:provider_dashboard")

    draft = ProviderServiceAreaDraft.objects.filter(profile=profile).first()
    review_submit_form = ProviderServiceAreaSubmitForm(
        request.POST if action == "submit_offerings_review" else None,
        initial={"expected_revision": draft.revision if draft else 0},
    )
    response_status = 200
    if action == "submit_offerings_review" and review_submit_form.is_valid():
        try:
            _submission, created = submit_provider_service_area_for_review(
                user=request.user,
                expected_revision=review_submit_form.cleaned_data["expected_revision"],
            )
        except ProviderDraftRevisionConflict as error:
            review_submit_form.add_error(None, str(error))
            response_status = 409
        except (PermissionError, ValueError) as error:
            review_submit_form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Revizia a fost trimisă la verificare.")
                if created
                else _("Revizia este deja în verificare."),
            )
            return redirect("services:provider_dashboard")
    current_services = tuple(
        draft.services.values_list("category", flat=True) if draft else ()
    )
    current_coverage = tuple(
        draft.coverage.order_by("county", "siruta_code").values_list(
            "county", "siruta_code"
        )
        if draft
        else ()
    )
    authorization_error = ""
    authorization_is_demo = False
    offering_editable = True
    category_policies = service_category_records()
    accepting_category_slugs = frozenset(
        record.slug for record in category_policies if record.accepts_new_providers
    )
    try:
        authorization = provider_authorization(profile)
        authorized_categories = editable_provider_service_slugs(
            authorized_categories=authorization.categories,
            current_services=current_services,
        )
        authorization_is_demo = authorization.is_demo
    except ValueError as error:
        # Missing-catalogue companies may prepare private declarations, but the
        # immutable review step remains blocked until legal authorization resolves.
        offering_editable = may_prepare_unverified_offering_draft(profile)
        authorized_categories = (
            editable_provider_service_slugs(
                authorized_categories=accepting_category_slugs,
                current_services=current_services,
            )
            if offering_editable
            else frozenset()
        )
        authorization_error = str(error)

    selected_county = request.GET.get("coverage_county", "")
    requested_category = (
        ProviderRegistrationRequest.objects.filter(
            status=ProviderRegistrationRequest.Status.CONVERTED,
            linked_business_id=profile.business_id,
            converted_claim_id=profile.approved_claim_id,
        )
        .values_list("requested_category", flat=True)
        .first()
        or ""
    )
    configured_services = (
        request.GET.getlist("services")
        if request.GET.get("configure_coverage")
        else current_services
        or (
            (requested_category,)
            if requested_category in authorized_categories
            else ()
        )
    )
    offering_form = ProviderServicesCoverageForm(
        request.POST if action == "save_offerings" else None,
        authorized_categories=authorized_categories,
        selected_county=selected_county,
        existing_coverage=current_coverage,
        initial={
            "services": configured_services,
            "coverage_county": selected_county,
            "expected_revision": draft.revision if draft else 0,
        },
    )
    if action == "save_offerings" and offering_editable and offering_form.is_valid():
        coverage = set(current_coverage)
        for encoded in offering_form.cleaned_data["remove_coverage"]:
            county, siruta_code = encoded.split("|", 1)
            coverage.discard((county, siruta_code))
        county = offering_form.cleaned_data["coverage_county"]
        siruta_code = offering_form.cleaned_data["coverage_locality"]
        if county and siruta_code:
            coverage.add((county, siruta_code))
        try:
            _draft, changed = replace_provider_services_and_coverage_for_owner(
                user=request.user,
                expected_revision=offering_form.cleaned_data["expected_revision"],
                categories=offering_form.cleaned_data["services"],
                coverage_pairs=coverage,
            )
        except ProviderDraftRevisionConflict as error:
            offering_form.add_error(None, str(error))
            response_status = 409
        except (PermissionError, ValueError) as error:
            offering_form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Declarația privată a fost salvată.")
                if changed
                else _("Declarația este deja la zi."),
            )
            return redirect("services:provider_dashboard")

    selected_services = set(
        offering_form["services"].value() or ()
    )
    coverage_display = tuple(
        {
            "encoded": f"{county}|{siruta_code}",
            "county": county,
            "siruta_code": siruta_code,
            "label": locality_name(county, siruta_code),
        }
        for county, siruta_code in current_coverage
    )
    current_submission = (
        ProviderServiceAreaSubmission.objects.filter(
            draft=draft, superseded_at__isnull=True
        ).first()
        if draft
        else None
    )
    publication_submit_form = ProviderPublicationSubmitForm(
        request.POST if action == "submit_publication" else None
    )
    if action == "submit_publication" and publication_submit_form.is_valid():
        try:
            _publication, created = submit_provider_publication_for_review(user=request.user)
        except (PermissionError, ValueError) as error:
            publication_submit_form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Profilul complet a fost trimis spre publicare.")
                if created else _("Această versiune este deja în verificare."),
            )
            return redirect("services:provider_dashboard")
    if action == "unpublish_profile":
        try:
            changed = unpublish_provider_profile(user=request.user)
        except (PermissionError, ValueError) as error:
            publication_submit_form.add_error(None, str(error))
        else:
            messages.success(
                request,
                _("Publicarea a fost oprită.")
                if changed
                else _("Profilul era deja retras."),
            )
            return redirect("services:provider_dashboard")
    publication_submission = (
        ProviderPublicationSubmission.objects.filter(
            profile=profile, superseded_at__isnull=True
        ).first()
    )
    publication_scope, _created = ProviderPublicationScope.objects.get_or_create(
        profile=profile
    )
    subscription_state = provider_subscription_state(profile)
    managed_site_inquiries = tuple(
        ManagedSiteInquiry.objects.filter(profile=profile).order_by("-created_at")[:5]
    )
    effective_publication_visibility = provider_publication_effective_visibility(
        publication_scope
    )
    portfolio_items = tuple(
        ProviderPortfolioItem.objects.select_related("asset").filter(profile=profile)
    )
    readiness = provider_publication_readiness(
        profile=profile,
        service_submission=current_submission,
        portfolio=portfolio_items,
    )
    profile_ready = readiness.profile_content and readiness.public_contact
    profile_detail = (
        _("Numele, descrierea și cel puțin un contact sunt pregătite.")
        if profile_ready
        else _("Completează descrierea și cel puțin o metodă publică de contact.")
        if not readiness.profile_content and not readiness.public_contact
        else _("Completează numele public și o descriere de minimum 60 de caractere.")
        if not readiness.profile_content
        else _("Adaugă cel puțin o metodă publică de contact.")
    )
    service_state = (
        "complete"
        if readiness.service_area_approved
        else "waiting"
        if draft and draft.review_state == ProviderServiceAreaDraft.ReviewState.PENDING
        else "attention"
        if draft
        and draft.review_state == ProviderServiceAreaDraft.ReviewState.CHANGES_REQUIRED
        else "action"
    )
    publication_state = (
        "preview"
        if effective_publication_visibility
        == ProviderPublicationScope.Visibility.INTERNAL_PREVIEW
        else "public"
        if effective_publication_visibility == ProviderPublicationScope.Visibility.PUBLIC
        else "subscription_inactive"
        if publication_submission
        and publication_submission.decision
        == ProviderPublicationSubmission.Decision.APPROVED
        and not subscription_state.is_active
        else "invalid"
        if effective_publication_visibility == "invalid"
        else "waiting"
        if publication_submission
        and publication_submission.decision
        == ProviderPublicationSubmission.Decision.PENDING
        else "attention"
        if publication_submission
        and publication_submission.decision
        == ProviderPublicationSubmission.Decision.CHANGES_REQUIRED
        else "withdrawn"
        if publication_submission
        and publication_submission.decision
        == ProviderPublicationSubmission.Decision.APPROVED
        else "action"
        if readiness.complete and subscription_state.is_active
        else "blocked"
    )
    publication_checklist = (
        {
            "label": _("Date publice"),
            "detail": (
                profile_detail
            ),
            "status": "complete" if profile_ready else "action",
            "status_label": _("Pregătit") if profile_ready else _("De completat"),
            "anchor": "date-profil",
        },
        {
            "label": _("Servicii și acoperire"),
            "detail": (
                _("Revizia curentă este aprobată pentru folosire în profil.")
                if service_state == "complete"
                else _("Revizia este în verificare administrativă.")
                if service_state == "waiting"
                else _("Aplică observațiile primite și trimite o revizie nouă.")
                if service_state == "attention"
                else _(
                    "Poți salva ciorna; trimiterea se deschide după verificarea "
                    "autorizărilor firmei."
                )
                if authorization_error
                else _("Salvează serviciile și localitățile, apoi trimite revizia.")
            ),
            "status": service_state,
            "status_label": {
                "complete": _("Aprobat"),
                "waiting": _("În verificare"),
                "attention": _("Necesită modificări"),
                "action": _("De completat"),
            }[service_state],
            "anchor": "servicii",
        },
        {
            "label": _("Portofoliu"),
            "detail": (
                _("Există cel puțin o fotografie validă în ciornă.")
                if readiness.portfolio
                else _("Adaugă cel puțin o fotografie asupra căreia ai drepturi.")
            ),
            "status": "complete" if readiness.portfolio else "action",
            "status_label": _("Pregătit") if readiness.portfolio else _("De completat"),
            "anchor": "portofoliu",
        },
        {
            "label": _("Abonament"),
            "detail": (
                _("Abonamentul de test este activ până la %(date)s.")
                % {"date": formats.date_format(subscription_state.period_ends_at, "DATE_FORMAT")}
                if subscription_state.is_active
                else _("Abonamentul a expirat; datele profesionale nu mai sunt vizibile.")
                if subscription_state.code == "expired"
                else _("Activează abonamentul prin simularea fără plată înainte de publicare.")
                if settings.SIMULATED_CHECKOUT_ENABLED
                else _("Administratorul trebuie să activeze abonamentul de test înainte de publicare.")
            ),
            "status": "complete" if subscription_state.is_active else "action",
            "status_label": _("Activ") if subscription_state.is_active else _("De activat"),
            "anchor": "abonament",
        },
        {
            "label": _("Publicare controlată"),
            "detail": (
                _("Versiunea aprobată este vizibilă numai în preview-ul intern.")
                if publication_state == "preview"
                else _("Versiunea aprobată este vizibilă public.")
                if publication_state == "public"
                else _("Vizibilitatea este suspendată deoarece sursa sau snapshotul nu mai trece verificările curente.")
                if publication_state == "invalid"
                else _("Versiunea aprobată este ascunsă până la reactivarea abonamentului.")
                if publication_state == "subscription_inactive"
                else _("Profilul complet este în verificare.")
                if publication_state == "waiting"
                else _("Aplică feedbackul publicării înainte de o nouă trimitere.")
                if publication_state == "attention"
                else _("Profilul este retras. Modifică ciorna pentru a crea o versiune nouă.")
                if publication_state == "withdrawn"
                else _("Toate condițiile sunt îndeplinite; poți trimite profilul.")
                if publication_state == "action"
                else _("Această etapă se deschide după pregătirea celorlalte elemente.")
            ),
            "status": publication_state,
            "status_label": {
                "preview": _("Preview intern"),
                "public": _("Public"),
                "invalid": _("Vizibilitate suspendată"),
                "subscription_inactive": _("Abonament inactiv"),
                "waiting": _("În verificare"),
                "attention": _("Necesită modificări"),
                "withdrawn": _("Retras"),
                "action": _("Pregătit de trimis"),
                "blocked": _("Blocat"),
            }[publication_state],
            "anchor": "publicare",
        },
    )
    return render(
        request,
        "services/provider_dashboard.html",
        {
            "profile": profile,
            "profile_form": profile_form,
            "offering_form": offering_form,
            "authorization_error": authorization_error,
            "authorization_is_demo": authorization_is_demo,
            "offering_editable": offering_editable,
            "service_options": tuple(
                {
                    "slug": slug,
                    "label": label,
                    "description": description,
                    "authorized": slug in authorized_categories,
                    "selected": slug in selected_services,
                }
                for record in category_policies
                if record.is_publicly_discoverable or record.slug in current_services
                for slug, label, description in (
                    (record.slug, record.label, record.description),
                )
            ),
            "coverage_display": coverage_display,
            "offering_revision": draft.revision if draft else 0,
            "offering_review_state": (
                draft.review_state
                if draft
                else ProviderServiceAreaDraft.ReviewState.DRAFT
            ),
            "offering_review_label": (
                draft.get_review_state_display() if draft else _("Ciornă")
            ),
            "review_submit_form": review_submit_form,
            "current_submission": current_submission,
            "portfolio_form": portfolio_form,
            "portfolio_items": portfolio_items,
            "publication_submit_form": publication_submit_form,
            "publication_submission": publication_submission,
            "publication_scope": publication_scope,
            "subscription_state": subscription_state,
            "managed_site_inquiries": managed_site_inquiries,
            "simulated_checkout_enabled": settings.SIMULATED_CHECKOUT_ENABLED,
            "publication_can_submit": subscription_state.is_active
            and (
                publication_submission is None
                or publication_submission.decision
                == ProviderPublicationSubmission.Decision.CHANGES_REQUIRED
            ),
            "publication_waits_for_subscription": not subscription_state.is_active
            and (
                publication_submission is None
                or publication_submission.decision
                == ProviderPublicationSubmission.Decision.CHANGES_REQUIRED
            ),
            "effective_publication_visibility": effective_publication_visibility,
            "publication_checklist": publication_checklist,
            "publication_checklist_complete": sum(
                step["status"] in {"complete", "preview", "public"}
                for step in publication_checklist
            ),
        },
        status=response_status,
    )


@require_POST
@login_required(login_url="services:provider_login")
def provider_review_reply(request, review_id):
    """Submit one provider response and return to the review workspace."""

    form = ProviderCustomerReviewReplyForm(request.POST, prefix=f"reply-{review_id}")
    if form.is_valid():
        try:
            submit_provider_review_reply(
                user=request.user,
                review_id=review_id,
                body=form.cleaned_data["body"],
            )
        except (PermissionError, ValueError) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, _("Răspunsul a fost trimis spre verificare."))
    else:
        messages.error(request, _("Răspunsul trebuie să aibă între 20 și 1200 de caractere."))
    return redirect(f'{reverse("services:provider_leads")}?view=reviews')


def _customer_activity_access_url(request, lead):
    """Link account-owned activity to its guarded workspace, never to a bearer token."""

    if lead.customer_account_id:
        route = "services:customer_batch_detail" if lead.batch_id else "services:customer_lead_detail"
        public_id = lead.batch.public_id if lead.batch_id else lead.public_id
        return request.build_absolute_uri(reverse(route, args=(public_id,)))
    return _("Folosește linkul privat primit la trimiterea solicitării.")


def _known_assignee_overlap(profile):
    """Match only complete overlapping slots for the same active technician."""

    return ProviderWorkOrder.objects.filter(
        lead__submission__profile=profile,
        lead__retention_applied_at__isnull=True,
        status=ProviderWorkOrder.Status.SCHEDULED,
        assigned_technician__state=ProviderTeamMember.State.ACTIVE,
        assigned_technician__user__is_active=True,
        assigned_technician_id=OuterRef("work_order__assigned_technician_id"),
        scheduled_end__isnull=False,
        scheduled_start__lt=OuterRef("work_order__scheduled_end"),
        scheduled_end__gt=OuterRef("work_order__scheduled_start"),
    ).exclude(lead_id=OuterRef("pk"))


@login_required(login_url="services:provider_login")
@never_cache
def provider_leads(request):
    """Show and update the authenticated provider's private customer-request funnel."""

    try:
        profile, lead_query = provider_leads_for_owner(request.user)
    except PermissionError as error:
        raise PermissionDenied(str(error)) from error
    team_members = list(
        ProviderTeamMember.objects.filter(
            profile=profile, state=ProviderTeamMember.State.ACTIVE,
            user__is_active=True,
        ).select_related("user").order_by("user__first_name", "user__last_name", "pk")[:20]
    )
    requested_filter = (
        request.POST.get("lead_filter", "all")
        if request.method == "POST"
        else request.GET.get("status", "all")
    )
    lead_filter = (
        requested_filter if requested_filter in PROVIDER_LEAD_STATUS_FILTERS else "all"
    )
    requested_page = (
        request.POST.get("lead_page", "1")
        if request.method == "POST"
        else request.GET.get("page", "1")
    )
    page_number = (
        max(1, int(requested_page))
        if requested_page.isdigit() and len(requested_page) <= 7
        else 1
    )
    focus = request.GET.get("focus", "") if request.method == "GET" else ""
    if focus:
        try:
            focused_lead = lead_query.prefetch_related(None).get(public_id=UUID(focus))
        except (ValueError, ProviderLead.DoesNotExist) as error:
            raise Http404(_("Solicitarea nu este disponibilă")) from error
        newer_count = lead_query.filter(
            Q(created_at__gt=focused_lead.created_at)
            | Q(created_at=focused_lead.created_at, pk__gt=focused_lead.pk)
        ).count()
        page_number = newer_count // PROVIDER_LEAD_PAGE_SIZE + 1
        canonical_query = {"view": "requests"}
        if page_number > 1:
            canonical_query["page"] = page_number
        canonical_url = f'{reverse("services:provider_leads")}?{urlencode(canonical_query)}'
        return redirect(f"{canonical_url}#lead-{focused_lead.public_id}")
    return_parameters = {}
    if lead_filter != "all":
        return_parameters["status"] = lead_filter
    if page_number > 1:
        return_parameters["page"] = page_number
    return_url = reverse("services:provider_leads")
    if return_parameters:
        return_url = f"{return_url}?{urlencode(return_parameters)}"
    selected_lead = None
    active_form = None
    selected_action = ""
    command_form = ProviderOwnerCommandForm()
    command_result = None
    draft_quote = None
    if request.method == "GET" and request.GET.get("offer_for"):
        if request.GET.get("view", "requests") != "requests":
            raise Http404(_("Solicitarea nu este disponibilă"))
        try:
            selected_lead = lead_query.prefetch_related(None).get(
                public_id=UUID(request.GET["offer_for"]),
                crm_customer__isnull=False,
                status__in=(
                    ProviderLead.Status.NEW,
                    ProviderLead.Status.CONTACTED,
                    ProviderLead.Status.VISIT_SCHEDULED,
                    ProviderLead.Status.QUOTE_SENT,
                ),
            )
        except (ValueError, ProviderLead.DoesNotExist) as error:
            raise Http404(_("Solicitarea nu este disponibilă")) from error
        # This GET only prepares the existing form. Sending remains an explicit,
        # validated POST and continues to use the request's immutable recipient.
        selected_action = "request_quote"
        lead_filter = "all"
        newer_count = lead_query.filter(
            Q(created_at__gt=selected_lead.created_at)
            | Q(created_at=selected_lead.created_at, pk__gt=selected_lead.pk)
        ).count()
        page_number = newer_count // PROVIDER_LEAD_PAGE_SIZE + 1
    if request.method == "POST":
        if request.POST.get("action") == "prepare_quote":
            selected_action = "prepare_quote"
            command_form = ProviderOwnerCommandForm(request.POST)
            if command_form.is_valid():
                command = command_form.cleaned_data["command"]
                if owner_command_kind(command) == "outstanding":
                    summary = provider_outstanding_receivable_summary(user=request.user)
                    command_result = {
                        "count": summary.count,
                        "overdue_count": summary.overdue_count,
                        "balance_ron": summary.balance_ron,
                    }
                    selected_action = "outstanding_query"
                else:
                    try:
                        draft_quote = parse_quote_command(command)
                    except ValueError as error:
                        command_form.add_error("command", str(error))
                    else:
                        # Names are hints, not identities: stop on no match or ambiguity.
                        candidates = list(
                            lead_query.prefetch_related(None).select_related(None)
                            .only("id", "customer_name", "created_at")
                            .filter(customer_name__icontains=draft_quote.customer_name)
                            .exclude(status__in=(ProviderLead.Status.COMPLETED, ProviderLead.Status.DECLINED, ProviderLead.Status.WON))[:51]
                        )
                        name = draft_quote.customer_name.casefold()
                        matches = [
                            lead for lead in candidates
                            if name == lead.customer_name.casefold()
                            or name in (part.strip(".,").casefold() for part in lead.customer_name.split())
                        ]
                        if len(candidates) > 50 or len(matches) != 1:
                            command_form.add_error(
                                "command",
                                _("Nu am găsit un singur client activ cu acest nume. Deschide solicitarea și completează oferta direct."),
                            )
                        else:
                            selected_lead = matches[0]
                            selected_action = "draft_quote"
                            lead_filter = "all"
                            newer_count = lead_query.filter(
                                Q(created_at__gt=selected_lead.created_at)
                                | Q(created_at=selected_lead.created_at, pk__gt=selected_lead.pk)
                            ).count()
                            page_number = newer_count // PROVIDER_LEAD_PAGE_SIZE + 1
            # Preparing a draft has no write path and never sends a notification.
        elif request.POST.get("action") == "customer_save":
            active_form = ProviderCRMCustomerForm(request.POST, prefix="customer")
            if active_form.is_valid():
                values = active_form.cleaned_data.copy()
                values.pop("lawful_use_confirmed")
                try:
                    _customer, created = save_provider_customer(user=request.user, **values)
                except (ValueError, ProviderCRMCustomer.DoesNotExist) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(
                        request,
                        _("Clientul a fost adăugat în registrul privat.") if created
                        else _("Fișa clientului a fost actualizată."),
                    )
            else:
                messages.error(request, _("Verifică datele clientului și confirmarea privind folosirea lor."))
            return redirect(f'{reverse("services:provider_leads")}?view=customers')
        elif request.POST.get("action") == "customer_archive":
            active_form = ProviderCRMCustomerArchiveForm(request.POST, prefix="archive-customer")
            if active_form.is_valid():
                try:
                    archive_provider_customer(
                        user=request.user,
                        customer_id=active_form.cleaned_data["customer_id"],
                        expected_revision=active_form.cleaned_data["expected_revision"],
                    )
                except (ValueError, ProviderCRMCustomer.DoesNotExist) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, _("Clientul a fost arhivat. Datele nu au fost șterse automat."))
            else:
                messages.error(request, _("Confirmă arhivarea clientului."))
            return redirect(f'{reverse("services:provider_leads")}?view=customers')
        else:
            try:
                selected_lead = lead_query.get(pk=request.POST.get("lead_id"))
            except (ValueError, TypeError, ProviderLead.DoesNotExist):
                raise Http404(_("Solicitarea nu este disponibilă"))
            selected_action = request.POST.get("action", "")
        if selected_action == "customer_link":
            active_form = ProviderCRMCustomerLinkForm(request.POST, prefix="customer-link")
            if not active_form.is_valid() or active_form.cleaned_data["lead_id"] != selected_lead.pk:
                raise Http404(_("Solicitarea nu este disponibilă"))
            try:
                _lead, changed = link_provider_customer_to_lead(
                    user=request.user,
                    lead_id=selected_lead.pk,
                    customer_id=active_form.cleaned_data["customer_id"],
                    expected_revision=active_form.cleaned_data["expected_revision"],
                )
            except ProviderCRMCustomer.DoesNotExist as error:
                raise Http404(_("Clientul nu este disponibil")) from error
            except ValueError as error:
                messages.error(request, str(error))
            else:
                if changed:
                    messages.success(
                        request,
                        _("Clientul a fost asociat solicitării.")
                        if active_form.cleaned_data["customer_id"]
                        else _("Asocierea cu clientul a fost eliminată."),
                    )
            return redirect(
                f'{reverse("services:provider_leads")}?view=requests&focus={selected_lead.public_id}'
            )
        if selected_action == "customer_create_from_lead":
            active_form = ProviderCRMCustomerFromLeadForm(request.POST, prefix="customer")
            if not active_form.is_valid() or active_form.cleaned_data["lead_id"] != selected_lead.pk:
                messages.error(
                    request,
                    _("Verifică datele clientului și confirmarea privind folosirea lor."),
                )
                return redirect(
                    f'{reverse("services:provider_leads")}?view=customers&new_for_lead={selected_lead.public_id}'
                )
            values = active_form.cleaned_data
            try:
                create_and_link_provider_customer_from_lead(
                    user=request.user,
                    lead_id=selected_lead.pk,
                    expected_link_revision=values["expected_link_revision"],
                    name=values["name"],
                    email=values["email"],
                    phone=values["phone"],
                    address=values["address"],
                    notes=values["notes"],
                )
            except (ValueError, ProviderCRMCustomer.DoesNotExist) as error:
                messages.error(request, str(error))
                return redirect(
                    f'{reverse("services:provider_leads")}?view=customers&new_for_lead={selected_lead.public_id}'
                )
            messages.success(
                request,
                _("Clientul a fost creat și asociat solicitării."),
            )
            return redirect(
                f'{reverse("services:provider_leads")}?view=requests&focus={selected_lead.public_id}'
            )
        if selected_action == "update":
            active_form = ProviderLeadUpdateForm(
                request.POST,
                status_choices=allowed_provider_lead_statuses(selected_lead),
                prefix=f"lead-{selected_lead.pk}",
            )
            if active_form.is_valid():
                try:
                    update_provider_lead_for_owner(
                        user=request.user,
                        lead_id=selected_lead.pk,
                        expected_revision=active_form.cleaned_data["expected_revision"],
                        new_status=active_form.cleaned_data["status"],
                        owner_notes=active_form.cleaned_data["owner_notes"],
                    )
                except ValueError as error:
                    active_form.add_error(None, str(error))
                else:
                    messages.success(request, _("Solicitarea a fost actualizată."))
                    return redirect(return_url)
        elif selected_action == "quote":
            active_form = ProviderQuoteForm(request.POST, prefix=f"quote-{selected_lead.pk}")
            if active_form.is_valid():
                try:
                    send_provider_quote(
                        user=request.user,
                        lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except ValueError as error:
                    active_form.add_error(None, str(error))
                else:
                    deliver_conversation_notification(
                        lead=selected_lead,
                        recipient=selected_lead.customer_email,
                        access_url=_customer_activity_access_url(request, selected_lead),
                    )
                    messages.success(request, _("Oferta a fost trimisă clientului."))
                    return redirect(return_url)
        elif selected_action == "message":
            active_form = ProviderLeadMessageForm(
                request.POST, prefix=f"message-{selected_lead.pk}"
            )
            if active_form.is_valid():
                try:
                    add_provider_lead_message(
                        lead=selected_lead,
                        sender_role=ProviderLeadMessage.SenderRole.PROVIDER,
                        body=active_form.cleaned_data["body"],
                        actor=request.user,
                    )
                except (PermissionError, ValueError) as error:
                    active_form.add_error(None, str(error))
                else:
                    deliver_conversation_notification(
                        lead=selected_lead,
                        recipient=selected_lead.customer_email,
                        access_url=_customer_activity_access_url(request, selected_lead),
                    )
                    messages.success(request, _("Mesajul a fost trimis clientului."))
                    return redirect(return_url)
        elif selected_action == "visit":
            active_form = ProviderVisitProposalForm(
                request.POST, prefix=f"visit-{selected_lead.pk}"
            )
            if active_form.is_valid():
                try:
                    propose_provider_visit(
                        user=request.user, lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except ValueError as error:
                    active_form.add_error(None, str(error))
                else:
                    email_sent = deliver_conversation_notification(
                        lead=selected_lead,
                        recipient=selected_lead.customer_email,
                        access_url=_customer_activity_access_url(request, selected_lead),
                    )
                    messages.success(request, _("Propunerea de vizită este vizibilă clientului."))
                    if not email_sent:
                        messages.warning(request, _("E-mailul de notificare nu a putut fi livrat."))
                    return redirect(return_url)
        elif selected_action == "visit_cancel":
            try:
                cancel_provider_visit_for_owner(
                    user=request.user, lead_id=selected_lead.pk,
                    proposal_id=int(request.POST.get("proposal_id", "")),
                )
            except (TypeError, ValueError, ProviderVisitProposal.DoesNotExist):
                messages.error(request, _("Vizita nu mai poate fi anulată. Reîncarcă pagina."))
            else:
                email_sent = deliver_conversation_notification(
                    lead=selected_lead,
                    recipient=selected_lead.customer_email,
                    access_url=_customer_activity_access_url(request, selected_lead),
                )
                messages.success(request, _("Vizita a fost anulată. Poți propune o altă dată."))
                if not email_sent:
                    messages.warning(request, _("E-mailul de notificare nu a putut fi livrat."))
                return redirect(return_url)
        elif selected_action == "work_schedule":
            active_form = ProviderWorkOrderScheduleForm(
                request.POST, prefix=f"work-{selected_lead.pk}"
            )
            if active_form.is_valid():
                try:
                    order = schedule_provider_work_order(
                        user=request.user, lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist, ProviderInvoiceDraft.DoesNotExist) as error:
                    active_form.add_error(None, str(error))
                else:
                    if order.revision != active_form.cleaned_data["expected_revision"]:
                        deliver_conversation_notification(
                            lead=selected_lead,
                            recipient=selected_lead.customer_email,
                            access_url=_customer_activity_access_url(request, selected_lead),
                        )
                    messages.success(request, _("Programarea lucrării a fost salvată."))
                    return redirect(f"{return_url}#lead-{selected_lead.public_id}")
        elif selected_action == "work_complete":
            active_form = ProviderWorkOrderCompleteForm(
                request.POST, prefix=f"complete-{selected_lead.pk}"
            )
            if active_form.is_valid():
                try:
                    complete_provider_work_order(
                        user=request.user, lead_id=selected_lead.pk,
                        expected_revision=active_form.cleaned_data["expected_revision"],
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist) as error:
                    active_form.add_error(None, str(error))
                else:
                    deliver_conversation_notification(
                        lead=selected_lead,
                        recipient=selected_lead.customer_email,
                        access_url=_customer_activity_access_url(request, selected_lead),
                    )
                    messages.success(request, _("Lucrarea a fost marcată ca finalizată. Nu a fost emisă nicio factură."))
                    return redirect(f"{return_url}#lead-{selected_lead.public_id}")
        elif selected_action == "work_cancel":
            active_form = ProviderWorkOrderCancelForm(
                request.POST, prefix=f"cancel-{selected_lead.pk}"
            )
            if active_form.is_valid():
                try:
                    cancel_provider_work_schedule(
                        user=request.user, lead_id=selected_lead.pk,
                        expected_revision=active_form.cleaned_data["expected_revision"],
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist, ProviderInvoiceDraft.DoesNotExist) as error:
                    active_form.add_error(None, str(error))
                else:
                    email_sent = deliver_conversation_notification(
                        lead=selected_lead,
                        recipient=selected_lead.customer_email,
                        access_url=_customer_activity_access_url(request, selected_lead),
                    )
                    messages.success(request, _("Programarea a fost anulată. Lucrarea rămâne de programat."))
                    if not email_sent:
                        messages.warning(request, _("E-mailul de notificare nu a putut fi livrat."))
                    return redirect(f"{return_url}#lead-{selected_lead.public_id}")
        elif selected_action == "work_assign":
            active_form = ProviderWorkAssignmentForm(
                request.POST, prefix=f"assign-{selected_lead.pk}", members=team_members,
            )
            if active_form.is_valid():
                try:
                    order = assign_provider_technician(
                        user=request.user, lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist, ProviderTeamMember.DoesNotExist) as error:
                    active_form.add_error(None, str(error))
                else:
                    if order.assignment_revision != active_form.cleaned_data["expected_revision"] and order.assigned_technician_id:
                        try:
                            send_mail(
                                subject=_("Lucrare atribuită în ServiciiAproape"),
                                message=_("Ai o lucrare programată atribuită. Detaliile sunt disponibile doar în contul tău: %(link)s") % {
                                    "link": request.build_absolute_uri(reverse("services:technician_work")),
                                },
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                recipient_list=[order.assigned_technician.user.email],
                                fail_silently=False,
                            )
                        except Exception:
                            messages.warning(request, _("Atribuirea a fost salvată, dar e-mailul nu a putut fi livrat."))
                            security_logger.exception("Technician assignment notification failed.")
                    messages.success(request, _("Atribuirea lucrării a fost salvată."))
                    return redirect(f"{return_url}#lead-{selected_lead.public_id}")
        elif selected_action == "invoice_draft":
            active_form = ProviderInvoiceDraftForm(
                request.POST, prefix=f"invoice-{selected_lead.pk}"
            )
            if active_form.is_valid():
                try:
                    save_provider_invoice_draft(
                        user=request.user, lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist, ProviderReceivable.DoesNotExist) as error:
                    active_form.add_error(None, str(error))
                else:
                    messages.success(request, _("Ciorna internă a fost salvată. Nu este o factură emisă și nu a fost trimisă clientului."))
                    return redirect(f"{return_url}#lead-{selected_lead.public_id}")
        elif selected_action == "receivable_open":
            active_form = ProviderReceivableForm(request.POST, prefix=f"receivable-{selected_lead.pk}")
            if active_form.is_valid():
                try:
                    open_provider_receivable(
                        user=request.user, lead_id=selected_lead.pk, **active_form.cleaned_data,
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist, ProviderInvoiceDraft.DoesNotExist) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, _("Evidența internă a fost deschisă. Nu este factură și nu confirmă o plată bancară."))
            else:
                messages.error(request, _("Verifică scadența și referința evidenței interne."))
            return redirect(f'{reverse("services:provider_leads")}?view=billing')
        elif selected_action == "manual_payment":
            active_form = ProviderManualPaymentForm(request.POST, prefix=f"payment-{selected_lead.pk}")
            if active_form.is_valid():
                try:
                    record_provider_manual_payment(
                        user=request.user, lead_id=selected_lead.pk, **active_form.cleaned_data,
                    )
                except (ValueError, ProviderWorkOrder.DoesNotExist, ProviderReceivable.DoesNotExist) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, _("Încasarea declarată manual a fost înregistrată. Nu este confirmare bancară."))
            else:
                messages.error(request, _("Verifică suma și data încasării declarate."))
            return redirect(f'{reverse("services:provider_leads")}?view=billing')
        elif selected_action == "manual_payment_void":
            active_form = ProviderManualPaymentVoidForm(request.POST, prefix=f"void-{selected_lead.pk}")
            if active_form.is_valid():
                try:
                    void_provider_manual_payment(
                        user=request.user, lead_id=selected_lead.pk, **active_form.cleaned_data,
                    )
                except (ValueError, ProviderManualPayment.DoesNotExist) as error:
                    messages.error(request, str(error) or _("Înregistrarea nu mai poate fi anulată."))
                else:
                    messages.success(request, _("Înregistrarea încasării a fost anulată și păstrată în istoric."))
            else:
                messages.error(request, _("Completează motivul anulării înregistrării."))
            return redirect(f'{reverse("services:provider_leads")}?view=billing')
        elif selected_action == "receivable_follow_up":
            active_form = ProviderReceivableFollowUpForm(
                request.POST, prefix=f"follow-up-{selected_lead.pk}",
            )
            if active_form.is_valid():
                try:
                    schedule_provider_receivable_follow_up(
                        user=request.user, lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except (ValueError, ProviderReceivable.DoesNotExist) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, _("Reminderul intern a fost programat. Clientul nu a fost contactat."))
            else:
                messages.error(request, _("Verifică data reminderului intern."))
            return redirect(f'{reverse("services:provider_leads")}?view=billing')
        elif selected_action == "receivable_follow_up_complete":
            active_form = ProviderReceivableFollowUpCompleteForm(
                request.POST, prefix=f"follow-up-complete-{selected_lead.pk}",
            )
            if active_form.is_valid():
                try:
                    complete_provider_receivable_follow_up(
                        user=request.user, lead_id=selected_lead.pk,
                        **active_form.cleaned_data,
                    )
                except (ValueError, ProviderReceivable.DoesNotExist) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, _("Urmărirea internă a fost marcată ca realizată. Nu s-a trimis niciun mesaj clientului."))
            else:
                messages.error(request, _("Reminderul intern s-a modificat. Reîncarcă pagina."))
            return redirect(f'{reverse("services:provider_leads")}?view=billing')
        else:
            if selected_action not in {"prepare_quote", "draft_quote", "outstanding_query"}:
                raise Http404
    metrics = provider_lead_metrics(lead_query)
    metrics["conversion"] = (
        round(metrics["won"] * 100 / metrics["total"]) if metrics["total"] else 0
    )
    lead_filters = (
        {"value": "all", "label": _("Toate"), "count": metrics["total"]},
        {"value": "new", "label": _("Noi"), "count": metrics["new"]},
        {
            "value": "active",
            "label": _("În desfășurare"),
            "count": metrics["active"],
        },
        {
            "value": "accepted",
            "label": _("Acceptate"),
            "count": metrics["accepted"],
        },
        {
            "value": "declined",
            "label": _("Refuzate"),
            "count": metrics["declined"],
        },
    )
    selected_statuses = PROVIDER_LEAD_STATUS_FILTERS[lead_filter]
    filtered_leads = (
        lead_query.filter(status__in=selected_statuses)
        if selected_statuses
        else lead_query
    )
    lead_page = Paginator(
        filtered_leads.annotate(known_assignee_overlap=Exists(_known_assignee_overlap(profile))),
        PROVIDER_LEAD_PAGE_SIZE,
    ).get_page(page_number)
    cards = []
    category_labels = {slug: label for slug, label, _description in CATEGORIES}
    for lead in lead_page.object_list:
        work_order = getattr(lead, "work_order", None)
        invoice_draft = getattr(work_order, "invoice_draft", None) if work_order else None
        selected_invoice_form = selected_action == "invoice_draft" and selected_lead and selected_lead.pk == lead.pk
        workspace_open = bool(
            selected_lead
            and selected_lead.pk == lead.pk
            and selected_action in {
                "quote", "message", "visit", "draft_quote", "request_quote",
            }
        )
        cards.append(
            {
                "lead": lead,
                "form": (
                    active_form
                    if selected_action == "update" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderLeadUpdateForm(
                        status_choices=allowed_provider_lead_statuses(lead),
                        prefix=f"lead-{lead.pk}",
                        initial={
                            "expected_revision": lead.revision,
                            "status": lead.status,
                            "owner_notes": lead.owner_notes,
                        },
                    )
                ),
                "quote_form": (
                    active_form
                    if selected_action == "quote" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderQuoteForm(
                        prefix=f"quote-{lead.pk}",
                        initial={
                            "amount_ron": draft_quote.amount_ron,
                            "summary": draft_quote.summary,
                            "item_1_description": draft_quote.summary,
                            "item_1_quantity": 1,
                            "item_1_unit": "lucrare",
                            "item_1_unit_price_ron": draft_quote.amount_ron,
                        } if selected_action == "draft_quote" and selected_lead and selected_lead.pk == lead.pk else {
                            "summary": lead.description,
                            "item_1_description": lead.description,
                            "item_1_quantity": 1,
                            "item_1_unit": "lucrare",
                        } if selected_action == "request_quote" and selected_lead and selected_lead.pk == lead.pk else None,
                    )
                ),
                "draft_prepared": selected_action == "draft_quote" and selected_lead and selected_lead.pk == lead.pk,
                "request_quote_prepared": selected_action == "request_quote" and selected_lead and selected_lead.pk == lead.pk,
                "can_prepare_quote": bool(
                    lead.crm_customer_id
                    and lead.status in {
                        ProviderLead.Status.NEW,
                        ProviderLead.Status.CONTACTED,
                        ProviderLead.Status.VISIT_SCHEDULED,
                        ProviderLead.Status.QUOTE_SENT,
                    }
                ),
                "message_form": (
                    active_form
                    if selected_action == "message" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderLeadMessageForm(prefix=f"message-{lead.pk}")
                ),
                "latest_quote": lead.quotes.first(),
                "latest_visit": lead.visit_proposals.first(),
                "work_order": work_order,
                "known_assignee_overlap": lead.known_assignee_overlap,
                "invoice_draft": invoice_draft,
                "invoice_draft_open": bool(selected_invoice_form),
                "invoice_draft_form": (
                    active_form
                    if selected_invoice_form
                    else ProviderInvoiceDraftForm(
                        prefix=f"invoice-{lead.pk}",
                        initial={
                            "expected_revision": invoice_draft.revision if invoice_draft else 0,
                            "amount_ron": invoice_draft.amount_ron if invoice_draft else work_order.accepted_quote.amount_ron,
                            "description": invoice_draft.description if invoice_draft else work_order.accepted_quote.summary,
                        },
                    ) if work_order and work_order.status == ProviderWorkOrder.Status.COMPLETED else None
                ),
                "work_schedule_form": (
                    active_form
                    if selected_action == "work_schedule" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderWorkOrderScheduleForm(
                        prefix=f"work-{lead.pk}",
                        initial={
                            "expected_revision": lead.work_order.revision,
                            "starts_at": lead.work_order.scheduled_start,
                            "ends_at": lead.work_order.scheduled_end,
                        },
                    ) if hasattr(lead, "work_order") else None
                ),
                "work_complete_form": (
                    active_form
                    if selected_action == "work_complete" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderWorkOrderCompleteForm(
                        prefix=f"complete-{lead.pk}",
                        initial={"expected_revision": lead.work_order.revision},
                    ) if hasattr(lead, "work_order") else None
                ),
                "work_cancel_form": (
                    active_form
                    if selected_action == "work_cancel" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderWorkOrderCancelForm(
                        prefix=f"cancel-{lead.pk}",
                        initial={"expected_revision": lead.work_order.revision},
                    ) if hasattr(lead, "work_order") else None
                ),
                "work_assignment_form": (
                    active_form
                    if selected_action == "work_assign" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderWorkAssignmentForm(
                        prefix=f"assign-{lead.pk}", members=team_members,
                        initial={
                            "expected_revision": lead.work_order.assignment_revision,
                            "member_id": lead.work_order.assigned_technician_id or "",
                        },
                    ) if hasattr(lead, "work_order") else None
                ),
                "visit_form": (
                    active_form
                    if selected_action == "visit" and selected_lead and selected_lead.pk == lead.pk
                    else ProviderVisitProposalForm(prefix=f"visit-{lead.pk}")
                ),
                "conversation": lead.messages.all(),
                "locality": locality_name(lead.county, lead.siruta_code),
                "category_label": category_labels.get(lead.category, lead.category),
                "workspace_open": workspace_open,
            }
        )
    requested_period = request.GET.get("period", "30")
    period = int(requested_period) if requested_period.isdigit() else 30
    period = period if period in ANALYTICS_PERIODS else 30
    requested_section = request.GET.get("view", "")
    dashboard_section = (
        requested_section
        if requested_section in {"requests", "customers", "work", "billing", "performance", "reviews"}
        else "performance" if "period" in request.GET else "requests"
    )
    customer_query = ProviderCRMCustomer.objects.filter(profile=profile)
    customer_counts = customer_query.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(state=ProviderCRMCustomer.State.ACTIVE)),
        archived=Count("id", filter=Q(state=ProviderCRMCustomer.State.ARCHIVED)),
    )
    customer_page = None
    customer_search = request.GET.get("q", "").strip()[:80]
    requested_customer_filter = request.GET.get("customers", "active")
    customer_filter = (
        requested_customer_filter
        if requested_customer_filter in {"active", "archived", "all"}
        else "active"
    )
    editing_customer = None
    linking_lead = None
    creating_from_lead = None
    customer_form = ProviderCRMCustomerForm(
        prefix="customer", initial={"expected_revision": 0},
    )
    if dashboard_section == "customers":
        link_lead_id = request.GET.get("link_lead", "")
        create_lead_id = request.GET.get("new_for_lead", "")
        if link_lead_id and create_lead_id:
            raise Http404(_("Solicitarea nu este disponibilă"))
        if link_lead_id:
            try:
                linking_lead = lead_query.prefetch_related(None).get(public_id=UUID(link_lead_id))
            except (ValueError, ProviderLead.DoesNotExist) as error:
                raise Http404(_("Solicitarea nu este disponibilă")) from error
            customer_filter = "active"
        if create_lead_id:
            try:
                creating_from_lead = lead_query.prefetch_related(None).get(
                    public_id=UUID(create_lead_id), crm_customer__isnull=True,
                )
            except (ValueError, ProviderLead.DoesNotExist) as error:
                raise Http404(_("Solicitarea nu este disponibilă")) from error
            customer_filter = "active"
            customer_form = ProviderCRMCustomerFromLeadForm(
                prefix="customer",
                initial={
                    "expected_revision": 0,
                    "lead_id": creating_from_lead.pk,
                    "expected_link_revision": creating_from_lead.crm_customer_revision,
                    "name": creating_from_lead.customer_name,
                    "email": creating_from_lead.customer_email,
                    "phone": creating_from_lead.customer_phone,
                    "address": creating_from_lead.project_address,
                },
            )
        if customer_filter != "all":
            customer_query = customer_query.filter(state=customer_filter)
        if customer_search:
            customer_query = customer_query.filter(
                Q(name__icontains=customer_search)
                | Q(email__icontains=customer_search)
                | Q(phone__icontains=customer_search)
            )
        customer_page = Paginator(
            customer_query.order_by("state", "name", "pk"), 12,
        ).get_page(request.GET.get("customer_page", "1"))
        edit_id = request.GET.get("edit", "")
        if edit_id:
            try:
                editing_customer = ProviderCRMCustomer.objects.get(
                    pk=int(edit_id), profile=profile,
                    state=ProviderCRMCustomer.State.ACTIVE,
                )
            except (TypeError, ValueError, ProviderCRMCustomer.DoesNotExist):
                raise Http404(_("Clientul nu este disponibil"))
            customer_form = ProviderCRMCustomerForm(
                prefix="customer",
                initial={
                    "expected_revision": editing_customer.revision,
                    "customer_id": editing_customer.pk,
                    "name": editing_customer.name,
                    "email": editing_customer.email,
                    "phone": editing_customer.phone,
                    "address": editing_customer.address,
                    "notes": editing_customer.notes,
                },
            )
    work_counts = None
    work_page = None
    calendar_days = None
    calendar_page = None
    work_display = "calendar" if request.GET.get("display") == "calendar" else "list"
    requested_work_filter = request.GET.get("work", "all")
    work_filter = (
        requested_work_filter
        if requested_work_filter in {"all", "awaiting_schedule", "scheduled", "completed"}
        else "all"
    )
    if dashboard_section == "work":
        work_orders = lead_query.prefetch_related(None).filter(
            work_order__isnull=False,
        )
        work_counts = work_orders.aggregate(
            total=Count("id"),
            awaiting_schedule=Count("id", filter=Q(work_order__status=ProviderWorkOrder.Status.AWAITING_SCHEDULE)),
            scheduled=Count("id", filter=Q(work_order__status=ProviderWorkOrder.Status.SCHEDULED)),
            completed=Count("id", filter=Q(work_order__status=ProviderWorkOrder.Status.COMPLETED)),
        )
        if work_display == "calendar":
            today = timezone.localdate()
            try:
                requested_week = date.fromisoformat(request.GET.get("week", ""))
                if not 2000 <= requested_week.year <= 2099:
                    requested_week = today
            except ValueError:
                requested_week = today
            week_start = requested_week - timedelta(days=requested_week.weekday())
            week_end = week_start + timedelta(days=7)
            local_zone = timezone.get_current_timezone()
            starts_at = timezone.make_aware(datetime.combine(week_start, time.min), local_zone)
            ends_at = timezone.make_aware(datetime.combine(week_end, time.min), local_zone)
            scheduled = work_orders.filter(
                work_order__status=ProviderWorkOrder.Status.SCHEDULED,
                work_order__scheduled_start__gte=starts_at,
                work_order__scheduled_start__lt=ends_at,
            ).order_by("work_order__scheduled_start", "pk")
            day_counts = dict(
                scheduled.order_by()
                .annotate(day=TruncDate("work_order__scheduled_start", tzinfo=local_zone))
                .values("day")
                .annotate(total=Count("id"))
                .values_list("day", "total")
            )
            scheduled = scheduled.annotate(
                has_interval_overlap=Exists(
                    ProviderWorkOrder.objects.filter(
                        lead__submission__profile=profile,
                        lead__retention_applied_at__isnull=True,
                        status=ProviderWorkOrder.Status.SCHEDULED,
                        scheduled_end__isnull=False,
                        scheduled_start__lt=OuterRef("work_order__scheduled_end"),
                        scheduled_end__gt=OuterRef("work_order__scheduled_start"),
                    ).exclude(lead_id=OuterRef("pk"))
                ),
                known_assignee_overlap=Exists(_known_assignee_overlap(profile)),
            ).select_related("work_order__accepted_quote")
            calendar_page = Paginator(scheduled, 60).get_page(request.GET.get("calendar_page", "1"))
            calendar_days = [
                {
                    "date": week_start + timedelta(days=index),
                    "items": [],
                    "count": day_counts.get(week_start + timedelta(days=index), 0),
                }
                for index in range(7)
            ]
            for lead in calendar_page:
                day_index = (timezone.localtime(lead.work_order.scheduled_start, local_zone).date() - week_start).days
                calendar_days[day_index]["items"].append(lead)
            calendar_week = {
                "start": week_start,
                "end": week_end - timedelta(days=1),
                "previous": week_start - timedelta(days=7),
                "next": week_start + timedelta(days=7),
            }
        else:
            if work_filter != "all":
                work_orders = work_orders.filter(work_order__status=work_filter)
            work_orders = work_orders.annotate(
                work_priority=Case(
                    When(work_order__status=ProviderWorkOrder.Status.AWAITING_SCHEDULE, then=Value(0)),
                    When(work_order__status=ProviderWorkOrder.Status.SCHEDULED, then=Value(1)),
                    default=Value(2),
                ),
                scheduled_sort=Case(
                    When(work_order__status=ProviderWorkOrder.Status.SCHEDULED, then=F("work_order__scheduled_start")),
                    output_field=DateTimeField(),
                ),
                completed_sort=Case(
                    When(work_order__status=ProviderWorkOrder.Status.COMPLETED, then=F("work_order__completed_at")),
                    output_field=DateTimeField(),
                ),
            ).order_by("work_priority", "scheduled_sort", "-completed_sort", "-pk")
            work_page = Paginator(work_orders, 12).get_page(request.GET.get("work_page", "1"))
    billing_counts = None
    billing_page = None
    billing_rows = ()
    requested_billing_filter = request.GET.get("billing", "all")
    billing_filter = (
        requested_billing_filter
        if requested_billing_filter in {"all", "pending", "ready", "outstanding", "followup", "settled"}
        else "all"
    )
    if dashboard_section == "billing":
        active_payment_total = (
            ProviderManualPayment.objects.filter(
                receivable_id=OuterRef("work_order__receivable__pk"),
                state=ProviderManualPayment.State.ACTIVE,
            )
            .values("receivable_id")
            .annotate(total=Sum("amount_ron"))
            .values("total")
        )
        money_field = DecimalField(max_digits=12, decimal_places=2)
        billing_orders = lead_query.filter(
            work_order__status=ProviderWorkOrder.Status.COMPLETED,
        ).annotate(
            received_total=Coalesce(
                Subquery(active_payment_total, output_field=money_field),
                Value(Decimal("0.00"), output_field=money_field),
            ),
        ).order_by("-work_order__completed_at", "-pk")
        billing_counts = billing_orders.aggregate(
            total=Count("id", distinct=True),
            pending=Count("id", distinct=True, filter=Q(work_order__invoice_draft__isnull=True)),
            ready=Count("id", distinct=True, filter=Q(
                work_order__invoice_draft__isnull=False,
                work_order__receivable__isnull=True,
            )),
            outstanding=Count("id", distinct=True, filter=Q(
                work_order__receivable__isnull=False,
                work_order__receivable__amount_ron__gt=F("received_total"),
            )),
            followup=Count("id", distinct=True, filter=Q(
                work_order__receivable__follow_up_on__lte=timezone.localdate(),
                work_order__receivable__amount_ron__gt=F("received_total"),
            )),
            settled=Count("id", distinct=True, filter=Q(
                work_order__receivable__isnull=False,
                work_order__receivable__amount_ron__lte=F("received_total"),
            )),
        )
        if billing_filter == "pending":
            billing_orders = billing_orders.filter(work_order__invoice_draft__isnull=True)
        elif billing_filter == "ready":
            billing_orders = billing_orders.filter(
                work_order__invoice_draft__isnull=False,
                work_order__receivable__isnull=True,
            )
        elif billing_filter == "outstanding":
            billing_orders = billing_orders.filter(
                work_order__receivable__isnull=False,
                work_order__receivable__amount_ron__gt=F("received_total"),
            )
        elif billing_filter == "followup":
            billing_orders = billing_orders.filter(
                work_order__receivable__follow_up_on__lte=timezone.localdate(),
                work_order__receivable__amount_ron__gt=F("received_total"),
            )
        elif billing_filter == "settled":
            billing_orders = billing_orders.filter(
                work_order__receivable__isnull=False,
                work_order__receivable__amount_ron__lte=F("received_total"),
            )
        billing_page = Paginator(billing_orders, PROVIDER_LEAD_PAGE_SIZE).get_page(
            request.GET.get("billing_page", "1")
        )
        today = timezone.localdate()
        billing_rows = []
        for lead in billing_page:
            receivable = getattr(lead.work_order, "receivable", None)
            received, balance = (
                provider_receivable_totals(receivable)
                if receivable else (Decimal("0.00"), Decimal("0.00"))
            )
            billing_rows.append({
                "lead": lead,
                "receivable": receivable,
                "received": received,
                "balance": balance,
                "is_settled": receivable is not None and balance <= 0,
                "is_overdue": receivable is not None and balance > 0 and receivable.due_date < today,
                "follow_up_due": (
                    receivable is not None and balance > 0
                    and receivable.follow_up_on is not None
                    and receivable.follow_up_on <= today
                ),
                "receivable_form": ProviderReceivableForm(
                    prefix=f"receivable-{lead.pk}", initial={"due_date": today + timedelta(days=14)},
                ),
                "payment_form": ProviderManualPaymentForm(
                    prefix=f"payment-{lead.pk}", initial={"amount_ron": balance, "received_on": today},
                ) if receivable is not None and balance > 0 else None,
                "follow_up_form": ProviderReceivableFollowUpForm(
                    prefix=f"follow-up-{lead.pk}",
                    initial={
                        "expected_revision": receivable.follow_up_revision,
                        "follow_up_on": receivable.follow_up_on or today + timedelta(days=7),
                    },
                ) if receivable is not None and balance > 0 else None,
                "follow_up_complete_form": ProviderReceivableFollowUpCompleteForm(
                    prefix=f"follow-up-complete-{lead.pk}",
                    initial={"expected_revision": receivable.follow_up_revision},
                ) if receivable is not None and receivable.follow_up_on is not None else None,
            })
    engagement_metrics = provider_engagement_metrics(profile=profile, days=period)
    customer_reviews = list(
        ProviderCustomerReview.objects.filter(
            profile=profile,
            status=ProviderCustomerReview.Status.APPROVED,
        ).select_related("provider_reply")
    )
    review_cards = [
        {
            "review": review,
            "reply": getattr(review, "provider_reply", None),
            "form": ProviderCustomerReviewReplyForm(prefix=f"reply-{review.pk}"),
        }
        for review in customer_reviews
    ]
    review_summary = ProviderCustomerReview.objects.filter(
        profile=profile,
        status=ProviderCustomerReview.Status.APPROVED,
    ).aggregate(count=Count("id"), average=Avg("rating"))
    return render(
        request,
        "services/provider_leads.html",
        {
            "profile": profile,
            "lead_cards": cards,
            "command_form": command_form,
            "command_result": command_result,
            "now": timezone.now(),
            "lead_metrics": metrics,
            "lead_filters": lead_filters,
            "lead_filter": lead_filter,
            "lead_page": lead_page,
            "engagement_metrics": engagement_metrics,
            "analytics_periods": ANALYTICS_PERIODS,
            "analytics_period": period,
            "dashboard_section": dashboard_section,
            "customer_counts": customer_counts,
            "customer_filter": customer_filter,
            "customer_search": customer_search,
            "customer_page": customer_page,
            "customer_form": customer_form,
            "editing_customer": editing_customer,
            "linking_lead": linking_lead,
            "creating_from_lead": creating_from_lead,
            "work_counts": work_counts,
            "work_filter": work_filter,
            "work_page": work_page,
            "work_display": work_display,
            "calendar_days": calendar_days,
            "calendar_page": calendar_page,
            "calendar_week": calendar_week if calendar_days is not None else None,
            "billing_counts": billing_counts,
            "billing_filter": billing_filter,
            "billing_page": billing_page,
            "billing_rows": billing_rows,
            "review_cards": review_cards,
            "review_count": review_summary["count"],
            "review_average": review_summary["average"],
        },
    )


@login_required(login_url="services:provider_login")
def provider_logout(request):
    """End a provider session only through an explicit POST."""

    if request.method != "POST":
        raise Http404
    logout(request)
    return redirect("services:provider_login")
