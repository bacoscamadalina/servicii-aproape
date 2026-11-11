"""Read-only operational visibility for imported legal-registry data."""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .catalog import CATEGORIES
from .forms import (
    DataSubjectRequestIntakeForm,
    DataSubjectRequestProcessForm,
    ManagedSiteInquiryProcessForm,
    ProviderClaimReviewForm,
    ProviderCustomerReviewModerationForm,
    ProviderCustomerReviewReplyModerationForm,
    ProviderRegistrationReviewForm,
    ProviderPublicationReviewForm,
    ProviderSubscriptionAdminForm,
    ServiceCategoryPolicyUpdateForm,
    ProviderServiceAreaReviewForm,
    PublicProviderReportTriageForm,
    ThrottledAdminAuthenticationForm,
)
from .locations import county_choices, locality_name

from .models import (
    DataSubjectRequest,
    DataSubjectRequestEvent,
    BusinessCaen,
    BusinessCategory,
    BusinessIdentity,
    BusinessStatus,
    CatalogueActivationEvent,
    CatalogueScope,
    CustomerAccount,
    ImportQuarantine,
    ImportRun,
    ManagedSiteInquiry,
    ManagedSiteInquiryEvent,
    PublicationApproval,
    ProviderClaimRequest,
    ProviderCustomerReview,
    ProviderCustomerReviewEvent,
    ProviderCustomerReviewReply,
    ProviderCustomerReviewReplyEvent,
    ProviderAccountInvitation,
    ProviderMembership,
    ProviderLead,
    ProviderLeadBatch,
    ProviderLeadEvent,
    ProviderLeadMessage,
    ProviderQuote,
    ProviderProfile,
    ProviderRegistrationRequest,
    ProviderRepresentationEvidence,
    ProviderPortfolioAsset,
    ProviderPortfolioItem,
    ProviderPublicationCoverage,
    ProviderPublicationEvent,
    ProviderPublicationPortfolioItem,
    ProviderPublicationScope,
    ProviderPublicationService,
    ProviderPublicationSubmission,
    ProviderSubscription,
    ProviderSubscriptionEvent,
    PublicProviderReport,
    PublicProviderReportCase,
    PublicProviderReportTriageEvent,
    ProviderServiceAreaDraft,
    ProviderServiceAreaSubmission,
    ProviderDraftService,
    ProviderDraftCoverage,
    ProviderDevelopmentDemoGrant,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
    VerifiedServiceCoverage,
    VerifiedServiceEvidence,
    ServiceCategoryPolicy,
    ServiceCategoryPolicyEvent,
)
from .data_subject_requests import (
    EXTENSION_ACKNOWLEDGEMENT,
    PROCESS_ACKNOWLEDGEMENT,
    advance_data_subject_request,
    extend_data_subject_request_deadline,
    initial_data_request_due_at,
)
from .data_subject_exports import (
    EXPORT_ACKNOWLEDGEMENT,
    EXPORT_FILENAME,
    generate_data_subject_export,
)
from .managed_site_inquiries import (
    PROCESS_ACKNOWLEDGEMENT as MANAGED_SITE_PROCESS_ACKNOWLEDGEMENT,
    transition_managed_site_inquiry,
)
from .provider_access import (
    REVIEW_ACKNOWLEDGEMENT,
    approve_provider_claim,
    deliver_provider_invitation_email,
    reject_provider_claim,
    rotate_provider_invitation,
)
from .provider_registrations import (
    REVIEW_ACKNOWLEDGEMENT as REGISTRATION_REVIEW_ACKNOWLEDGEMENT,
    convert_provider_registration_to_claim,
    reject_provider_registration,
)
from .provider_offerings import (
    REVIEW_ACKNOWLEDGEMENT as SERVICE_AREA_REVIEW_ACKNOWLEDGEMENT,
    review_provider_service_area_submission,
)
from .provider_publication import (
    REVIEW_ACKNOWLEDGEMENT as PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
    review_provider_publication,
    publication_submission_contract_is_valid,
)
from .provider_subscriptions import (
    SUBSCRIPTION_ACKNOWLEDGEMENT,
    activate_or_extend_provider_subscription,
    deactivate_provider_subscription,
    provider_subscription_state,
)
from .report_triage import (
    TRIAGE_ACKNOWLEDGEMENT,
    close_public_provider_report_case,
    start_public_provider_report_review,
)
from .report_insights import WINDOW_DAYS, normalized_insight_window_days, public_report_insights
from .lead_insights import (
    WINDOW_DAYS as LEAD_WINDOW_DAYS,
    normalized_insight_window_days as normalized_lead_insight_window_days,
    provider_lead_insights,
)
from .delivery_audit import audit_request_delivery
from .provider_leads import (
    deliver_provider_lead_notification,
    provider_lead_focus_url,
    provider_lead_recipient,
    rotate_and_deliver_customer_access_notification,
)
from .pilot_readiness import pilot_readiness
from .provider_reviews import (
    MODERATION_ACKNOWLEDGEMENT,
    REPLY_MODERATION_ACKNOWLEDGEMENT,
    moderate_customer_review,
    moderate_provider_review_reply,
)
from .representation_evidence import representation_evidence_is_valid
from .service_category_policies import (
    CATEGORY_CATALOGUE,
    CATEGORY_POLICY_ACKNOWLEDGEMENT,
    update_service_category_policy,
)


class ReadOnlyRegistryAdmin(admin.ModelAdmin):
    """Prevent accidental manual mutation of manifest-derived registry facts."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ProviderDevelopmentDemoGrant, ReadOnlyRegistryAdmin)


def _representation_evidence_download(evidence):
    """Return private proof as an attachment so browser-active content never renders."""

    extension = {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/png": "png",
    }.get(evidence.mime_type)
    if extension is None or not representation_evidence_is_valid(evidence):
        raise Http404("Dovada nu este disponibilă.")
    response = HttpResponse(bytes(evidence.document), content_type=evidence.mime_type)
    response["Content-Disposition"] = (
        f'attachment; filename="dovada-reprezentare-{evidence.pk}.{extension}"'
    )
    response["Content-Length"] = evidence.byte_size
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(ReadOnlyRegistryAdmin):
    """Register immutable intake and route every later decision through audit services."""

    form = DataSubjectRequestIntakeForm
    change_form_template = "admin/services/datasubjectrequest/change_form.html"
    list_display = (
        "requester_name",
        "request_kind",
        "status",
        "deadline_state",
        "received_at",
    )
    list_filter = ("status", "request_kind", "channel", "received_at")
    search_fields = ("requester_name", "contact_email", "details")
    fields = (
        "request_kind",
        "channel",
        "requester_name",
        "contact_email",
        "details",
        "received_at",
    )
    readonly_fields = (
        "request_kind",
        "channel",
        "requester_name",
        "contact_email",
        "details",
        "status",
        "revision",
        "received_at",
        "due_at",
        "extended_due_at",
        "extension_notified_at",
        "identity_verified_at",
        "closed_at",
        "recorded_by",
        "retention_applied_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        """Allow controlled intake only to users holding Django's explicit add permission."""

        return request.user.has_perm("services.add_datasubjectrequest")

    def get_fields(self, request, obj=None):
        return self.readonly_fields if obj is not None else self.fields

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj is not None else ()

    def get_changeform_initial_data(self, request):
        return {"received_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")}

    def save_model(self, request, obj, form, change):
        """Pin recorder and one-calendar-month deadline on the only allowed create path."""

        if change:
            raise PermissionDenied
        obj.recorded_by = request.user
        obj.due_at = initial_data_request_due_at(obj.received_at)
        super().save_model(request, obj, form, change)

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Cereri privind datele personale",
            },
        )

    @admin.display(description="Termen")
    def deadline_state(self, obj):
        if obj.status in (
            DataSubjectRequest.Status.FULFILLED,
            DataSubjectRequest.Status.REFUSED,
        ):
            return "Închisă"
        remaining = obj.effective_due_at - timezone.now()
        if remaining.total_seconds() < 0:
            return "Termen depășit"
        if remaining.days < 7:
            return f"Scadentă în {remaining.days + 1} zile"
        return obj.effective_due_at

    def get_urls(self):
        return [
            path(
                "<int:object_id>/process/",
                self.admin_site.admin_view(self.process_view),
                name="services_datasubjectrequest_process",
            )
        ] + super().get_urls()

    def process_view(self, request, object_id):
        """Render inert facts on GET and accept one guarded POST transition."""

        if not (
            self.has_view_permission(request)
            and request.user.has_perm("services.process_data_subject_request")
        ):
            raise PermissionDenied
        item = get_object_or_404(
            DataSubjectRequest.objects.select_related("recorded_by").prefetch_related(
                "events__actor"
            ),
            pk=object_id,
        )
        is_closed = item.status in (
            DataSubjectRequest.Status.FULFILLED,
            DataSubjectRequest.Status.REFUSED,
        )
        form = DataSubjectRequestProcessForm(
            request.POST or None,
            item=item,
            initial={"expected_revision": item.revision},
        )
        if request.method == "POST" and not is_closed and form.is_valid():
            action = form.cleaned_data["action"]
            try:
                if action == "extend_deadline":
                    extend_data_subject_request_deadline(
                        request_id=item.pk,
                        actor=request.user,
                        expected_revision=form.cleaned_data["expected_revision"],
                        internal_note=form.cleaned_data["internal_note"],
                        acknowledgement=EXTENSION_ACKNOWLEDGEMENT,
                    )
                    success_message = "Prelungirea și notificarea au fost înregistrate."
                elif action == "generate_export":
                    content = generate_data_subject_export(
                        request_id=item.pk,
                        actor=request.user,
                        expected_revision=form.cleaned_data["expected_revision"],
                        acknowledgement=EXPORT_ACKNOWLEDGEMENT,
                    )
                    response = HttpResponse(
                        content,
                        content_type="application/json; charset=utf-8",
                    )
                    response["Content-Disposition"] = (
                        f'attachment; filename="{EXPORT_FILENAME}"'
                    )
                    response["Cache-Control"] = "no-store, private"
                    response["Pragma"] = "no-cache"
                    return response
                else:
                    advance_data_subject_request(
                        request_id=item.pk,
                        actor=request.user,
                        expected_revision=form.cleaned_data["expected_revision"],
                        new_status=action,
                        internal_note=form.cleaned_data["internal_note"],
                        acknowledgement=PROCESS_ACKNOWLEDGEMENT,
                    )
                    success_message = "Starea cererii a fost actualizată și jurnalizată."
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, success_message, level=messages.SUCCESS)
                return HttpResponseRedirect(
                    reverse(
                        "admin:services_datasubjectrequest_change", args=(item.pk,)
                    )
                )
        if request.method == "POST" and form.errors:
            for field in form.visible_fields():
                if field.errors:
                    field.field.widget.attrs["autofocus"] = True
                    break
        context = {
            **self.admin_site.each_context(request),
            "title": f"Procesează cererea — {item.requester_name}",
            "item": item,
            "events": item.events.all(),
            "form": form,
            "is_closed": is_closed,
            "is_overdue": not is_closed and timezone.now() > item.effective_due_at,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/datasubjectrequest/process.html",
            context,
        )


admin.site.register(DataSubjectRequestEvent, ReadOnlyRegistryAdmin)


@admin.register(ProviderProfile)
class ProviderProfileAdmin(ReadOnlyRegistryAdmin):
    """Offer a staff-only, inert preview of the provider's current private draft."""

    list_display = (
        "provider_name",
        "legal_name",
        "owner_account",
        "account_state",
        "publication_state",
        "subscription_state",
        "preview_action",
    )
    list_filter = ("state", "memberships__state")
    search_fields = (
        "display_name",
        "approved_claim__legal_name_at_request",
        "memberships__user__email",
    )

    def get_queryset(self, request):
        """Bound list rendering to the relations used by its operational columns."""

        return (
            super()
            .get_queryset(request)
            .select_related("approved_claim")
            .prefetch_related("memberships__user", "publication_scope", "subscription")
            .distinct()
        )

    def changelist_view(self, request, extra_context=None):
        """Name the operational list in Romanian rather than exposing model internals."""

        return super().changelist_view(
            request,
            extra_context={**(extra_context or {}), "title": "Conturi furnizori"},
        )

    @admin.display(description="Nume public", ordering="display_name")
    def provider_name(self, obj):
        return obj.display_name

    @admin.display(description="Denumire legală", ordering="approved_claim__legal_name_at_request")
    def legal_name(self, obj):
        return obj.approved_claim.legal_name_at_request

    @admin.display(description="Cont furnizor")
    def owner_account(self, obj):
        membership = next(
            (
                membership
                for membership in obj.memberships.all()
                if membership.state != ProviderMembership.State.REVOKED
            ),
            None,
        )
        return membership.user.email if membership else "—"

    @admin.display(description="Acces")
    def account_state(self, obj):
        membership = next(
            (
                membership
                for membership in obj.memberships.all()
                if membership.state != ProviderMembership.State.REVOKED
            ),
            None,
        )
        return membership.get_state_display() if membership else "Fără acces curent"

    @admin.display(description="Publicare")
    def publication_state(self, obj):
        try:
            scope = obj.publication_scope
        except ProviderPublicationScope.DoesNotExist:
            return "Nepublicat"
        return scope.get_visibility_display()

    @admin.display(description="Abonament")
    def subscription_state(self, obj):
        state = provider_subscription_state(obj)
        return (
            f"Activ până la {timezone.localtime(state.period_ends_at):%d.%m.%Y}"
            if state.is_active
            else state.label
        )

    @admin.display(description="Profil")
    def preview_action(self, obj):
        return format_html(
            '<a class="button" href="{}">Previzualizează</a>',
            reverse("admin:services_providerprofile_preview", args=(obj.pk,)),
        )

    def get_urls(self):
        """Expose a separate read-only route; the model form remains disabled."""

        return [
            path(
                "<int:object_id>/preview/",
                self.admin_site.admin_view(self.preview_view),
                name="services_providerprofile_preview",
            )
        ] + super().get_urls()

    def preview_view(self, request, object_id):
        """Preview the draft and route explicit POSTs through subscription services."""

        profile = get_object_or_404(
            ProviderProfile.objects.select_related("approved_claim").prefetch_related(
                "memberships__user",
                "portfolio_items__asset",
                "publication_submissions",
                "subscription__events",
            ),
            pk=object_id,
        )
        if not self.has_view_permission(request, profile):
            raise PermissionDenied

        subscription_state = provider_subscription_state(profile)
        subscription_form = ProviderSubscriptionAdminForm(
            request.POST if request.POST.get("workflow_action") == "subscription" else None,
            initial={"expected_revision": subscription_state.revision},
        )
        if request.method == "POST" and request.POST.get("workflow_action") == "subscription":
            if not request.user.has_perm("services.manage_provider_subscription"):
                raise PermissionDenied
            if subscription_form.is_valid():
                values = {
                    "profile_id": profile.pk,
                    "actor": request.user,
                    "expected_revision": subscription_form.cleaned_data["expected_revision"],
                    "internal_note": subscription_form.cleaned_data["internal_note"],
                    "acknowledgement": SUBSCRIPTION_ACKNOWLEDGEMENT,
                }
                try:
                    if (
                        subscription_form.cleaned_data["action"]
                        == ProviderSubscriptionEvent.Action.DEACTIVATE
                    ):
                        deactivate_provider_subscription(**values)
                        notice = "Abonamentul de test a fost dezactivat."
                    else:
                        activate_or_extend_provider_subscription(**values)
                        notice = "Abonamentul de test a fost activat sau prelungit cu 30 de zile."
                except (PermissionError, ValueError) as error:
                    subscription_form.add_error(None, str(error))
                else:
                    messages.success(request, notice)
                    return HttpResponseRedirect(request.path)

        membership = next(
            (
                candidate
                for candidate in profile.memberships.all()
                if candidate.state != ProviderMembership.State.REVOKED
            ),
            None,
        )
        service_draft = (
            ProviderServiceAreaDraft.objects.filter(profile=profile)
            .prefetch_related("services", "coverage")
            .first()
        )
        publication_scope = ProviderPublicationScope.objects.filter(
            profile=profile
        ).first()
        current_submission = next(
            (
                submission
                for submission in profile.publication_submissions.all()
                if submission.superseded_at is None
            ),
            None,
        )
        category_labels = {slug: label for slug, label, _description in CATEGORIES}
        service_labels = tuple(
            category_labels.get(slug, slug)
            for slug in (
                service_draft.services.values_list("category", flat=True)
                if service_draft
                else ()
            )
        )
        coverage_labels = tuple(
            f"{locality_name(county, code)} — {county}"
            for county, code in (
                service_draft.coverage.values_list("county", "siruta_code")
                if service_draft
                else ()
            )
        )
        words = [word for word in profile.display_name.split() if word]
        initials = "".join(word[0] for word in words[:2]).upper() or "SA"
        context = {
            **self.admin_site.each_context(request),
            "title": f"Previzualizare cont — {profile.display_name}",
            "profile": profile,
            "legal_name": profile.approved_claim.legal_name_at_request,
            "membership": membership,
            "service_draft": service_draft,
            "service_labels": service_labels,
            "coverage_labels": coverage_labels,
            "portfolio_items": profile.portfolio_items.select_related("asset"),
            "publication_scope": publication_scope,
            "current_submission": current_submission,
            "subscription_state": subscription_state,
            "subscription_form": subscription_form,
            "can_manage_subscription": request.user.has_perm(
                "services.manage_provider_subscription"
            ),
            "initials": initials,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/providerprofile/preview.html",
            context,
        )


admin.site.register(ProviderSubscription, ReadOnlyRegistryAdmin)
admin.site.register(ProviderSubscriptionEvent, ReadOnlyRegistryAdmin)


@admin.register(ManagedSiteInquiry)
class ManagedSiteInquiryAdmin(ReadOnlyRegistryAdmin):
    """Expose Partner briefs to operators without permitting silent edits."""

    list_display = (
        "profile",
        "goal",
        "desired_launch",
        "status",
        "revision",
        "notification_state",
        "created_at",
        "workflow_action",
    )
    list_filter = ("status", "goal", "desired_launch", "notification_state")
    search_fields = ("profile__display_name", "profile__public_id")
    readonly_fields = (
        "profile",
        "created_by",
        "goal",
        "desired_launch",
        "current_website",
        "brief",
        "privacy_notice_version",
        "consented_at",
        "notification_state",
        "status",
        "revision",
        "created_at",
        "updated_at",
        "retention_applied_at",
    )

    @admin.display(description="Procesare")
    def workflow_action(self, obj):
        return format_html(
            '<a href="{}">Deschide fluxul</a>',
            reverse("admin:services_managedsiteinquiry_process", args=(obj.pk,)),
        )

    def get_urls(self):
        return [
            path(
                "<int:object_id>/process/",
                self.admin_site.admin_view(self.process_view),
                name="services_managedsiteinquiry_process",
            )
        ] + super().get_urls()

    def process_view(self, request, object_id):
        """Render the brief on GET and accept only an audited forward transition."""

        if not (
            self.has_view_permission(request)
            and request.user.has_perm("services.process_managed_site_inquiry")
        ):
            raise PermissionDenied
        item = get_object_or_404(
            ManagedSiteInquiry.objects.select_related("profile", "created_by").prefetch_related(
                "events__actor"
            ),
            pk=object_id,
        )
        is_terminal = item.status in (
            ManagedSiteInquiry.Status.ACCEPTED,
            ManagedSiteInquiry.Status.CLOSED,
        )
        form = ManagedSiteInquiryProcessForm(
            request.POST or None,
            item=item,
            initial={"expected_revision": item.revision},
        )
        if request.method == "POST" and not is_terminal and form.is_valid():
            try:
                transition_managed_site_inquiry(
                    inquiry_id=item.pk,
                    actor=request.user,
                    expected_revision=form.cleaned_data["expected_revision"],
                    new_status=form.cleaned_data["action"],
                    internal_note=form.cleaned_data["internal_note"],
                    acknowledgement=MANAGED_SITE_PROCESS_ACKNOWLEDGEMENT,
                )
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(
                    request,
                    "Starea solicitării a fost actualizată și jurnalizată.",
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(
                    reverse("admin:services_managedsiteinquiry_process", args=(item.pk,))
                )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Procesează solicitarea Partener — {item.profile.display_name}",
            "item": item,
            "events": item.events.all(),
            "form": form,
            "is_terminal": is_terminal,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/managedsiteinquiry/process.html",
            context,
        )


admin.site.register(ManagedSiteInquiryEvent, ReadOnlyRegistryAdmin)


@admin.register(SourceSnapshot)
class SourceSnapshotAdmin(ReadOnlyRegistryAdmin):
    list_display = ("provider", "snapshot_date", "state", "created_at")


@admin.register(ImportRun)
class ImportRunAdmin(ReadOnlyRegistryAdmin):
    list_display = ("snapshot", "county", "state", "attempt_count", "finished_at")
    list_filter = ("state", "county")


@admin.register(RegisteredBusinessSnapshot)
class RegisteredBusinessSnapshotAdmin(ReadOnlyRegistryAdmin):
    list_display = (
        "legal_name",
        "registered_county_raw",
        "registered_office_siruta",
        "status_eligibility",
    )
    list_filter = ("status_eligibility", "registered_county_raw")
    search_fields = ("legal_name", "business__registration_number", "cui")


admin.site.register(BusinessIdentity, ReadOnlyRegistryAdmin)
admin.site.register(BusinessStatus, ReadOnlyRegistryAdmin)
admin.site.register(BusinessCaen, ReadOnlyRegistryAdmin)
admin.site.register(BusinessCategory, ReadOnlyRegistryAdmin)
admin.site.register(ImportQuarantine, ReadOnlyRegistryAdmin)
admin.site.register(PublicationApproval, ReadOnlyRegistryAdmin)
admin.site.register(CatalogueScope, ReadOnlyRegistryAdmin)
admin.site.register(CatalogueActivationEvent, ReadOnlyRegistryAdmin)
admin.site.register(VerifiedServiceEvidence, ReadOnlyRegistryAdmin)
admin.site.register(VerifiedServiceCoverage, ReadOnlyRegistryAdmin)
admin.site.register(ProviderServiceAreaDraft, ReadOnlyRegistryAdmin)
admin.site.register(ProviderDraftService, ReadOnlyRegistryAdmin)
admin.site.register(ProviderDraftCoverage, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPortfolioAsset, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPortfolioItem, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPublicationService, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPublicationCoverage, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPublicationPortfolioItem, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPublicationScope, ReadOnlyRegistryAdmin)
admin.site.register(ProviderPublicationEvent, ReadOnlyRegistryAdmin)


@admin.register(ProviderServiceAreaSubmission)
class ProviderServiceAreaSubmissionAdmin(ReadOnlyRegistryAdmin):
    """Expose an explicit review queue without permitting model-form mutation."""

    change_form_template = "admin/services/providerserviceareasubmission/change_form.html"
    list_display = (
        "provider_name",
        "revision",
        "decision",
        "is_current",
        "submitted_at",
    )
    list_filter = ("decision", "superseded_at", "submitted_at")
    search_fields = ("draft__profile__display_name",)
    readonly_fields = (
        "draft",
        "revision",
        "snapshot_schema_version",
        "services_snapshot",
        "coverage_snapshot",
        "contract_sha256",
        "authorization_run",
        "catalogue_run",
        "siruta_catalogue_version",
        "siruta_catalogue_sha256",
        "submitted_by",
        "submitted_at",
        "decision",
        "reviewed_by",
        "reviewed_at",
        "review_policy_version",
        "review_acknowledgement",
        "internal_review_note",
        "provider_feedback",
        "superseded_at",
        "superseded_by",
        "superseded_by_revision",
    )

    @admin.display(description="Furnizor")
    def provider_name(self, obj):
        return obj.draft.profile.display_name

    @admin.display(boolean=True, description="Curentă")
    def is_current(self, obj):
        return obj.superseded_at is None

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("draft__profile")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="services_providerserviceareasubmission_review",
            )
        ] + super().get_urls()

    def review_view(self, request, object_id):
        """Decide one exact pending revision only through a CSRF-protected POST."""

        if not request.user.has_perm("services.review_provider_service_area"):
            raise PermissionDenied
        submission = get_object_or_404(
            ProviderServiceAreaSubmission.objects.select_related(
                "draft__profile", "authorization_run", "catalogue_run"
            ),
            pk=object_id,
        )
        form = ProviderServiceAreaReviewForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                _submission, changed = review_provider_service_area_submission(
                    submission_id=submission.pk,
                    reviewer=request.user,
                    decision=form.cleaned_data["decision"],
                    internal_note=form.cleaned_data["internal_note"],
                    provider_feedback=form.cleaned_data["provider_feedback"],
                    acknowledgement=SERVICE_AREA_REVIEW_ACKNOWLEDGEMENT,
                )
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(
                    request,
                    "Decizia a fost înregistrată."
                    if changed
                    else "Aceeași decizie era deja înregistrată.",
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(
                    reverse(
                        "admin:services_providerserviceareasubmission_change",
                        args=(submission.pk,),
                    )
                )
        category_labels = {slug: label for slug, label, _description in CATEGORIES}
        context = {
            **self.admin_site.each_context(request),
            "title": f"Verifică revizia {submission.revision} — {submission.draft.profile.display_name}",
            "submission": submission,
            "service_labels": tuple(
                category_labels.get(slug, slug)
                for slug in submission.services_snapshot
            ),
            "coverage_labels": tuple(
                f"{locality_name(county, code)} — {county}"
                for county, code in submission.coverage_snapshot
            ),
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/providerserviceareasubmission/review.html",
            context,
        )


@admin.register(ProviderPublicationSubmission)
class ProviderPublicationSubmissionAdmin(ReadOnlyRegistryAdmin):
    """Review an immutable whole-profile snapshot through an explicit POST."""

    change_form_template = "admin/services/providerpublicationsubmission/change_form.html"
    list_display = ("provider_name", "version", "decision", "is_current", "submitted_at")
    list_filter = ("decision", "superseded_at", "submitted_at")
    search_fields = ("display_name", "profile__business__registration_number")
    readonly_fields = tuple(
        field.name
        for field in ProviderPublicationSubmission._meta.fields
        if field.name != "id"
    )

    @admin.display(description="Furnizor")
    def provider_name(self, obj):
        return obj.display_name

    @admin.display(boolean=True, description="Curentă")
    def is_current(self, obj):
        return obj.superseded_at is None

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="services_providerpublicationsubmission_review",
            )
        ] + super().get_urls()

    def review_view(self, request, object_id):
        if not request.user.has_perm("services.review_provider_publication"):
            raise PermissionDenied
        submission = get_object_or_404(
            ProviderPublicationSubmission.objects.select_related(
                "profile", "service_area_submission", "catalogue_run", "authorization_run"
            ),
            pk=object_id,
        )
        form = ProviderPublicationReviewForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                _submission, changed = review_provider_publication(
                    submission_id=submission.pk,
                    reviewer=request.user,
                    decision=form.cleaned_data["decision"],
                    visibility=form.cleaned_data["visibility"],
                    internal_note=form.cleaned_data["internal_note"],
                    provider_feedback=form.cleaned_data["provider_feedback"],
                    acknowledgement=PUBLICATION_REVIEW_ACKNOWLEDGEMENT,
                )
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(
                    request,
                    "Profilul a fost activat." if changed else "Decizia era deja înregistrată.",
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(
                    reverse(
                        "admin:services_providerpublicationsubmission_change",
                        args=(submission.pk,),
                    )
                )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Publică versiunea {submission.version} — {submission.display_name}",
            "submission": submission,
            "service_labels": tuple(
                dict((slug, label) for slug, label, _description in CATEGORIES).get(
                    slug, slug
                )
                for slug in submission.services.values_list("category", flat=True)
            ),
            "coverage_labels": tuple(
                f"{locality_name(county, code)} — {county}"
                for county, code in submission.coverage.values_list("county", "siruta_code")
            ),
            "portfolio_items": submission.portfolio_items.select_related("asset"),
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/providerpublicationsubmission/review.html",
            context,
        )


@admin.register(ProviderRegistrationRequest)
class ProviderRegistrationRequestAdmin(ReadOnlyRegistryAdmin):
    """Review unlisted-company intake without allowing ad-hoc state edits."""

    change_form_template = "admin/services/providerregistrationrequest/change_form.html"
    exclude = ("token_digest", "token_expires_at", "password_hash")
    list_display = (
        "legal_name",
        "cui",
        "registration_number",
        "requested_category_label",
        "registered_county",
        "contact_name",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "email_delivery_state",
        "requested_category",
        "registered_county",
        "created_at",
    )
    search_fields = ("legal_name", "cui", "registration_number", "contact_name", "email")
    readonly_fields = (
        "legal_name",
        "cui",
        "registration_number",
        "requested_category",
        "registered_county",
        "registered_office_siruta",
        "contact_name",
        "role",
        "email",
        "account_first_name",
        "account_last_name",
        "account_username",
        "credentials_supplied_at",
        "status",
        "email_delivery_state",
        "email_verified_at",
        "privacy_notice_version",
        "consented_at",
        "linked_business",
        "converted_claim_link",
        "reviewed_at",
        "reviewed_by",
        "review_note",
        "review_policy_version",
        "created_at",
    )

    @admin.display(description="Serviciu principal", ordering="requested_category")
    def requested_category_label(self, registration):
        """Present the provider's intake choice without treating it as verified."""

        return registration.get_requested_category_display() or "—"

    @admin.display(description="Revendicare rezultată")
    def converted_claim_link(self, registration):
        """Link the audit record to the existing claim review workflow."""

        if not registration.converted_claim_id:
            return "—"
        url = reverse(
            "admin:services_providerclaimrequest_change",
            args=(registration.converted_claim_id,),
        )
        return format_html('<a href="{}">Revendicarea #{}</a>', url, registration.converted_claim_id)

    def get_urls(self):
        """Expose one explicit reconciliation surface for reviewed identities."""

        return [
            path(
                "<int:object_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="services_providerregistrationrequest_review",
            ),
            path(
                "<int:object_id>/evidence/",
                self.admin_site.admin_view(self.evidence_view),
                name="services_providerregistrationrequest_evidence",
            ),
        ] + super().get_urls()

    def evidence_view(self, request, object_id):
        """Download registration proof only for the dedicated reviewer."""

        if not request.user.has_perm("services.review_provider_registration"):
            raise PermissionDenied
        evidence = get_object_or_404(
            ProviderRepresentationEvidence, registration_id=object_id
        )
        return _representation_evidence_download(evidence)

    def review_view(self, request, object_id):
        """Convert or reject an e-mail-verified registration transactionally."""

        if not request.user.has_perm("services.review_provider_registration"):
            raise PermissionDenied
        registration = get_object_or_404(ProviderRegistrationRequest, pk=object_id)
        if registration.status != ProviderRegistrationRequest.Status.REVIEW_PENDING:
            self.message_user(
                request,
                "Înscrierea nu mai este disponibilă pentru verificare.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse(
                    "admin:services_providerregistrationrequest_change",
                    args=(registration.pk,),
                )
            )
        form = ProviderRegistrationReviewForm(
            request.POST or None,
            initial={"verified_registration_number": registration.registration_number},
        )
        if request.method == "POST" and form.is_valid():
            try:
                if form.cleaned_data["decision"] == "convert":
                    claim = convert_provider_registration_to_claim(
                        registration_id=registration.pk,
                        reviewer=request.user,
                        verified_registration_number=form.cleaned_data[
                            "verified_registration_number"
                        ],
                        review_note=form.cleaned_data["review_note"],
                        acknowledgement=REGISTRATION_REVIEW_ACKNOWLEDGEMENT,
                    )
                    self.message_user(
                        request,
                        "Identitatea a fost verificată. Continuă cu verificarea revendicării.",
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse(
                            "admin:services_providerclaimrequest_review", args=(claim.pk,)
                        )
                    )
                reject_provider_registration(
                    registration_id=registration.pk,
                    reviewer=request.user,
                    review_note=form.cleaned_data["review_note"],
                    acknowledgement=REGISTRATION_REVIEW_ACKNOWLEDGEMENT,
                )
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, "Înscrierea a fost respinsă.", level=messages.SUCCESS)
                return HttpResponseRedirect(
                    reverse(
                        "admin:services_providerregistrationrequest_change",
                        args=(registration.pk,),
                    )
                )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Verifică înscrierea — {registration.legal_name}",
            "registration": registration,
            "evidence": getattr(registration, "representation_evidence", None),
            "locality_label": locality_name(
                registration.registered_county,
                registration.registered_office_siruta,
            ),
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/providerregistrationrequest/review.html",
            context,
        )


@admin.register(ProviderClaimRequest)
class ProviderClaimRequestAdmin(ReadOnlyRegistryAdmin):
    """Expose claim progress for audit without permitting ad-hoc approval edits."""

    change_form_template = "admin/services/providerclaimrequest/change_form.html"
    exclude = ("token_digest", "token_expires_at", "password_hash")

    list_display = (
        "legal_name_at_request",
        "contact_name",
        "email",
        "status",
        "email_delivery_state",
        "created_at",
    )
    list_filter = ("status", "email_delivery_state", "created_at")
    search_fields = ("legal_name_at_request", "contact_name", "email")
    readonly_fields = (
        "business",
        "legal_name_at_request",
        "contact_name",
        "role",
        "email",
        "account_first_name",
        "account_last_name",
        "account_username",
        "credentials_supplied_at",
        "status",
        "email_delivery_state",
        "email_verified_at",
        "privacy_notice_version",
        "consented_at",
        "reviewed_at",
        "reviewed_by",
        "review_note",
        "approval_policy_version",
        "created_at",
    )

    def get_urls(self):
        """Expose one explicit review surface; no bulk or model-form decisions."""

        return [
            path(
                "<int:object_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="services_providerclaimrequest_review",
            ),
            path(
                "<int:object_id>/resend-invitation/",
                self.admin_site.admin_view(self.resend_invitation_view),
                name="services_providerclaimrequest_resend_invitation",
            ),
            path(
                "<int:object_id>/evidence/",
                self.admin_site.admin_view(self.evidence_view),
                name="services_providerclaimrequest_evidence",
            ),
        ] + super().get_urls()

    def evidence_view(self, request, object_id):
        """Download claim proof only for the dedicated claim reviewer."""

        if not request.user.has_perm("services.review_provider_claim"):
            raise PermissionDenied
        evidence = get_object_or_404(
            ProviderRepresentationEvidence, claim_id=object_id
        )
        return _representation_evidence_download(evidence)

    def review_view(self, request, object_id):
        """Record an approved/rejected decision through the transactional service."""

        if not request.user.has_perm("services.review_provider_claim"):
            raise PermissionDenied
        claim = get_object_or_404(
            ProviderClaimRequest.objects.select_related("business"), pk=object_id
        )
        if claim.status != ProviderClaimRequest.Status.REVIEW_PENDING:
            self.message_user(
                request,
                "Cererea nu mai este disponibilă pentru verificare.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse("admin:services_providerclaimrequest_change", args=(claim.pk,))
            )
        form = ProviderClaimReviewForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                if form.cleaned_data["decision"] == "approve":
                    _profile, invitation, token = approve_provider_claim(
                        claim_id=claim.pk,
                        reviewer=request.user,
                        review_note=form.cleaned_data["review_note"],
                        acknowledgement=REVIEW_ACKNOWLEDGEMENT,
                    )
                    if invitation is None:
                        message = (
                            "Cererea a fost aprobată. Contul este activ și solicitantul "
                            "se poate autentifica prin e-mail și parolă."
                        )
                        level = messages.SUCCESS
                    else:
                        activation_url = request.build_absolute_uri(
                            reverse("services:provider_activate", args=(token,))
                        )
                        delivered = deliver_provider_invitation_email(
                            invitation=ProviderAccountInvitation.objects.select_related(
                                "membership__user", "membership__profile"
                            ).get(pk=invitation.pk),
                            activation_url=activation_url,
                        )
                        message = (
                            "Cererea istorică a fost aprobată și invitația a fost trimisă."
                            if delivered
                            else "Cererea a fost aprobată, dar invitația nu a putut fi trimisă."
                        )
                        level = messages.SUCCESS if delivered else messages.WARNING
                else:
                    reject_provider_claim(
                        claim_id=claim.pk,
                        reviewer=request.user,
                        review_note=form.cleaned_data["review_note"],
                        acknowledgement=REVIEW_ACKNOWLEDGEMENT,
                    )
                    message, level = "Cererea a fost respinsă.", messages.SUCCESS
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, message, level=level)
                return HttpResponseRedirect(
                    reverse(
                        "admin:services_providerclaimrequest_change", args=(claim.pk,)
                    )
                )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Verifică revendicarea — {claim.legal_name_at_request}",
            "claim": claim,
            "evidence": getattr(claim, "representation_evidence", None),
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/services/providerclaimrequest/review.html", context
        )

    def resend_invitation_view(self, request, object_id):
        """Rotate and resend an unused invitation only after an explicit POST."""

        if not request.user.has_perm("services.review_provider_claim"):
            raise PermissionDenied
        claim = get_object_or_404(ProviderClaimRequest, pk=object_id)
        if request.method == "POST":
            try:
                invitation, token = rotate_provider_invitation(
                    claim_id=claim.pk,
                    reviewer=request.user,
                    acknowledgement=REVIEW_ACKNOWLEDGEMENT,
                )
                activation_url = request.build_absolute_uri(
                    reverse("services:provider_activate", args=(token,))
                )
                delivered = deliver_provider_invitation_email(
                    invitation=ProviderAccountInvitation.objects.select_related(
                        "membership__user", "membership__profile"
                    ).get(pk=invitation.pk),
                    activation_url=activation_url,
                )
            except (PermissionError, ValueError) as error:
                self.message_user(request, str(error), level=messages.ERROR)
            else:
                self.message_user(
                    request,
                    (
                        "Invitația nouă a fost trimisă."
                        if delivered
                        else "Invitația a fost rotită, dar e-mailul nu a putut fi trimis."
                    ),
                    level=messages.SUCCESS if delivered else messages.WARNING,
                )
            return HttpResponseRedirect(
                reverse("admin:services_providerclaimrequest_change", args=(claim.pk,))
            )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Retrimite invitația — {claim.legal_name_at_request}",
            "claim": claim,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/providerclaimrequest/resend_invitation.html",
            context,
        )


admin.site.register(ProviderMembership, ReadOnlyRegistryAdmin)
admin.site.register(ProviderAccountInvitation, ReadOnlyRegistryAdmin)


@admin.register(ProviderCustomerReview)
class ProviderCustomerReviewAdmin(ReadOnlyRegistryAdmin):
    """Expose immutable reviews with a separate audited moderation route."""

    change_form_template = "admin/services/providercustomerreview/change_form.html"
    list_display = ("provider_name", "reviewer_display_name", "rating", "status", "submitted_at")
    list_filter = ("status", "rating", "submitted_at")
    search_fields = ("profile__display_name", "reviewer_display_name", "body")
    readonly_fields = tuple(
        field.name for field in ProviderCustomerReview._meta.fields if field.name != "id"
    )

    @admin.display(description="Furnizor", ordering="profile__display_name")
    def provider_name(self, obj):
        return obj.profile.display_name

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile", "lead", "reviewed_by")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/moderate/",
                self.admin_site.admin_view(self.moderate_view),
                name="services_providercustomerreview_moderate",
            )
        ] + super().get_urls()

    def moderate_view(self, request, object_id):
        if not request.user.has_perm("services.moderate_customer_review"):
            raise PermissionDenied
        review = get_object_or_404(
            ProviderCustomerReview.objects.select_related("profile", "lead"),
            pk=object_id,
        )
        form = ProviderCustomerReviewModerationForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                moderate_customer_review(
                    review_id=review.pk,
                    actor=request.user,
                    decision=form.cleaned_data["decision"],
                    internal_note=form.cleaned_data["internal_note"],
                    acknowledgement=MODERATION_ACKNOWLEDGEMENT,
                )
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, "Decizia asupra recenziei a fost înregistrată.")
                return HttpResponseRedirect(
                    reverse("admin:services_providercustomerreview_change", args=(review.pk,))
                )
        return TemplateResponse(
            request,
            "admin/services/providercustomerreview/moderate.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Moderează recenzia — {review.profile.display_name}",
                "review": review,
                "form": form,
                "opts": self.model._meta,
            },
        )


admin.site.register(ProviderCustomerReviewEvent, ReadOnlyRegistryAdmin)


@admin.register(ProviderCustomerReviewReply)
class ProviderCustomerReviewReplyAdmin(ReadOnlyRegistryAdmin):
    """Expose immutable provider replies with audited moderation."""

    change_form_template = "admin/services/providercustomerreviewreply/change_form.html"
    list_display = ("profile", "status", "submitted_at")
    list_filter = ("status", "submitted_at")
    readonly_fields = tuple(
        field.name for field in ProviderCustomerReviewReply._meta.fields if field.name != "id"
    )

    def get_urls(self):
        return [path("<int:object_id>/moderate/", self.admin_site.admin_view(self.moderate_view), name="services_providercustomerreviewreply_moderate")] + super().get_urls()

    def moderate_view(self, request, object_id):
        if not request.user.has_perm("services.moderate_customer_review_reply"):
            raise PermissionDenied
        reply = get_object_or_404(ProviderCustomerReviewReply, pk=object_id)
        form = ProviderCustomerReviewReplyModerationForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                moderate_provider_review_reply(reply_id=reply.pk, actor=request.user, decision=form.cleaned_data["decision"], internal_note=form.cleaned_data["internal_note"], acknowledgement=REPLY_MODERATION_ACKNOWLEDGEMENT)
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, "Decizia asupra răspunsului a fost înregistrată.")
                return HttpResponseRedirect(reverse("admin:services_providercustomerreviewreply_change", args=(reply.pk,)))
        return TemplateResponse(request, "admin/services/providercustomerreviewreply/moderate.html", {**self.admin_site.each_context(request), "title": "Moderează răspunsul firmei", "reply": reply, "form": form, "opts": self.model._meta})


admin.site.register(ProviderCustomerReviewReplyEvent, ReadOnlyRegistryAdmin)


@admin.register(PublicProviderReport)
class PublicProviderReportAdmin(ReadOnlyRegistryAdmin):
    """Expose immutable reports with a separate audited triage route."""

    change_form_template = "admin/services/publicproviderreport/change_form.html"
    change_list_template = "admin/services/publicproviderreport/change_list.html"
    list_display = ("provider_name", "reason", "triage_state", "created_at")
    list_filter = (
        "reason",
        "triage_case__state",
        "triage_case__outcome",
        "created_at",
    )
    search_fields = (
        "submission__display_name",
        "submission__profile__approved_claim__legal_name_at_request",
        "details",
    )
    readonly_fields = (
        "submission",
        "reason",
        "details",
        "reporter_session_digest",
        "created_at",
    )

    @admin.display(description="Profil", ordering="submission__display_name")
    def provider_name(self, obj):
        return obj.submission.display_name

    @admin.display(description="Stare analiză", ordering="triage_case__state")
    def triage_state(self, obj):
        try:
            return obj.triage_case.get_state_display()
        except PublicProviderReportCase.DoesNotExist:
            return "Dosar lipsă"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "submission__profile", "triage_case"
        )

    def changelist_view(self, request, extra_context=None):
        """Name the private queue without computing insights for unauthorized viewers."""

        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Sesizări despre profiluri publice",
            },
        )

    def get_urls(self):
        return [
            path(
                "insights/",
                self.admin_site.admin_view(self.insights_view),
                name="services_publicproviderreport_insights",
            ),
            path(
                "<int:object_id>/triage/",
                self.admin_site.admin_view(self.triage_view),
                name="services_publicproviderreport_triage",
            )
        ] + super().get_urls()

    def insights_view(self, request):
        """Render a least-privilege GET-only aggregate view of the report workflow."""

        if not (
            request.user.is_active
            and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm(
                "services.view_public_provider_report_insights"
            )
        ):
            raise PermissionDenied
        if request.method != "GET":
            return HttpResponseNotAllowed(("GET",))
        days = normalized_insight_window_days(request.GET.get("days"))
        context = {
            **self.admin_site.each_context(request),
            "title": "Perspectivă operațională asupra sesizărilor",
            "report_insights": public_report_insights(window_days=days),
            "window_choices": WINDOW_DAYS,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/publicproviderreport/insights.html",
            context,
        )

    def triage_view(self, request, object_id):
        """Render an inert GET and apply transitions only through a CSRF-protected POST."""

        if not (
            self.has_view_permission(request)
            and request.user.has_perm("services.triage_public_provider_report")
        ):
            raise PermissionDenied
        report = get_object_or_404(
            PublicProviderReport.objects.select_related(
                "submission__profile__business",
                "submission__service_area_submission",
                "triage_case",
            ).prefetch_related(
                "submission__services",
                "submission__coverage",
                "triage_case__events__actor",
            ),
            pk=object_id,
        )
        case = report.triage_case
        closing = case.state == PublicProviderReportCase.State.IN_REVIEW
        form = PublicProviderReportTriageForm(
            request.POST or None,
            closing=closing,
            initial={"expected_revision": case.revision},
        )
        if request.method == "POST" and case.state != PublicProviderReportCase.State.CLOSED and form.is_valid():
            try:
                if closing:
                    close_public_provider_report_case(
                        case_id=case.pk,
                        reviewer=request.user,
                        expected_revision=form.cleaned_data["expected_revision"],
                        outcome=form.cleaned_data["outcome"],
                        internal_note=form.cleaned_data["internal_note"],
                        acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
                    )
                    success_message = "Sesizarea a fost închisă, fără modificarea automată a profilului."
                else:
                    start_public_provider_report_review(
                        case_id=case.pk,
                        reviewer=request.user,
                        expected_revision=form.cleaned_data["expected_revision"],
                        internal_note=form.cleaned_data["internal_note"],
                        acknowledgement=TRIAGE_ACKNOWLEDGEMENT,
                    )
                    success_message = "Sesizarea a fost preluată în analiză."
            except (PermissionError, ValueError) as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, success_message, level=messages.SUCCESS)
                return HttpResponseRedirect(
                    reverse("admin:services_publicproviderreport_change", args=(report.pk,))
                )
        if request.method == "POST" and form.errors:
            for field in form.visible_fields():
                if field.errors:
                    field.field.widget.attrs["autofocus"] = True
                    break
        scope = ProviderPublicationScope.objects.filter(
            profile=report.submission.profile
        ).first()
        snapshot_is_current = bool(
            scope and scope.current_submission_id == report.submission_id
        )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Analizează sesizarea — {report.submission.display_name}",
            "report": report,
            "case": case,
            "events": case.events.all(),
            "form": form,
            "closing": closing,
            "snapshot_integrity_valid": publication_submission_contract_is_valid(
                report.submission
            ),
            "snapshot_is_current": snapshot_is_current,
            "current_visibility": scope.get_visibility_display() if scope else "Nepublicat",
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/publicproviderreport/triage.html",
            context,
        )


admin.site.register(PublicProviderReportCase, ReadOnlyRegistryAdmin)
admin.site.register(PublicProviderReportTriageEvent, ReadOnlyRegistryAdmin)


class CustomerAccessRecoveryFilter(admin.SimpleListFilter):
    """Separate reissuable links from expired and inconsistent private cases."""

    title = "E-mail client"
    parameter_name = "customer_access"

    def lookups(self, request, model_admin):
        choices = (
            ("needs_reissue", "Necesită reemitere"),
            ("expired", "Link expirat"),
        )
        return (
            choices + (("mixed", "Stare neuniformă"),)
            if model_admin.model is ProviderLeadBatch else choices
        )

    def queryset(self, request, queryset):
        state = self.value()
        if state not in {"needs_reissue", "expired", "mixed"}:
            return queryset
        if state == "mixed" and queryset.model is not ProviderLeadBatch:
            return queryset.none()
        active = queryset.filter(
            customer_account__isnull=True,
            retention_applied_at__isnull=True,
        )
        if queryset.model is ProviderLeadBatch:
            if state == "mixed":
                return active.filter(_active_failure=True, _active_other=True)
            active = active.filter(_active_failure=True, _active_other=False)
        else:
            active = active.filter(
                batch__isnull=True,
                customer_notification_failed_at__isnull=False,
                customer_notified_at__isnull=True,
            )
        expiry = (
            {"customer_access_expires_at__lte": timezone.now()}
            if state == "expired" else {"customer_access_expires_at__gt": timezone.now()}
        )
        return active.filter(**expiry)


class ProviderNotificationHealthFilter(admin.SimpleListFilter):
    """Match the delivery audit's active provider-copy counts exactly."""

    title = "Notificare firmă · activă"
    parameter_name = "provider_delivery"

    def lookups(self, request, model_admin):
        return (
            (ProviderLead.NotificationState.FAILED, "E-mail eșuat"),
            (ProviderLead.NotificationState.PENDING, "În așteptare"),
            (ProviderLead.NotificationState.SENT, "E-mail trimis"),
        )

    def queryset(self, request, queryset):
        if self.value() not in {
            ProviderLead.NotificationState.FAILED,
            ProviderLead.NotificationState.PENDING,
            ProviderLead.NotificationState.SENT,
        }:
            return queryset
        return queryset.filter(
            retention_applied_at__isnull=True,
            notification_state=self.value(),
        )


@admin.register(ProviderLead)
class ProviderLeadAdmin(ReadOnlyRegistryAdmin):
    """Expose private lead records and a separately permissioned aggregate view."""

    change_list_template = "admin/services/providerlead/change_list.html"
    change_form_template = "admin/services/providerlead/change_form.html"
    list_display = (
        "submitted_at",
        "provider_name",
        "provider_delivery_state",
        "customer_delivery_state",
    )
    list_filter = (ProviderNotificationHealthFilter, CustomerAccessRecoveryFilter, "status", "category", "county")
    search_fields = ("submission__display_name", "customer_name", "customer_email")
    readonly_fields = tuple(field.name for field in ProviderLead._meta.fields)

    @admin.display(description="Firmă", ordering="submission__display_name")
    def provider_name(self, obj):
        return obj.submission.display_name

    @admin.display(description="Data", ordering="created_at")
    def submitted_at(self, obj):
        return obj.created_at

    @admin.display(description="E-mail firmă", ordering="notification_state")
    def provider_delivery_state(self, obj):
        return obj.get_notification_state_display()

    @admin.display(description="E-mail client")
    def customer_delivery_state(self, obj):
        """Name the recovery state without showing an address or bearer token."""

        if obj.retention_applied_at:
            return "Date eliminate"
        if obj.customer_account_id:
            return "În contul clientului"
        if obj.batch_id:
            return "Prin cererea comună"
        if obj.customer_notified_at:
            return "Link trimis"
        if obj.customer_notification_failed_at:
            return "Necesită reemitere" if obj.customer_access_expires_at > timezone.now() else "Link expirat"
        return "În așteptare"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("submission")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/retry-customer-access/",
                self.admin_site.admin_view(self.retry_customer_access_view),
                name="services_providerlead_retry_customer_access",
            ),
            path(
                "<int:object_id>/retry-notification/",
                self.admin_site.admin_view(self.retry_notification_view),
                name="services_providerlead_retry_notification",
            ),
            path(
                "pilot/",
                self.admin_site.admin_view(self.pilot_view),
                name="services_providerlead_pilot",
            ),
            path(
                "insights/",
                self.admin_site.admin_view(self.insights_view),
                name="services_providerlead_insights",
            ),
            path(
                "delivery/",
                self.admin_site.admin_view(self.delivery_view),
                name="services_providerlead_delivery",
            ),
        ] + super().get_urls()

    def retry_customer_access_view(self, request, object_id):
        """Reissue an anonymous customer's failed private link under a row lock."""

        if not (
            request.user.is_active and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.retry_customer_access_notification")
        ):
            raise PermissionDenied
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        lead = get_object_or_404(ProviderLead, pk=object_id)
        eligible = (
            lead.batch_id is None and lead.customer_account_id is None
            and lead.retention_applied_at is None
            and lead.customer_notification_failed_at is not None
            and lead.customer_notified_at is None
            and lead.customer_access_expires_at is not None
            and lead.customer_access_expires_at > timezone.now()
        )
        if request.method == "GET":
            if not eligible:
                self.message_user(request, "Linkul nu este eligibil pentru reemitere.", level=messages.WARNING)
                return HttpResponseRedirect(reverse("admin:services_providerlead_change", args=(lead.pk,)))
            return TemplateResponse(request, "admin/services/providerlead/retry_customer_access.html", {
                **self.admin_site.each_context(request), "opts": self.model._meta, "target": lead,
            })
        if request.POST.get("acknowledgement") != "REEMITE":
            self.message_user(request, "Confirmarea reemiterii lipsește.", level=messages.ERROR)
        else:
            with transaction.atomic():
                lead = ProviderLead.objects.select_for_update().get(pk=lead.pk)
                try:
                    delivered = rotate_and_deliver_customer_access_notification(request=request, lead=lead)
                except ValueError:
                    self.message_user(request, "Linkul nu mai este eligibil pentru reemitere.", level=messages.WARNING)
                else:
                    self.log_change(request, lead, "Link privat reemis" if delivered else "Reemiterea linkului privat a eșuat")
                    self.message_user(
                        request,
                        "Noul link privat a fost trimis clientului." if delivered else "E-mailul a eșuat; linkul anterior este invalidat și se poate reîncerca.",
                        level=messages.SUCCESS if delivered else messages.WARNING,
                    )
        return HttpResponseRedirect(reverse("admin:services_providerlead_change", args=(lead.pk,)))

    def retry_notification_view(self, request, object_id):
        """Retry one failed e-mail under a row lock; never resend a successful one."""

        if not (
            request.user.is_active
            and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.retry_provider_lead_notification")
        ):
            raise PermissionDenied
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        lead = get_object_or_404(
            ProviderLead.objects.select_related("submission"),
            pk=object_id,
            retention_applied_at__isnull=True,
        )
        if request.method == "GET" and lead.notification_state != ProviderLead.NotificationState.FAILED:
            self.message_user(request, "Notificarea nu este eligibilă pentru retrimitere.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:services_providerlead_change", args=(lead.pk,)))
        if request.method == "POST":
            if request.POST.get("acknowledgement") != "RETRIMITE":
                self.message_user(request, "Confirmarea retrimiterii lipsește.", level=messages.ERROR)
            else:
                with transaction.atomic():
                    lead = ProviderLead.objects.select_related("submission").select_for_update().get(pk=lead.pk)
                    if lead.notification_state != ProviderLead.NotificationState.FAILED or lead.retention_applied_at:
                        self.message_user(request, "Notificarea nu mai este eligibilă pentru retrimitere.", level=messages.WARNING)
                    elif not provider_lead_recipient(lead):
                        self.message_user(request, "Nu există o adresă validă pentru firmă.", level=messages.ERROR)
                    else:
                        lead.notification_state = ProviderLead.NotificationState.PENDING
                        lead.notification_failed_at = None
                        lead.save(update_fields=("notification_state", "notification_failed_at"))
                        delivered = deliver_provider_lead_notification(
                            lead=lead, dashboard_url=provider_lead_focus_url(request, lead),
                        )
                        self.log_change(
                            request, lead,
                            "Notificare retrimisă" if delivered else "Retrimiterea notificării a eșuat",
                        )
                        self.message_user(
                            request,
                            "Notificarea a fost retrimisă." if delivered else "E-mailul nu a putut fi trimis; solicitarea rămâne în panoul firmei.",
                            level=messages.SUCCESS if delivered else messages.WARNING,
                        )
            return HttpResponseRedirect(reverse("admin:services_providerlead_change", args=(lead.pk,)))
        return TemplateResponse(
            request,
            "admin/services/providerlead/retry_notification.html",
            {**self.admin_site.each_context(request), "opts": self.model._meta, "lead": lead},
        )

    def pilot_view(self, request):
        """Render scoped launch evidence under the existing aggregate permission."""

        if not (
            request.user.is_active
            and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.view_provider_lead_insights")
        ):
            raise PermissionDenied
        if request.method != "GET":
            return HttpResponseNotAllowed(("GET",))
        counties = county_choices()
        categories = tuple((slug, label) for slug, label, _description in CATEGORIES)
        county = request.GET.get("county")
        category = request.GET.get("category")
        county = county if county in dict(counties) else "Iași"
        category = category if category in dict(categories) else "constructii"
        days = normalized_lead_insight_window_days(request.GET.get("days"))
        context = {
            **self.admin_site.each_context(request),
            "title": "Pregătirea lansării locale",
            "pilot": pilot_readiness(county=county, category=category, window_days=days),
            "counties": counties,
            "categories": categories,
            "window_choices": LEAD_WINDOW_DAYS,
            "days": days,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/services/providerlead/pilot.html", context)

    def insights_view(self, request):
        """Render GET-only project demand aggregates without customer identity."""

        if not (
            request.user.is_active
            and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.view_provider_lead_insights")
        ):
            raise PermissionDenied
        if request.method != "GET":
            return HttpResponseNotAllowed(("GET",))
        days = normalized_lead_insight_window_days(request.GET.get("days"))
        context = {
            **self.admin_site.each_context(request),
            "title": "Cerere și acoperire operațională",
            "lead_insights": provider_lead_insights(window_days=days),
            "window_choices": LEAD_WINDOW_DAYS,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/providerlead/insights.html",
            context,
        )

    def delivery_view(self, request):
        """Show the command's identity-free delivery facts to authorized staff."""

        if not (
            request.user.is_active
            and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.view_provider_lead_insights")
        ):
            raise PermissionDenied
        if request.method != "GET":
            return HttpResponseNotAllowed(("GET",))
        return TemplateResponse(
            request,
            "admin/services/providerlead/delivery.html",
            {
                **self.admin_site.each_context(request),
                "title": "Livrarea notificărilor",
                "delivery": audit_request_delivery(),
                "opts": self.model._meta,
            },
        )


class ProviderLeadBatchAdmin(ReadOnlyRegistryAdmin):
    """Allow a separately authorized recovery of a failed comparison link."""

    change_form_template = "admin/services/providerleadbatch/change_form.html"
    list_display = ("created_at", "category", "county", "customer_delivery_state")
    list_filter = (CustomerAccessRecoveryFilter, "category", "county")

    def get_queryset(self, request):
        """Project active-child delivery facts without hydrating private requests."""

        active = ProviderLead.objects.filter(batch_id=OuterRef("pk"), retention_applied_at__isnull=True)
        return super().get_queryset(request).annotate(
            _active_failure=Exists(active.filter(
                customer_notification_failed_at__isnull=False,
                customer_notified_at__isnull=True,
            )),
            _active_other=Exists(active.exclude(
                customer_notification_failed_at__isnull=False,
                customer_notified_at__isnull=True,
            )),
            _active_notified=Exists(active.filter(customer_notified_at__isnull=False)),
        )

    @admin.display(description="E-mail client")
    def customer_delivery_state(self, obj):
        """Show one project-level state even when it reached several firms."""

        if obj.retention_applied_at:
            return "Date eliminate"
        if obj.customer_account_id:
            return "În contul clientului"
        if obj._active_failure and not obj._active_other:
            return "Necesită reemitere" if obj.customer_access_expires_at > timezone.now() else "Link expirat"
        if obj._active_failure:
            return "Stare neuniformă"
        if obj._active_notified:
            return "Link trimis"
        return "În așteptare"

    def get_urls(self):
        return [path(
            "<int:object_id>/retry-customer-access/",
            self.admin_site.admin_view(self.retry_customer_access_view),
            name="services_providerleadbatch_retry_customer_access",
        )] + super().get_urls()

    def retry_customer_access_view(self, request, object_id):
        """Rotate and resend one failed anonymous batch capability."""

        if not (
            request.user.is_active and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.retry_customer_access_notification")
        ):
            raise PermissionDenied
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        batch = get_object_or_404(ProviderLeadBatch, pk=object_id)
        if request.method == "GET":
            active_leads = batch.leads.filter(retention_applied_at__isnull=True)
            if (
                batch.customer_account_id or batch.retention_applied_at
                or batch.customer_access_expires_at <= timezone.now()
                or not active_leads.exists()
                or active_leads.exclude(
                    customer_notification_failed_at__isnull=False,
                    customer_notified_at__isnull=True,
                ).exists()
            ):
                self.message_user(request, "Linkul nu este eligibil pentru reemitere.", level=messages.WARNING)
                return HttpResponseRedirect(reverse("admin:services_providerleadbatch_change", args=(batch.pk,)))
            return TemplateResponse(request, "admin/services/providerlead/retry_customer_access.html", {
                **self.admin_site.each_context(request), "opts": self.model._meta, "target": batch,
            })
        if request.POST.get("acknowledgement") != "REEMITE":
            self.message_user(request, "Confirmarea reemiterii lipsește.", level=messages.ERROR)
        else:
            with transaction.atomic():
                batch = ProviderLeadBatch.objects.select_for_update().get(pk=batch.pk)
                try:
                    delivered = rotate_and_deliver_customer_access_notification(request=request, batch=batch)
                except ValueError:
                    self.message_user(request, "Linkul nu mai este eligibil pentru reemitere.", level=messages.WARNING)
                else:
                    self.log_change(request, batch, "Link privat reemis" if delivered else "Reemiterea linkului privat a eșuat")
                    self.message_user(
                        request,
                        "Noul link privat a fost trimis clientului." if delivered else "E-mailul a eșuat; linkul anterior este invalidat și se poate reîncerca.",
                        level=messages.SUCCESS if delivered else messages.WARNING,
                    )
        return HttpResponseRedirect(reverse("admin:services_providerleadbatch_change", args=(batch.pk,)))


admin.site.register(ProviderLeadBatch, ProviderLeadBatchAdmin)
admin.site.register(CustomerAccount, ReadOnlyRegistryAdmin)
admin.site.register(ProviderLeadEvent, ReadOnlyRegistryAdmin)
admin.site.register(ProviderLeadMessage, ReadOnlyRegistryAdmin)
admin.site.register(ProviderQuote, ReadOnlyRegistryAdmin)


@admin.register(ServiceCategoryPolicy)
class ServiceCategoryPolicyAdmin(ReadOnlyRegistryAdmin):
    """Expose taxonomy locks and route changes through one audited operation."""

    change_list_template = "admin/services/servicecategorypolicy/change_list.html"
    list_display = (
        "category_label",
        "state",
        "display_order",
        "revision",
        "updated_at",
    )
    list_filter = ("state",)
    readonly_fields = tuple(field.name for field in ServiceCategoryPolicy._meta.fields)

    @admin.display(description="Categorie", ordering="category")
    def category_label(self, obj):
        return CATEGORY_CATALOGUE[obj.category][0]

    def get_urls(self):
        return [
            path(
                "manage/",
                self.admin_site.admin_view(self.manage_view),
                name="services_servicecategorypolicy_manage",
            )
        ] + super().get_urls()

    def manage_view(self, request):
        """Render and apply one revision-bound category policy at a time."""

        if not (
            request.user.is_active
            and request.user.is_staff
            and self.has_view_permission(request)
            and request.user.has_perm("services.manage_service_category_policy")
        ):
            raise PermissionDenied
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(("GET", "POST"))

        policies = tuple(ServiceCategoryPolicy.objects.select_related("updated_by"))
        submitted_category = request.POST.get("category", "")
        bound_form = (
            ServiceCategoryPolicyUpdateForm(request.POST)
            if request.method == "POST"
            else None
        )
        if bound_form is not None and bound_form.is_valid():
            try:
                _policy, changed = update_service_category_policy(
                    category=bound_form.cleaned_data["category"],
                    state=bound_form.cleaned_data["state"],
                    display_order=bound_form.cleaned_data["display_order"],
                    expected_revision=bound_form.cleaned_data["expected_revision"],
                    reason=bound_form.cleaned_data["reason"],
                    actor=request.user,
                    acknowledgement=(
                        CATEGORY_POLICY_ACKNOWLEDGEMENT
                        if bound_form.cleaned_data["acknowledgement"]
                        else ""
                    ),
                )
            except (PermissionError, ValueError) as error:
                bound_form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    "Politica a fost actualizată și auditată."
                    if changed
                    else "Politica era deja configurată astfel.",
                )
                return HttpResponseRedirect(
                    reverse("admin:services_servicecategorypolicy_manage")
                )

        rows = []
        for policy in policies:
            form = (
                bound_form
                if bound_form is not None and submitted_category == policy.category
                else ServiceCategoryPolicyUpdateForm(
                    initial={
                        "category": policy.category,
                        "state": policy.state,
                        "display_order": policy.display_order,
                        "expected_revision": policy.revision,
                    }
                )
            )
            rows.append(
                {
                    "policy": policy,
                    "label": CATEGORY_CATALOGUE[policy.category][0],
                    "description": CATEGORY_CATALOGUE[policy.category][1],
                    "form": form,
                    "open": bound_form is form,
                }
            )
        context = {
            **self.admin_site.each_context(request),
            "title": "Disponibilitatea serviciilor",
            "rows": rows,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/services/servicecategorypolicy/manage.html",
            context,
            status=400 if bound_form is not None and bound_form.errors else 200,
        )


@admin.register(ServiceCategoryPolicyEvent)
class ServiceCategoryPolicyEventAdmin(ReadOnlyRegistryAdmin):
    """Expose the append-only category-policy decision history."""

    list_display = (
        "created_at",
        "policy",
        "revision",
        "previous_state",
        "new_state",
        "actor",
    )
    list_filter = ("new_state", "created_at")
    search_fields = ("policy__category", "reason", "actor__username")
    readonly_fields = tuple(
        field.name for field in ServiceCategoryPolicyEvent._meta.fields
    )


admin.site.login_form = ThrottledAdminAuthenticationForm
