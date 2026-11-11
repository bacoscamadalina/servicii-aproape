"""Persistent legal-registry staging models, isolated from marketplace profiles."""

import uuid

from django.conf import settings
from django.db.models import F, Q
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .catalog import CATEGORIES


class SourceSnapshot(models.Model):
    """One immutable, manifest-verified national source bundle."""

    class State(models.TextChoices):
        VERIFIED = "verified", "Verificat"
        REJECTED = "rejected", "Respins"

    provider = models.CharField(max_length=40)
    snapshot_date = models.DateField()
    manifest_sha256 = models.CharField(max_length=64)
    dataset_url = models.URLField(max_length=500)
    license_label = models.CharField(max_length=80)
    verified_resources = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=State, default=State.VERIFIED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "snapshot_date"), name="uniq_snapshot_date"
            ),
            models.UniqueConstraint(
                fields=("provider", "manifest_sha256"), name="uniq_snapshot_manifest"
            ),
        ]
        ordering = ("-snapshot_date", "provider")

    def __str__(self) -> str:
        return f"{self.provider} — {self.snapshot_date:%Y-%m-%d}"


class ImportRun(models.Model):
    """One isolated, repeatable pilot scope built from a verified snapshot."""

    class State(models.TextChoices):
        PENDING = "pending", "În așteptare"
        RUNNING = "running", "În curs"
        SUCCEEDED = "succeeded", "Finalizat"
        FAILED = "failed", "Eșuat"

    snapshot = models.ForeignKey(
        SourceSnapshot, on_delete=models.PROTECT, related_name="import_runs"
    )
    scope_key = models.CharField(max_length=64)
    county = models.CharField(max_length=80)
    categories = models.JSONField(default=list)
    caen_mapping_version = models.CharField(max_length=20)
    caen_mapping_hash = models.CharField(max_length=64)
    status_policy_version = models.CharField(max_length=20)
    locality_policy = models.CharField(max_length=40, default="exact_only")
    locality_rules_hash = models.CharField(max_length=64, blank=True)
    scope_contract_version = models.PositiveSmallIntegerField(default=1)
    refined_from_run = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="refinement_runs",
    )
    activity_evidence_snapshot = models.ForeignKey(
        SourceSnapshot, on_delete=models.PROTECT, null=True, blank=True,
        related_name="evidence_import_runs",
    )
    activity_evidence_policy_version = models.CharField(max_length=20, blank=True)
    activity_evidence_policy_hash = models.CharField(max_length=64, blank=True)
    activity_evidence_year = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=State, default=State.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    counters = models.JSONField(default=dict)
    error_summary = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("snapshot", "scope_key"), name="uniq_snapshot_scope"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        scope_contract_version=1,
                        refined_from_run__isnull=True,
                        activity_evidence_snapshot__isnull=True,
                        activity_evidence_policy_version="",
                        activity_evidence_policy_hash="",
                        activity_evidence_year__isnull=True,
                    )
                    | (
                        Q(
                            scope_contract_version=2,
                            refined_from_run__isnull=False,
                            activity_evidence_snapshot__isnull=False,
                            activity_evidence_year__isnull=False,
                        )
                        & ~Q(activity_evidence_policy_version="")
                        & ~Q(activity_evidence_policy_hash="")
                    )
                ),
                name="valid_scope_contract_evidence",
            ),
        ]
        indexes = [models.Index(fields=("state",), name="import_run_state_idx")]

    def __str__(self) -> str:
        return f"{self.snapshot} — {self.county} — {self.state}"


class BusinessIdentity(models.Model):
    """Stable ONRC identity keyed only by the official registration number."""

    registration_number = models.CharField(max_length=80, unique=True)

    def __str__(self) -> str:
        return self.registration_number


class RegistryBusinessQuerySet(models.QuerySet):
    """Expose the only records eligible for internal staging consumers."""

    def staging_candidates(self, import_run: ImportRun):
        return self.filter(
            import_run=import_run,
            import_run__state=ImportRun.State.SUCCEEDED,
            import_run__snapshot__state=SourceSnapshot.State.VERIFIED,
            status_eligibility=RegisteredBusinessSnapshot.StatusEligibility.ELIGIBLE,
            locality_match__in=("exact", "hierarchy_alias"),
        )


class RegisteredBusinessSnapshot(models.Model):
    """Immutable legal facts staged by one run; never a marketplace profile."""

    class StatusEligibility(models.TextChoices):
        ELIGIBLE = "eligible_function_only", "Eligibil tehnic"
        EXCLUDED_RADIATED = "excluded_radiated", "Radiată"
        NEEDS_REVIEW = "needs_review_mixed_function", "Stare mixtă"
        QUARANTINED = "quarantined_without_function", "Fără funcțiune"

    import_run = models.ForeignKey(
        ImportRun, on_delete=models.CASCADE, related_name="business_snapshots"
    )
    business = models.ForeignKey(
        BusinessIdentity, on_delete=models.PROTECT, related_name="snapshot_records"
    )
    legal_name = models.CharField(max_length=500)
    cui = models.CharField(max_length=40, blank=True, db_index=True)
    euid = models.CharField(max_length=80, blank=True)
    legal_form = models.CharField(max_length=200, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    registered_country_raw = models.CharField(max_length=120, blank=True)
    registered_county_raw = models.CharField(max_length=120, blank=True)
    registered_locality_raw = models.CharField(max_length=240, blank=True)
    registered_office_siruta = models.CharField(max_length=12, db_index=True)
    locality_match = models.CharField(max_length=24, default="exact")
    status_eligibility = models.CharField(max_length=40, choices=StatusEligibility)
    registry_web = models.CharField(max_length=500, blank=True)
    source_fingerprint = models.CharField(max_length=32)
    objects = RegistryBusinessQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("import_run", "business"), name="uniq_run_business"
            )
        ]
        indexes = [
            models.Index(
                fields=("import_run", "registered_office_siruta"),
                name="run_siruta_idx",
            ),
            models.Index(
                fields=("import_run", "status_eligibility"),
                name="run_eligibility_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.legal_name


class BusinessStatus(models.Model):
    """One official ONRC status membership for a staged business record."""

    business_snapshot = models.ForeignKey(
        RegisteredBusinessSnapshot, on_delete=models.CASCADE, related_name="statuses"
    )
    code = models.CharField(max_length=16)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("business_snapshot", "code"), name="uniq_business_status"
            )
        ]


class BusinessCaen(models.Model):
    """One version-qualified authorized CAEN activity from the same snapshot."""

    business_snapshot = models.ForeignKey(
        RegisteredBusinessSnapshot, on_delete=models.CASCADE, related_name="caen_codes"
    )
    version = models.CharField(max_length=8)
    code = models.CharField(max_length=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("business_snapshot", "version", "code"),
                name="uniq_business_caen",
            )
        ]


class BusinessCategory(models.Model):
    """A curated ServiciiAproape category derived from the run-pinned CAEN mapping."""

    business_snapshot = models.ForeignKey(
        RegisteredBusinessSnapshot, on_delete=models.CASCADE, related_name="categories"
    )
    category = models.SlugField(max_length=60)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("business_snapshot", "category"),
                name="uniq_business_category",
            )
        ]


class ServiceCategoryPolicy(models.Model):
    """Operational presentation policy layered over the immutable CAEN taxonomy."""

    class State(models.TextChoices):
        ACTIVE = "active", "Activă"
        INTAKE_PAUSED = "intake_paused", "Înscrieri noi oprite"
        HIDDEN = "hidden", "Ascunsă din descoperire"

    category = models.SlugField(
        max_length=60,
        unique=True,
        choices=tuple((slug, label) for slug, label, _description in CATEGORIES),
    )
    state = models.CharField(max_length=24, choices=State, default=State.ACTIVE)
    display_order = models.PositiveSmallIntegerField()
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_service_category_policies",
    )

    class Meta:
        ordering = ("display_order", "category")
        permissions = [
            (
                "manage_service_category_policy",
                "Poate administra disponibilitatea categoriilor",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(display_order__gte=1),
                name="service_category_policy_positive_order",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_category_display()} — {self.get_state_display()}"


class ServiceCategoryPolicyEvent(models.Model):
    """Append-only revision recording one operational category-policy change."""

    policy = models.ForeignKey(
        ServiceCategoryPolicy,
        on_delete=models.PROTECT,
        related_name="events",
    )
    revision = models.PositiveIntegerField()
    previous_state = models.CharField(max_length=24, choices=ServiceCategoryPolicy.State)
    new_state = models.CharField(max_length=24, choices=ServiceCategoryPolicy.State)
    previous_order = models.PositiveSmallIntegerField()
    new_order = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=500)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="service_category_policy_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("policy", "revision"),
                name="uniq_service_category_policy_revision",
            )
        ]

    def __str__(self) -> str:
        return f"{self.policy.category} — revizia {self.revision}"


class PrimaryActivityEvidence(models.Model):
    """One privacy-minimized MF filing fact supporting one refined category."""

    business_snapshot = models.OneToOneField(
        RegisteredBusinessSnapshot,
        on_delete=models.CASCADE,
        related_name="primary_activity_evidence",
    )
    resource_kind = models.CharField(max_length=32)
    cui_join_fingerprint = models.CharField(max_length=64)
    caen_version = models.CharField(max_length=8)
    caen_code = models.CharField(max_length=4)
    reporting_year = models.PositiveSmallIntegerField()
    source_row_fingerprint = models.CharField(max_length=64)


class VerifiedServiceEvidence(models.Model):
    """Versioned human review of a provider's own public service statement."""

    class State(models.TextChoices):
        ACTIVE = "active", "Activă"
        SUPERSEDED = "superseded", "Înlocuită"
        REVOKED = "revoked", "Revocată"

    business = models.ForeignKey(
        BusinessIdentity,
        on_delete=models.PROTECT,
        related_name="verified_service_evidence",
    )
    category = models.SlugField(max_length=60)
    evidence_version = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=16, choices=State, default=State.ACTIVE)
    source_url = models.URLField(max_length=500)
    source_title = models.CharField(max_length=240)
    identity_reference = models.CharField(max_length=240)
    evidence_summary = models.CharField(max_length=500)
    retrieved_at = models.DateTimeField()
    content_sha256 = models.CharField(max_length=64)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="verified_service_evidence_reviews",
    )
    approved_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    superseded_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verified_service_evidence_revocations",
    )

    class Meta:
        permissions = [
            (
                "verify_service_evidence",
                "Can record or revoke direct service evidence",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("business", "category", "evidence_version"),
                name="uniq_service_evidence_version",
            ),
            models.UniqueConstraint(
                fields=("business", "category"),
                condition=Q(state="active"),
                name="uniq_active_service_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="active",
                        superseded_at__isnull=True,
                        revoked_at__isnull=True,
                        revoked_by__isnull=True,
                    )
                    | Q(
                        state="superseded",
                        superseded_at__isnull=False,
                        revoked_at__isnull=True,
                        revoked_by__isnull=True,
                    )
                    | Q(
                        state="revoked",
                        superseded_at__isnull=True,
                        revoked_at__isnull=False,
                        revoked_by__isnull=False,
                    )
                ),
                name="service_evidence_revocation_contract",
            ),
        ]


class VerifiedServiceCoverage(models.Model):
    """One canonical county explicitly declared by direct service evidence."""

    evidence = models.ForeignKey(
        VerifiedServiceEvidence,
        on_delete=models.CASCADE,
        related_name="coverage",
    )
    county = models.CharField(max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("evidence", "county"),
                name="uniq_service_evidence_county",
            )
        ]
        indexes = [
            models.Index(fields=("county",), name="service_evidence_county_idx")
        ]


class ProviderClaimRequest(models.Model):
    """A privacy-controlled request to prove representation of one legal entity."""

    class Status(models.TextChoices):
        EMAIL_PENDING = "email_pending", "E-mail neconfirmat"
        REVIEW_PENDING = "review_pending", "În verificare administrativă"
        APPROVED = "approved", "Aprobată"
        REJECTED = "rejected", "Respinsă"
        SUPERSEDED = "superseded", "Înlocuită"

    class DeliveryState(models.TextChoices):
        PENDING = "pending", "În așteptare"
        SENT = "sent", "Trimis"
        FAILED = "failed", "Eșuat"

    business = models.ForeignKey(
        BusinessIdentity,
        on_delete=models.PROTECT,
        related_name="provider_claim_requests",
    )
    legal_name_at_request = models.CharField(max_length=500)
    contact_name = models.CharField(max_length=160)
    role = models.CharField(max_length=160)
    email = models.EmailField(max_length=254)
    account_first_name = models.CharField(max_length=150, blank=True)
    account_last_name = models.CharField(max_length=150, blank=True)
    account_username = models.CharField(max_length=150, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)
    credentials_supplied_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=Status, default=Status.EMAIL_PENDING
    )
    token_digest = models.CharField(max_length=64, unique=True)
    token_expires_at = models.DateTimeField()
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_delivery_state = models.CharField(
        max_length=16, choices=DeliveryState, default=DeliveryState.PENDING
    )
    privacy_notice_version = models.CharField(max_length=20)
    consented_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provider_claim_reviews",
    )
    review_note = models.TextField(blank=True)
    approval_policy_version = models.CharField(max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retention_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("review_provider_claim", "Poate decide revendicări de profil")
        ]
        indexes = [
            models.Index(fields=("status", "created_at"), name="claim_status_created_idx"),
            models.Index(fields=("business", "email"), name="claim_business_email_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=("email_pending", "superseded"),
                        email_verified_at__isnull=True,
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                    )
                    | Q(
                        status="review_pending",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                    )
                    & (
                        Q(email_verified_at__isnull=False)
                        | Q(credentials_supplied_at__isnull=False)
                    )
                    | Q(
                        status__in=("approved", "rejected"),
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                        approval_policy_version__gt="",
                    )
                    & (
                        Q(email_verified_at__isnull=False)
                        | Q(credentials_supplied_at__isnull=False)
                    )
                ),
                name="provider_claim_status_timestamps",
            ),
        ]


class ProviderRegistrationRequest(models.Model):
    """A verified intake for a company that cannot yet be found in the catalogue."""

    class Status(models.TextChoices):
        EMAIL_PENDING = "email_pending", "E-mail neconfirmat"
        REVIEW_PENDING = "review_pending", "În verificare administrativă"
        CONVERTED = "converted", "Transferată la revendicare"
        REJECTED = "rejected", "Respinsă"
        SUPERSEDED = "superseded", "Înlocuită"

    class DeliveryState(models.TextChoices):
        PENDING = "pending", "În așteptare"
        SENT = "sent", "Trimis"
        FAILED = "failed", "Eșuat"

    legal_name = models.CharField(max_length=500)
    cui = models.CharField(max_length=12, db_index=True)
    registration_number = models.CharField(max_length=80, db_index=True)
    requested_category = models.CharField(
        max_length=32,
        choices=tuple((slug, label) for slug, label, _description in CATEGORIES),
        blank=True,
        default="",
    )
    registered_county = models.CharField(max_length=80)
    registered_office_siruta = models.CharField(max_length=12)
    contact_name = models.CharField(max_length=160)
    role = models.CharField(max_length=160)
    email = models.EmailField(max_length=254)
    account_first_name = models.CharField(max_length=150, blank=True)
    account_last_name = models.CharField(max_length=150, blank=True)
    account_username = models.CharField(max_length=150, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)
    credentials_supplied_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=Status, default=Status.EMAIL_PENDING
    )
    token_digest = models.CharField(max_length=64, unique=True)
    token_expires_at = models.DateTimeField()
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_delivery_state = models.CharField(
        max_length=16, choices=DeliveryState, default=DeliveryState.PENDING
    )
    privacy_notice_version = models.CharField(max_length=20)
    consented_at = models.DateTimeField()
    linked_business = models.ForeignKey(
        BusinessIdentity,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registration_requests",
    )
    converted_claim = models.OneToOneField(
        ProviderClaimRequest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_registration_request",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provider_registration_reviews",
    )
    review_note = models.TextField(blank=True)
    review_policy_version = models.CharField(max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retention_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("review_provider_registration", "Poate verifica înscrieri de firme")
        ]
        indexes = [
            models.Index(
                fields=("status", "created_at"), name="reg_status_created_idx"
            ),
            models.Index(
                fields=("registration_number", "email"),
                name="reg_number_email_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=("email_pending", "superseded"),
                        email_verified_at__isnull=True,
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                        linked_business__isnull=True,
                        converted_claim__isnull=True,
                    )
                    | Q(
                        status="review_pending",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                        linked_business__isnull=True,
                        converted_claim__isnull=True,
                    )
                    & (
                        Q(email_verified_at__isnull=False)
                        | Q(credentials_supplied_at__isnull=False)
                    )
                    | Q(
                        status="converted",
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                        linked_business__isnull=False,
                        converted_claim__isnull=False,
                        review_policy_version__gt="",
                    )
                    & (
                        Q(email_verified_at__isnull=False)
                        | Q(credentials_supplied_at__isnull=False)
                    )
                    | Q(
                        status="rejected",
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                        linked_business__isnull=True,
                        converted_claim__isnull=True,
                        review_policy_version__gt="",
                    )
                    & (
                        Q(email_verified_at__isnull=False)
                        | Q(credentials_supplied_at__isnull=False)
                    )
                ),
                name="provider_registration_status_contract",
            )
        ]

    def __str__(self) -> str:
        return self.legal_name


class ProviderRepresentationEvidence(models.Model):
    """Private proof that a claimant may represent exactly one company request."""

    class EvidenceType(models.TextChoices):
        ONRC_DOCUMENT = "onrc_document", _("Document ONRC recent")
        SIGNED_AUTHORIZATION = "signed_authorization", _("Împuternicire semnată")
        COMPANY_DOCUMENT = "company_document", _("Document oficial al firmei")

    claim = models.OneToOneField(
        ProviderClaimRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="representation_evidence",
    )
    registration = models.OneToOneField(
        ProviderRegistrationRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="representation_evidence",
    )
    evidence_type = models.CharField(max_length=32, choices=EvidenceType)
    document = models.BinaryField(editable=False)
    mime_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    declaration_version = models.CharField(max_length=48)
    declared_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(claim__isnull=False, registration__isnull=True)
                    | Q(claim__isnull=True, registration__isnull=False)
                ),
                name="representation_evidence_single_request",
            ),
            models.CheckConstraint(
                condition=Q(byte_size__gt=0),
                name="representation_evidence_nonempty",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(mime_type="")
                    & ~Q(sha256="")
                    & ~Q(declaration_version="")
                ),
                name="representation_evidence_metadata",
            ),
        ]


class ProviderProfile(models.Model):
    """Provider-owned draft content, intentionally separate from ONRC facts."""

    class State(models.TextChoices):
        DRAFT = "draft", "Ciornă"
        DISABLED = "disabled", "Dezactivat"

    class Availability(models.TextChoices):
        NOT_SPECIFIED = "not_specified", _("Nespecificată")
        ACCEPTING = "accepting", _("Acceptă solicitări noi")
        LIMITED = "limited", _("Disponibilitate limitată")
        UNAVAILABLE = "unavailable", _("Momentan indisponibil")

    class ContactPreference(models.TextChoices):
        ANY = "any", _("Oricare dintre metodele afișate")
        PHONE = "phone", _("Telefon")
        EMAIL = "email", _("E-mail")
        WEBSITE = "website", _("Website")

    business = models.OneToOneField(
        BusinessIdentity,
        on_delete=models.PROTECT,
        related_name="provider_profile",
    )
    approved_claim = models.OneToOneField(
        ProviderClaimRequest,
        on_delete=models.PROTECT,
        related_name="provider_profile",
    )
    state = models.CharField(max_length=16, choices=State, default=State.DRAFT)
    display_name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=1200)
    public_address = models.CharField(max_length=300, blank=True)
    public_phone = models.CharField(max_length=32, blank=True)
    public_email = models.EmailField(max_length=254, blank=True)
    website = models.URLField(max_length=500, blank=True)
    availability = models.CharField(
        max_length=24,
        choices=Availability,
        default=Availability.NOT_SPECIFIED,
    )
    contact_preference = models.CharField(
        max_length=16,
        choices=ContactPreference,
        default=ContactPreference.ANY,
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    public_content_revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProviderCRMCustomer(models.Model):
    """Provider-private contact; never an implicit ServiciiAproape account."""

    class State(models.TextChoices):
        ACTIVE = "active", _("Activ")
        ARCHIVED = "archived", _("Arhivat")

    profile = models.ForeignKey(
        ProviderProfile, on_delete=models.CASCADE, related_name="crm_customers",
    )
    name = models.CharField(max_length=160)
    email = models.EmailField(max_length=254, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=500, blank=True)
    notes = models.TextField(max_length=1200, blank=True)
    state = models.CharField(max_length=16, choices=State, default=State.ACTIVE)
    revision = models.PositiveBigIntegerField(default=1)
    lawful_use_confirmed_at = models.DateTimeField(default=timezone.now)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_crm_customers_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_crm_customers_updated",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(name="") & Q(revision__gt=0),
                name="provider_crm_customer_content_contract",
            ),
            models.CheckConstraint(
                condition=~(Q(email="") & Q(phone="")),
                name="provider_crm_customer_contact_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="active", archived_at__isnull=True)
                    | Q(state="archived", archived_at__isnull=False)
                ),
                name="provider_crm_customer_archive_contract",
            ),
        ]


class ProviderCRMCustomerEvent(models.Model):
    """PII-free audit journal for a provider customer record."""

    class Action(models.TextChoices):
        CREATED = "created", _("Creat")
        UPDATED = "updated", _("Actualizat")
        ARCHIVED = "archived", _("Arhivat")

    customer = models.ForeignKey(
        ProviderCRMCustomer, on_delete=models.CASCADE, related_name="events",
    )
    revision = models.PositiveBigIntegerField()
    action = models.CharField(max_length=16, choices=Action)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_crm_customer_events",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("customer", "revision"), name="uniq_provider_crm_customer_revision",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0), name="provider_crm_customer_event_revision_positive",
            ),
        ]


class ProviderDevelopmentDemoGrant(models.Model):
    """Explicit development-only authorization for one synthetic provider journey.

    The authorization run belongs to a distinct demo source. It must never be
    inserted into, or presented as, the ONRC catalogue.
    """

    profile = models.OneToOneField(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="development_demo_grant",
    )
    authorization_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        related_name="provider_development_demo_authorizations",
    )
    catalogue_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        related_name="provider_development_demo_catalogues",
    )
    enabled = models.BooleanField(default=True)
    internal_note = models.TextField(max_length=1200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_provider_development_demo_grants",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            (
                "manage_provider_development_demo",
                "Poate administra accesul demonstrativ al furnizorilor",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(internal_note=""),
                name="provider_demo_grant_note_required",
            )
        ]


class ProviderPortfolioAsset(models.Model):
    """One private, derived image asset owned by a provider profile."""

    class State(models.TextChoices):
        ACTIVE = "active", "Activ"
        REVOKED = "revoked", "Revocat"

    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="portfolio_assets",
    )
    opaque_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    image = models.FileField(upload_to="provider_portfolio/%Y/%m")
    sha256 = models.CharField(max_length=64)
    mime_type = models.CharField(max_length=32)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=State, default=State.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_provider_portfolio_assets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revoked_provider_portfolio_assets",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("profile", "state"),
                name="portfolio_asset_state_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(width__gt=0, height__gt=0),
                name="portfolio_asset_positive_dimensions",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="active", revoked_by__isnull=True, revoked_at__isnull=True)
                    | Q(
                        state="revoked",
                        revoked_by__isnull=False,
                        revoked_at__isnull=False,
                    )
                ),
                name="portfolio_asset_state_contract",
            ),
        ]


class ProviderPortfolioItem(models.Model):
    """One editable portfolio placement; asset ownership is checked by services."""

    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="portfolio_items",
    )
    asset = models.ForeignKey(
        ProviderPortfolioAsset,
        on_delete=models.PROTECT,
        related_name="portfolio_items",
    )
    caption = models.CharField(max_length=240, blank=True)
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "asset"),
                name="uniq_provider_portfolio_asset",
            ),
            models.UniqueConstraint(
                fields=("profile", "position"),
                name="uniq_provider_portfolio_position",
            ),
        ]


class ProviderServiceAreaDraft(models.Model):
    """Versioned private declaration of offered services and service localities."""

    class ReviewState(models.TextChoices):
        DRAFT = "draft", _("Ciornă")
        PENDING = "pending", _("În verificare")
        APPROVED = "approved", _("Aprobată")
        CHANGES_REQUIRED = "changes_required", _("Necesită modificări")

    profile = models.OneToOneField(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="service_area_draft",
    )
    revision = models.PositiveBigIntegerField(default=0)
    review_state = models.CharField(
        max_length=24, choices=ReviewState, default=ReviewState.DRAFT
    )
    reviewed_revision = models.PositiveBigIntegerField(null=True, blank=True)
    authorization_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provider_service_area_drafts",
    )
    siruta_catalogue_version = models.CharField(max_length=20, blank=True)
    siruta_catalogue_sha256 = models.CharField(max_length=64, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_provider_service_area_drafts",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        revision=0,
                        authorization_run__isnull=True,
                        siruta_catalogue_version="",
                        siruta_catalogue_sha256="",
                        reviewed_revision__isnull=True,
                        review_state="draft",
                    )
                    | (
                        Q(revision__gt=0)
                        & ~Q(siruta_catalogue_version="")
                        & ~Q(siruta_catalogue_sha256="")
                        & (
                            Q(
                                review_state="draft",
                                reviewed_revision__isnull=True,
                            )
                            | Q(authorization_run__isnull=False)
                        )
                    )
                ),
                name="provider_draft_source_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(reviewed_revision__isnull=True)
                    | Q(reviewed_revision__lte=models.F("revision"))
                ),
                name="provider_draft_reviewed_revision_lte",
            ),
            models.CheckConstraint(
                condition=(
                    Q(review_state="draft", reviewed_revision__isnull=True)
                    | (
                        Q(
                            review_state__in=(
                                "pending",
                                "approved",
                                "changes_required",
                            )
                        )
                        & Q(reviewed_revision=models.F("revision"))
                    )
                ),
                name="provider_draft_current_review",
            ),
        ]


class ProviderDraftService(models.Model):
    """One normalized category declared in a private provider draft."""

    draft = models.ForeignKey(
        ProviderServiceAreaDraft,
        on_delete=models.CASCADE,
        related_name="services",
    )
    category = models.SlugField(max_length=60)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("draft", "category"), name="uniq_provider_draft_service"
            )
        ]


class ProviderDraftCoverage(models.Model):
    """One exact SIRUTA locality declared as a private service area."""

    draft = models.ForeignKey(
        ProviderServiceAreaDraft,
        on_delete=models.CASCADE,
        related_name="coverage",
    )
    county = models.CharField(max_length=80)
    siruta_code = models.CharField(max_length=12)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("draft", "county", "siruta_code"),
                name="uniq_provider_draft_coverage",
            )
        ]
        indexes = [
            models.Index(
                fields=("county", "siruta_code"),
                name="provider_coverage_siruta_idx",
            )
        ]


class ProviderServiceAreaSubmission(models.Model):
    """Immutable content snapshot and audited decision for one draft revision."""

    class Decision(models.TextChoices):
        PENDING = "pending", _("În verificare")
        APPROVED = "approved", _("Aprobată intern")
        CHANGES_REQUIRED = "changes_required", _("Necesită modificări")

    draft = models.ForeignKey(
        ProviderServiceAreaDraft,
        on_delete=models.PROTECT,
        related_name="submissions",
    )
    revision = models.PositiveBigIntegerField()
    snapshot_schema_version = models.PositiveSmallIntegerField(default=1)
    services_snapshot = models.JSONField(default=list)
    coverage_snapshot = models.JSONField(default=list)
    contract_sha256 = models.CharField(max_length=64)
    authorization_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        related_name="provider_service_submissions_as_authorization",
    )
    catalogue_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        related_name="provider_service_submissions_as_catalogue",
    )
    siruta_catalogue_version = models.CharField(max_length=20)
    siruta_catalogue_sha256 = models.CharField(max_length=64)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_provider_service_areas",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    decision = models.CharField(
        max_length=24, choices=Decision, default=Decision.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_provider_service_areas",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_policy_version = models.CharField(max_length=24, blank=True)
    review_acknowledgement = models.CharField(max_length=120, blank=True)
    internal_review_note = models.TextField(blank=True, max_length=1200)
    provider_feedback = models.TextField(blank=True, max_length=700)
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_provider_service_areas",
    )
    superseded_by_revision = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        permissions = [
            (
                "review_provider_service_area",
                "Poate decide declarații de servicii și acoperire",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("draft", "revision"),
                name="uniq_provider_service_submission_revision",
            ),
            models.UniqueConstraint(
                fields=("draft",),
                condition=Q(superseded_at__isnull=True),
                name="uniq_current_provider_service_submission",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0),
                name="provider_submission_positive_revision",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        decision="pending",
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                        review_policy_version="",
                        review_acknowledgement="",
                        internal_review_note="",
                        provider_feedback="",
                    )
                    | (
                        Q(
                            decision="approved",
                            reviewed_by__isnull=False,
                            reviewed_at__isnull=False,
                        )
                        & ~Q(review_policy_version="")
                        & ~Q(review_acknowledgement="")
                        & ~Q(internal_review_note="")
                    )
                    | (
                        Q(
                            decision="changes_required",
                            reviewed_by__isnull=False,
                            reviewed_at__isnull=False,
                        )
                        & ~Q(review_policy_version="")
                        & ~Q(review_acknowledgement="")
                        & ~Q(internal_review_note="")
                        & ~Q(provider_feedback="")
                    )
                ),
                name="provider_submission_decision_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        superseded_at__isnull=True,
                        superseded_by__isnull=True,
                        superseded_by_revision__isnull=True,
                    )
                    | (
                        Q(
                            superseded_at__isnull=False,
                            superseded_by__isnull=False,
                            superseded_by_revision__isnull=False,
                        )
                        & Q(superseded_by_revision__gt=models.F("revision"))
                    )
                ),
                name="provider_submission_supersession_contract",
            ),
        ]
        indexes = [
            models.Index(
                fields=("decision", "superseded_at", "submitted_at"),
                name="provider_submission_queue_idx",
            )
        ]


class ProviderPublicationSubmission(models.Model):
    """Immutable publication snapshot for one provider content revision."""

    class Decision(models.TextChoices):
        PENDING = "pending", _("În verificare")
        APPROVED = "approved", _("Aprobată pentru publicare")
        CHANGES_REQUIRED = "changes_required", _("Necesită modificări")

    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="publication_submissions",
    )
    version = models.PositiveBigIntegerField()
    snapshot_schema_version = models.PositiveSmallIntegerField(default=2)
    profile_content_revision = models.PositiveBigIntegerField()
    display_name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=1200)
    public_address = models.CharField(max_length=300, blank=True)
    public_phone = models.CharField(max_length=32, blank=True)
    public_email = models.EmailField(max_length=254, blank=True)
    website = models.URLField(max_length=500, blank=True)
    availability = models.CharField(
        max_length=24,
        choices=ProviderProfile.Availability,
        default=ProviderProfile.Availability.NOT_SPECIFIED,
    )
    contact_preference = models.CharField(
        max_length=16,
        choices=ProviderProfile.ContactPreference,
        default=ProviderProfile.ContactPreference.ANY,
    )
    service_area_submission = models.ForeignKey(
        ProviderServiceAreaSubmission,
        on_delete=models.PROTECT,
        related_name="publication_submissions",
    )
    authorization_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        related_name="provider_publications_as_authorization",
    )
    catalogue_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        related_name="provider_publications_as_catalogue",
    )
    siruta_catalogue_version = models.CharField(max_length=20)
    siruta_catalogue_sha256 = models.CharField(max_length=64)
    contract_sha256 = models.CharField(max_length=64)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_provider_publications",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    decision = models.CharField(
        max_length=24, choices=Decision, default=Decision.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_provider_publications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_policy_version = models.CharField(max_length=24, blank=True)
    review_acknowledgement = models.CharField(max_length=120, blank=True)
    internal_review_note = models.TextField(blank=True, max_length=1200)
    provider_feedback = models.TextField(blank=True, max_length=700)
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_provider_publications",
    )
    superseded_by_version = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        permissions = [
            (
                "review_provider_publication",
                "Poate decide publicarea profilurilor de furnizor",
            )
        ]
        indexes = [
            models.Index(
                fields=("decision", "superseded_at", "submitted_at"),
                name="provider_pub_queue_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "version"),
                name="uniq_provider_publication_version",
            ),
            models.UniqueConstraint(
                fields=("profile",),
                condition=Q(superseded_at__isnull=True),
                name="uniq_current_provider_publication",
            ),
            models.CheckConstraint(
                condition=Q(version__gt=0),
                name="provider_publication_positive_version",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        decision="pending",
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                        review_policy_version="",
                        review_acknowledgement="",
                        internal_review_note="",
                        provider_feedback="",
                    )
                    | (
                        Q(
                            decision="approved",
                            reviewed_by__isnull=False,
                            reviewed_at__isnull=False,
                        )
                        & ~Q(review_policy_version="")
                        & ~Q(review_acknowledgement="")
                        & ~Q(internal_review_note="")
                    )
                    | (
                        Q(
                            decision="changes_required",
                            reviewed_by__isnull=False,
                            reviewed_at__isnull=False,
                        )
                        & ~Q(review_policy_version="")
                        & ~Q(review_acknowledgement="")
                        & ~Q(internal_review_note="")
                        & ~Q(provider_feedback="")
                    )
                ),
                name="provider_publication_decision_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        superseded_at__isnull=True,
                        superseded_by__isnull=True,
                        superseded_by_version__isnull=True,
                    )
                    | (
                        Q(
                            superseded_at__isnull=False,
                            superseded_by__isnull=False,
                            superseded_by_version__isnull=False,
                        )
                        & Q(superseded_by_version__gt=models.F("version"))
                    )
                ),
                name="provider_publication_supersession_contract",
            ),
        ]


class ProviderEngagementEvent(models.Model):
    """One privacy-minimized daily interaction with a visible provider snapshot."""

    class EventType(models.TextChoices):
        PROFILE_VIEW = "profile_view", _("Vizualizare profil")
        PHONE = "phone", _("Apăsare pe telefon")
        EMAIL = "email", _("Apăsare pe e-mail")
        WEBSITE = "website", _("Apăsare pe website")
        QUOTE_REQUEST = "quote_request", _("Pornire solicitare ofertă")

    submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.PROTECT,
        related_name="engagement_events",
    )
    event_type = models.CharField(max_length=24, choices=EventType)
    visitor_session_digest = models.CharField(max_length=64)
    occurred_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-occurred_on", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "submission",
                    "event_type",
                    "visitor_session_digest",
                    "occurred_on",
                ),
                name="uniq_provider_engagement_daily_session",
            )
        ]
        indexes = [
            models.Index(
                fields=("submission", "occurred_on", "event_type"),
                name="provider_engagement_metric_idx",
            ),
            models.Index(
                fields=("occurred_on", "id"),
                name="provider_engagement_ret_idx",
            ),
        ]


class ProviderPublicationService(models.Model):
    """One normalized service copied into an immutable publication snapshot."""

    submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.CASCADE,
        related_name="services",
    )
    category = models.SlugField(max_length=60)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "category"),
                name="uniq_publication_service",
            )
        ]


class ProviderPublicationCoverage(models.Model):
    """One exact locality copied into an immutable publication snapshot."""

    submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.CASCADE,
        related_name="coverage",
    )
    county = models.CharField(max_length=80)
    siruta_code = models.CharField(max_length=12)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "county", "siruta_code"),
                name="uniq_publication_coverage",
            )
        ]
        indexes = [
            models.Index(
                fields=("county", "siruta_code"),
                name="provider_pub_coverage_idx",
            )
        ]


class ProviderPublicationPortfolioItem(models.Model):
    """One ordered portfolio asset copied into a publication snapshot."""

    submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.CASCADE,
        related_name="portfolio_items",
    )
    asset = models.ForeignKey(
        ProviderPortfolioAsset,
        on_delete=models.PROTECT,
        related_name="publication_items",
    )
    position = models.PositiveSmallIntegerField()
    caption = models.CharField(max_length=240, blank=True)
    asset_sha256 = models.CharField(max_length=64)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "asset"),
                name="uniq_publication_portfolio_asset",
            ),
            models.UniqueConstraint(
                fields=("submission", "position"),
                name="uniq_publication_portfolio_position",
            ),
        ]


class ProviderPublicationScope(models.Model):
    """Stable, lockable pointer controlling one provider's visible snapshot."""

    class Visibility(models.TextChoices):
        OFF = "off", _("Oprit")
        INTERNAL_PREVIEW = "internal_preview", _("Previzualizare internă")
        PUBLIC = "public", _("Public")

    profile = models.OneToOneField(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="publication_scope",
    )
    visibility = models.CharField(
        max_length=24, choices=Visibility, default=Visibility.OFF
    )
    current_submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="active_scopes",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            (
                "publish_provider_profile",
                "Poate controla vizibilitatea profilurilor de furnizor",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        visibility="off",
                        current_submission__isnull=True,
                        activated_at__isnull=True,
                    )
                    | Q(
                        visibility__in=("internal_preview", "public"),
                        current_submission__isnull=False,
                        activated_at__isnull=False,
                    )
                ),
                name="provider_publication_scope_contract",
            )
        ]


class ProviderPublicationEvent(models.Model):
    """Append-only audit event for a provider publication pointer change."""

    class Action(models.TextChoices):
        PUBLISH = "publish", "Publicare"
        REPLACE = "replace", "Înlocuire"
        UNPUBLISH = "unpublish", "Retragere"

    scope = models.ForeignKey(
        ProviderPublicationScope,
        on_delete=models.PROTECT,
        related_name="events",
    )
    previous_submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publication_events_as_previous",
    )
    new_submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publication_events_as_new",
    )
    action = models.CharField(max_length=16, choices=Action)
    visibility = models.CharField(
        max_length=24, choices=ProviderPublicationScope.Visibility
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_publication_events",
    )
    note = models.TextField(blank=True, max_length=1200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("scope", "created_at"),
                name="provider_pub_event_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        action="publish",
                        previous_submission__isnull=True,
                        new_submission__isnull=False,
                        visibility__in=("internal_preview", "public"),
                    )
                    | (
                        Q(
                            action="replace",
                            previous_submission__isnull=False,
                            new_submission__isnull=False,
                            visibility__in=("internal_preview", "public"),
                        )
                        & ~Q(previous_submission=models.F("new_submission"))
                    )
                    | Q(
                        action="unpublish",
                        previous_submission__isnull=False,
                        new_submission__isnull=True,
                        visibility="off",
                    )
                ),
                name="provider_publication_event_contract",
            )
        ]


class ProviderSubscription(models.Model):
    """Stable entitlement controlling access to published professional content."""

    class Status(models.TextChoices):
        INACTIVE = "inactive", _("Inactiv")
        ACTIVE = "active", _("Activ")

    profile = models.OneToOneField(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="subscription",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.INACTIVE)
    period_started_at = models.DateTimeField(null=True, blank=True)
    period_ends_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            (
                "manage_provider_subscription",
                "Poate administra abonamentele furnizorilor",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status="inactive",
                        period_started_at__isnull=True,
                        period_ends_at__isnull=True,
                    )
                    | (
                        Q(
                            status="active",
                            period_started_at__isnull=False,
                            period_ends_at__isnull=False,
                        )
                        & Q(period_ends_at__gt=models.F("period_started_at"))
                    )
                ),
                name="provider_subscription_period_contract",
            )
        ]


class ProviderSubscriptionEvent(models.Model):
    """Append-only audit event for an administrator-managed entitlement change."""

    class Action(models.TextChoices):
        ACTIVATE = "activate", "Activare"
        EXTEND = "extend", "Prelungire"
        DEACTIVATE = "deactivate", "Dezactivare"

    subscription = models.ForeignKey(
        ProviderSubscription,
        on_delete=models.PROTECT,
        related_name="events",
    )
    action = models.CharField(max_length=16, choices=Action)
    previous_status = models.CharField(max_length=16, choices=ProviderSubscription.Status)
    new_status = models.CharField(max_length=16, choices=ProviderSubscription.Status)
    previous_period_ends_at = models.DateTimeField(null=True, blank=True)
    new_period_ends_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveBigIntegerField()
    internal_note = models.TextField(max_length=1200)
    policy_version = models.CharField(max_length=24)
    acknowledgement = models.CharField(max_length=160)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_subscription_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "revision"),
                name="uniq_provider_subscription_revision",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revision__gt=0)
                    & ~Q(internal_note="")
                    & ~Q(policy_version="")
                    & ~Q(acknowledgement="")
                ),
                name="provider_subscription_event_contract",
            ),
        ]


class ManagedSiteInquiry(models.Model):
    """A provider-owned request for the separately delivered Partner service."""

    class Status(models.TextChoices):
        RECEIVED = "received", _("Primită")
        CONTACTED = "contacted", _("Discuție începută")
        PROPOSAL_SENT = "proposal_sent", _("Propunere trimisă")
        ACCEPTED = "accepted", _("Propunere acceptată")
        CLOSED = "closed", _("Închisă")

    class Goal(models.TextChoices):
        NEW_PRESENCE = "new_presence", _("Prezență online de la zero")
        MODERNIZE = "modernize", _("Modernizarea unui site existent")
        MORE_REQUESTS = "more_requests", _("Mai multe cereri de la clienți")
        APPOINTMENTS = "appointments", _("Programări și contact mai simplu")

    class DesiredLaunch(models.TextChoices):
        THIRTY_DAYS = "30_days", _("În aproximativ 30 de zile")
        SIXTY_DAYS = "60_days", _("În aproximativ 60 de zile")
        NINETY_DAYS = "90_days", _("În aproximativ 90 de zile")
        EXPLORING = "exploring", _("Analizez opțiunile")

    class NotificationState(models.TextChoices):
        PENDING = "pending", "În așteptare"
        SENT = "sent", "Trimisă"
        FAILED = "failed", "Eșuată"

    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="managed_site_inquiries",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_site_inquiries",
    )
    goal = models.CharField(max_length=24, choices=Goal)
    desired_launch = models.CharField(max_length=16, choices=DesiredLaunch)
    current_website = models.URLField(max_length=500, blank=True)
    brief = models.TextField(max_length=1200)
    privacy_notice_version = models.CharField(max_length=20)
    consented_at = models.DateTimeField()
    notification_state = models.CharField(
        max_length=16,
        choices=NotificationState,
        default=NotificationState.PENDING,
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.RECEIVED,
    )
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    retention_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        permissions = (
            (
                "process_managed_site_inquiry",
                "Poate procesa solicitări pentru planul Partener",
            ),
        )
        indexes = [
            models.Index(
                fields=("profile", "created_at"),
                name="managed_site_profile_time_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(brief="") & ~Q(privacy_notice_version=""),
                name="managed_site_inquiry_content_contract",
            )
        ]


class ManagedSiteInquiryEvent(models.Model):
    """One append-only, operator-authored transition for a Partner inquiry."""

    inquiry = models.ForeignKey(
        ManagedSiteInquiry,
        on_delete=models.PROTECT,
        related_name="events",
    )
    previous_status = models.CharField(max_length=16, choices=ManagedSiteInquiry.Status)
    new_status = models.CharField(max_length=16, choices=ManagedSiteInquiry.Status)
    revision = models.PositiveIntegerField()
    internal_note = models.TextField(max_length=1000)
    policy_version = models.CharField(max_length=24)
    acknowledgement = models.CharField(max_length=200)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_site_inquiry_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("inquiry", "revision"),
                name="uniq_managed_site_inquiry_revision",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revision__gt=0)
                    & ~Q(internal_note="")
                    & ~Q(policy_version="")
                    & ~Q(acknowledgement="")
                    & ~Q(previous_status=models.F("new_status"))
                ),
                name="managed_site_inquiry_event_contract",
            ),
        ]
class CustomerAccount(models.Model):
    """One authenticated customer identity, separate from provider ownership."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_account",
    )
    normalized_email = models.EmailField(max_length=254, unique=True)
    privacy_notice_version = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=~Q(normalized_email="") & ~Q(privacy_notice_version=""),
                name="customer_account_identity_contract",
            )
        ]

    def __str__(self) -> str:
        return self.user.get_full_name() or self.user.username


class ProviderLeadBatch(models.Model):
    """One customer project dispatched to a bounded set of visible providers."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    category = models.SlugField(max_length=60)
    county = models.CharField(max_length=80)
    siruta_code = models.CharField(max_length=12)
    visitor_session_digest = models.CharField(max_length=64)
    # Historical projects have no nonce; new requests store only its one-way digest.
    submission_nonce_digest = models.CharField(max_length=64, unique=True, null=True, blank=True)
    privacy_notice_version = models.CharField(max_length=20)
    customer_access_digest = models.CharField(max_length=64, unique=True)
    customer_access_expires_at = models.DateTimeField()
    customer_account = models.ForeignKey(
        CustomerAccount,
        on_delete=models.PROTECT,
        related_name="lead_batches",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    retention_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("visitor_session_digest", "created_at"),
                name="lead_batch_session_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(category="")
                    & ~Q(county="")
                    & ~Q(siruta_code="")
                    & ~Q(visitor_session_digest="")
                    & ~Q(customer_access_digest="")
                ),
                name="provider_lead_batch_content",
            ),
            models.CheckConstraint(
                condition=(
                    Q(retention_applied_at__isnull=True)
                    | Q(
                        customer_account__isnull=True,
                        customer_access_expires_at__lte=models.F("retention_applied_at"),
                    )
                ),
                name="retained_lead_batch_detached",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.county} — {self.category} — {self.public_id}"


class ProviderLead(models.Model):
    """One private customer request pinned to the provider snapshot they viewed."""

    class Status(models.TextChoices):
        NEW = "new", _("Nouă")
        CONTACTED = "contacted", _("Client contactat")
        VISIT_SCHEDULED = "visit_scheduled", _("Vizionare programată")
        QUOTE_SENT = "quote_sent", _("Ofertă trimisă")
        WON = "won", _("Lucrare acceptată")
        COMPLETED = "completed", _("Finalizată")
        DECLINED = "declined", _("Refuzată")

    class Budget(models.TextChoices):
        UNSPECIFIED = "unspecified", _("De stabilit")
        UNDER_5000 = "under_5000", _("Sub 5.000 lei")
        FROM_5000_TO_15000 = "5000_15000", _("5.000–15.000 lei")
        FROM_15000_TO_50000 = "15000_50000", _("15.000–50.000 lei")
        OVER_50000 = "over_50000", _("Peste 50.000 lei")

    class DesiredStart(models.TextChoices):
        URGENT = "urgent", _("Cât mai curând")
        WITHIN_MONTH = "within_month", _("În următoarea lună")
        ONE_TO_THREE_MONTHS = "one_to_three_months", _("În 1–3 luni")
        LATER = "later", _("Peste 3 luni")
        FLEXIBLE = "flexible", _("Perioadă flexibilă")

    class NotificationState(models.TextChoices):
        PENDING = "pending", _("În așteptare")
        SENT = "sent", _("Trimisă")
        FAILED = "failed", _("Eșuată")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.PROTECT,
        related_name="customer_leads",
    )
    batch = models.ForeignKey(
        ProviderLeadBatch,
        on_delete=models.PROTECT,
        related_name="leads",
        null=True,
        blank=True,
    )
    category = models.SlugField(max_length=60)
    county = models.CharField(max_length=80)
    siruta_code = models.CharField(max_length=12)
    customer_name = models.CharField(max_length=120)
    customer_email = models.EmailField(max_length=254)
    customer_phone = models.CharField(max_length=32)
    customer_account = models.ForeignKey(
        CustomerAccount,
        on_delete=models.PROTECT,
        related_name="leads",
        null=True,
        blank=True,
    )
    crm_customer = models.ForeignKey(
        ProviderCRMCustomer,
        on_delete=models.SET_NULL,
        related_name="provider_leads",
        null=True,
        blank=True,
    )
    crm_customer_revision = models.PositiveBigIntegerField(default=0)
    project_address = models.CharField(max_length=300, blank=True)
    description = models.TextField(max_length=2000)
    budget = models.CharField(
        max_length=24,
        choices=Budget,
        default=Budget.UNSPECIFIED,
    )
    desired_start = models.CharField(max_length=24, choices=DesiredStart)
    status = models.CharField(max_length=24, choices=Status, default=Status.NEW)
    revision = models.PositiveBigIntegerField(default=0)
    owner_notes = models.TextField(max_length=2000, blank=True)
    visitor_session_digest = models.CharField(max_length=64)
    # Batch children remain null; only directly submitted projects own a replay key.
    submission_nonce_digest = models.CharField(max_length=64, unique=True, null=True, blank=True)
    privacy_notice_version = models.CharField(max_length=20)
    notification_state = models.CharField(
        max_length=16,
        choices=NotificationState,
        default=NotificationState.PENDING,
    )
    notified_at = models.DateTimeField(null=True, blank=True)
    notification_failed_at = models.DateTimeField(null=True, blank=True)
    customer_access_digest = models.CharField(max_length=64, unique=True, null=True, blank=True)
    customer_access_expires_at = models.DateTimeField(null=True, blank=True)
    customer_notified_at = models.DateTimeField(null=True, blank=True)
    customer_notification_failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    retention_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        permissions = [
            (
                "view_provider_lead_insights",
                "Poate vedea agregatele operaționale ale solicitărilor",
            ),
            (
                "retry_provider_lead_notification",
                "Poate retrimite notificările eșuate ale firmelor",
            ),
            (
                "retry_customer_access_notification",
                "Poate reemite linkurile private pentru notificările eșuate ale clienților",
            ),
        ]
        indexes = [
            models.Index(
                fields=("submission", "status", "created_at"),
                name="provider_lead_queue_idx",
            ),
            models.Index(
                fields=("visitor_session_digest", "created_at"),
                name="provider_lead_session_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "submission"),
                condition=Q(batch__isnull=False),
                name="uniq_provider_per_lead_batch",
            ),
            models.CheckConstraint(
                condition=(~Q(customer_name="") & ~Q(customer_email="") & ~Q(customer_phone="") & ~Q(description="")),
                name="provider_lead_contact_content",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        batch__isnull=True,
                        customer_access_digest__isnull=False,
                        customer_access_expires_at__isnull=False,
                    )
                    | Q(
                        batch__isnull=True,
                        retention_applied_at__isnull=False,
                        customer_access_digest__isnull=True,
                        customer_access_expires_at__isnull=True,
                    )
                    | Q(
                        batch__isnull=False,
                        customer_access_digest__isnull=True,
                        customer_access_expires_at__isnull=True,
                    )
                ),
                name="provider_lead_access_owner",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        notification_state="pending",
                        notified_at__isnull=True,
                        notification_failed_at__isnull=True,
                    )
                    | Q(
                        notification_state="sent",
                        notified_at__isnull=False,
                        notification_failed_at__isnull=True,
                    )
                    | Q(
                        notification_state="failed",
                        notified_at__isnull=True,
                        notification_failed_at__isnull=False,
                    )
                ),
                name="provider_lead_notification_contract",
            ),
        ]


class ProviderLeadCustomerLinkEvent(models.Model):
    """Append-only audit of explicit CRM-to-request associations."""

    lead = models.ForeignKey(
        ProviderLead, on_delete=models.CASCADE, related_name="crm_customer_link_events",
    )
    revision = models.PositiveBigIntegerField()
    previous_customer = models.ForeignKey(
        ProviderCRMCustomer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="previous_provider_lead_links",
    )
    new_customer = models.ForeignKey(
        ProviderCRMCustomer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="new_provider_lead_links",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_lead_customer_link_events",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("lead", "revision"), name="uniq_provider_lead_customer_link_revision",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0), name="provider_lead_customer_link_revision_positive",
            ),
            models.CheckConstraint(
                condition=~Q(previous_customer=models.F("new_customer")),
                name="provider_lead_customer_link_changed",
            ),
        ]


class ProviderVisitProposal(models.Model):
    """One private visit time proposed by a provider and answered by its customer."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("În așteptarea clientului")
        ACCEPTED = "accepted", _("Confirmată")
        DECLINED = "declined", _("Refuzată")
        EXPIRED = "expired", _("Expirată")
        CANCELLED = "cancelled", _("Anulată")

    class CancelledBy(models.TextChoices):
        PROVIDER = "provider", _("Firmă")
        CUSTOMER = "customer", _("Client")

    lead = models.ForeignKey(ProviderLead, on_delete=models.CASCADE, related_name="visit_proposals")
    starts_at = models.DateTimeField()
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.PROPOSED)
    proposed_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=8, choices=CancelledBy, blank=True)

    class Meta:
        ordering = ("-proposed_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("lead",),
                condition=Q(status="proposed"),
                name="one_pending_visit_per_lead",
            ),
            models.UniqueConstraint(
                fields=("lead",),
                condition=Q(status="accepted"),
                name="one_confirmed_visit_per_lead",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="cancelled", cancelled_at__isnull=False)
                    & ~Q(cancelled_by="")
                    | ~Q(status="cancelled")
                    & Q(cancelled_at__isnull=True, cancelled_by="")
                ),
                name="provider_visit_cancellation_contract",
            ),
        ]


class ProviderQuote(models.Model):
    """One immutable commercial offer sent by a provider for a private request."""

    class Status(models.TextChoices):
        SENT = "sent", _("Trimisă")
        ACCEPTED = "accepted", _("Acceptată")
        DECLINED = "declined", _("Refuzată")
        WITHDRAWN = "withdrawn", _("Retrasă")

    lead = models.ForeignKey(ProviderLead, on_delete=models.PROTECT, related_name="quotes")
    revision = models.PositiveBigIntegerField()
    amount_ron = models.DecimalField(max_digits=12, decimal_places=2)
    summary = models.TextField(max_length=2000)
    estimated_duration = models.CharField(max_length=120)
    valid_until = models.DateField()
    status = models.CharField(max_length=16, choices=Status, default=Status.SENT)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_quotes_sent",
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-revision", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("lead", "revision"), name="uniq_provider_quote_revision"
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0) & Q(amount_ron__gt=0) & ~Q(summary="") & ~Q(estimated_duration=""),
                name="provider_quote_content_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="sent", responded_at__isnull=True)
                    | Q(status="withdrawn", responded_at__isnull=False)
                    | Q(status="accepted", responded_at__isnull=False)
                    | Q(status="declined", responded_at__isnull=False)
                ),
                name="provider_quote_response_contract",
            ),
        ]


class ProviderQuoteLine(models.Model):
    """One immutable priced position pinned to a sent commercial offer."""

    quote = models.ForeignKey(
        ProviderQuote, on_delete=models.CASCADE, related_name="lines",
    )
    position = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=240)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=24)
    unit_price_ron = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("quote", "position"), name="uniq_provider_quote_line_position",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0) & Q(quantity__gt=0) & Q(unit_price_ron__gte=0)
                & ~Q(description="") & ~Q(unit=""),
                name="provider_quote_line_content_contract",
            ),
        ]

    @property
    def total_ron(self):
        """Return the frozen commercial total for this position."""

        return self.quantity * self.unit_price_ron


class ProviderWorkOrder(models.Model):
    """Private execution record created from exactly one accepted provider offer."""

    class Status(models.TextChoices):
        AWAITING_SCHEDULE = "awaiting_schedule", _("De programat")
        SCHEDULED = "scheduled", _("Programată")
        COMPLETED = "completed", _("Finalizată")

    lead = models.OneToOneField(
        ProviderLead, on_delete=models.CASCADE, related_name="work_order"
    )
    accepted_quote = models.OneToOneField(
        ProviderQuote, on_delete=models.PROTECT, related_name="work_order"
    )
    status = models.CharField(
        max_length=24, choices=Status, default=Status.AWAITING_SCHEDULE
    )
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    assigned_technician = models.ForeignKey(
        "ProviderTeamMember", on_delete=models.PROTECT, null=True, blank=True,
        related_name="assigned_work_orders",
    )
    assignment_revision = models.PositiveBigIntegerField(default=0)
    revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(
                fields=("status", "scheduled_start", "scheduled_end"),
                name="provider_work_slot_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status="awaiting_schedule", scheduled_start__isnull=True, scheduled_end__isnull=True, completed_at__isnull=True)
                    | Q(status="scheduled", scheduled_start__isnull=False, completed_at__isnull=True)
                    | Q(status="completed", scheduled_start__isnull=False, completed_at__isnull=False)
                ),
                name="provider_work_order_lifecycle",
            ),
            models.CheckConstraint(
                condition=Q(scheduled_end__isnull=True) | Q(scheduled_end__gt=F("scheduled_start")),
                name="provider_work_order_end_after_start",
            ),
            models.CheckConstraint(
                condition=~Q(status="awaiting_schedule") | Q(assigned_technician__isnull=True),
                name="provider_work_awaiting_unassigned",
            ),
            models.CheckConstraint(
                condition=Q(started_at__isnull=True) | Q(status__in=("scheduled", "completed"), started_at__gte=F("scheduled_start")),
                name="provider_work_started_after_schedule",
            ),
            models.CheckConstraint(
                condition=Q(completed_at__isnull=True) | Q(started_at__isnull=True) | Q(completed_at__gte=F("started_at")),
                name="provider_work_completed_after_start",
            ),
        ]


class ProviderWorkOrderEvent(models.Model):
    """Append-only trace of owner scheduling and actor-confirmed execution."""

    work_order = models.ForeignKey(
        ProviderWorkOrder, on_delete=models.CASCADE, related_name="events"
    )
    revision = models.PositiveBigIntegerField()
    previous_status = models.CharField(max_length=24)
    new_status = models.CharField(max_length=24)
    previous_start = models.DateTimeField(null=True, blank=True)
    new_start = models.DateTimeField(null=True, blank=True)
    previous_end = models.DateTimeField(null=True, blank=True)
    new_end = models.DateTimeField(null=True, blank=True)
    previous_started_at = models.DateTimeField(null=True, blank=True)
    new_started_at = models.DateTimeField(null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("work_order", "revision"), name="uniq_work_order_event_revision"
            ),
        ]


class ProviderWorkAssignmentEvent(models.Model):
    """Append-only evidence of who could see an assigned job and when."""

    work_order = models.ForeignKey(
        ProviderWorkOrder, on_delete=models.CASCADE, related_name="assignment_events",
    )
    revision = models.PositiveBigIntegerField()
    previous_technician = models.ForeignKey(
        "ProviderTeamMember", on_delete=models.PROTECT, null=True, blank=True,
        related_name="previous_assignment_events",
    )
    new_technician = models.ForeignKey(
        "ProviderTeamMember", on_delete=models.PROTECT, null=True, blank=True,
        related_name="new_assignment_events",
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("work_order", "revision"), name="uniq_work_assignment_revision",
            ),
        ]


class ProviderInvoiceDraft(models.Model):
    """Provider-private billing preparation, never an issued fiscal document."""

    work_order = models.OneToOneField(
        ProviderWorkOrder, on_delete=models.CASCADE, related_name="invoice_draft"
    )
    amount_ron = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(max_length=2000)
    revision = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_ron__gt=0) & ~Q(description="") & Q(revision__gt=0),
                name="provider_invoice_draft_content_contract",
            ),
        ]


class ProviderReceivable(models.Model):
    """Owner-declared internal amount due; neither an invoice nor a bank claim."""

    work_order = models.OneToOneField(
        ProviderWorkOrder, on_delete=models.CASCADE, related_name="receivable"
    )
    amount_ron = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField()
    reference = models.CharField(max_length=200, blank=True)
    follow_up_on = models.DateField(null=True, blank=True)
    follow_up_revision = models.PositiveBigIntegerField(default=0)
    last_followed_up_at = models.DateTimeField(null=True, blank=True)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_receivables_opened",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_ron__gt=0), name="provider_receivable_positive_amount",
            ),
        ]


class ProviderReceivableFollowUpEvent(models.Model):
    """Append-only journal for one provider's internal collection follow-up."""

    class Action(models.TextChoices):
        SCHEDULED = "scheduled", _("Programat")
        COMPLETED = "completed", _("Marcat realizat")
        CLEARED_AFTER_PAYMENT = "cleared_after_payment", _("Închis după încasare")

    receivable = models.ForeignKey(
        ProviderReceivable, on_delete=models.CASCADE, related_name="follow_up_events",
    )
    revision = models.PositiveBigIntegerField()
    action = models.CharField(max_length=32, choices=Action)
    previous_on = models.DateField(null=True, blank=True)
    new_on = models.DateField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_receivable_follow_up_events",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("receivable", "revision"),
                name="uniq_provider_receivable_follow_up_revision",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0),
                name="provider_receivable_follow_up_positive_revision",
            ),
        ]


class ProviderManualPayment(models.Model):
    """Append-only owner declaration of money received outside the platform."""

    class State(models.TextChoices):
        ACTIVE = "active", _("Activă")
        VOID = "void", _("Anulată")

    receivable = models.ForeignKey(
        ProviderReceivable, on_delete=models.CASCADE, related_name="manual_payments"
    )
    amount_ron = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField()
    reference = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=16, choices=State, default=State.ACTIVE)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_manual_payments_recorded",
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="provider_manual_payments_voided",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_ron__gt=0), name="provider_manual_payment_positive_amount",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="active", voided_by__isnull=True, voided_at__isnull=True, void_reason="")
                    | Q(state="void", voided_by__isnull=False, voided_at__isnull=False) & ~Q(void_reason="")
                ),
                name="provider_manual_payment_state_contract",
            ),
        ]


class ProviderBillingIdentity(models.Model):
    """Private, provider-declared issuer details; not verified for fiscal issuance."""

    profile = models.OneToOneField(
        ProviderProfile, on_delete=models.CASCADE, related_name="billing_identity"
    )
    legal_name = models.CharField(max_length=500)
    fiscal_identifier = models.CharField(max_length=40)
    registration_number = models.CharField(max_length=80)
    registered_address = models.CharField(max_length=500)
    revision = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(legal_name="") & ~Q(fiscal_identifier="")
                    & ~Q(registration_number="") & ~Q(registered_address="")
                    & Q(revision__gt=0)
                ),
                name="provider_billing_identity_content_contract",
            ),
        ]


class ProviderBillingIdentityEvent(models.Model):
    """Append-only snapshot of each provider-declared issuer-data revision."""

    identity = models.ForeignKey(
        ProviderBillingIdentity, on_delete=models.CASCADE, related_name="events"
    )
    revision = models.PositiveBigIntegerField()
    legal_name = models.CharField(max_length=500)
    fiscal_identifier = models.CharField(max_length=40)
    registration_number = models.CharField(max_length=80)
    registered_address = models.CharField(max_length=500)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("identity", "revision"), name="uniq_provider_billing_identity_revision"
            ),
        ]


class ProviderLeadMessage(models.Model):
    """Append-only message visible only to the lead customer and verified provider."""

    class SenderRole(models.TextChoices):
        CUSTOMER = "customer", _("Client")
        PROVIDER = "provider", _("Firmă")

    lead = models.ForeignKey(ProviderLead, on_delete=models.PROTECT, related_name="messages")
    sender_role = models.CharField(max_length=16, choices=SenderRole)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_lead_messages",
        null=True,
        blank=True,
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(sender_role="customer", actor__isnull=True)
                    | Q(sender_role="provider", actor__isnull=False)
                ) & ~Q(body=""),
                name="provider_lead_message_sender_contract",
            )
        ]


class ProviderLeadEvent(models.Model):
    """Append-only status history for a provider-owned customer request."""

    lead = models.ForeignKey(
        ProviderLead,
        on_delete=models.PROTECT,
        related_name="events",
    )
    previous_status = models.CharField(max_length=24, choices=ProviderLead.Status)
    new_status = models.CharField(max_length=24, choices=ProviderLead.Status)
    revision = models.PositiveBigIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_lead_events",
        null=True,
        blank=True,
    )
    actor_role = models.CharField(
        max_length=16,
        choices=ProviderLeadMessage.SenderRole,
        default=ProviderLeadMessage.SenderRole.PROVIDER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("lead", "revision"),
                name="uniq_provider_lead_revision",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0) & ~Q(previous_status=models.F("new_status")),
                name="provider_lead_event_transition",
            ),
            models.CheckConstraint(
                condition=(
                    Q(actor_role="customer", actor__isnull=True)
                    | Q(actor_role="provider", actor__isnull=False)
                ),
                name="provider_lead_event_actor_contract",
            ),
        ]


class ProviderCustomerReview(models.Model):
    """One customer-authored review, published only after an audited decision."""

    class Status(models.TextChoices):
        PENDING = "pending", _("În verificare")
        APPROVED = "approved", _("Publicată")
        REJECTED = "rejected", _("Respinsă")

    lead = models.OneToOneField(
        ProviderLead,
        on_delete=models.PROTECT,
        related_name="customer_review",
    )
    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="customer_reviews",
    )
    rating = models.PositiveSmallIntegerField()
    body = models.TextField(max_length=1200)
    reviewer_display_name = models.CharField(max_length=80)
    consent_policy_version = models.CharField(max_length=20)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provider_customer_reviews_moderated",
    )
    moderation_note = models.TextField(max_length=1200, blank=True)

    class Meta:
        ordering = ("-submitted_at", "-id")
        permissions = [
            ("moderate_customer_review", "Poate modera recenziile clienților")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5) & ~Q(body=""),
                name="customer_review_content_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="pending",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                        moderation_note="",
                    )
                    | Q(
                        status__in=("approved", "rejected"),
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                    )
                    & ~Q(moderation_note="")
                ),
                name="customer_review_state_contract",
            ),
        ]


class ProviderCustomerReviewEvent(models.Model):
    """Append-only moderation decision for one immutable customer review."""

    review = models.OneToOneField(
        ProviderCustomerReview,
        on_delete=models.PROTECT,
        related_name="decision_event",
    )
    decision = models.CharField(
        max_length=16,
        choices=(
            (ProviderCustomerReview.Status.APPROVED, _("Publică")),
            (ProviderCustomerReview.Status.REJECTED, _("Respinge")),
        ),
    )
    internal_note = models.TextField(max_length=1200)
    policy_version = models.CharField(max_length=20)
    acknowledgement = models.CharField(max_length=180)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_customer_review_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(internal_note="")
                    & ~Q(policy_version="")
                    & ~Q(acknowledgement="")
                ),
                name="customer_review_event_contract",
            )
        ]


class ProviderCustomerReviewReply(models.Model):
    """One provider-authored response, published only after an audited decision."""

    class Status(models.TextChoices):
        PENDING = "pending", _("În verificare")
        APPROVED = "approved", _("Publicat")
        REJECTED = "rejected", _("Respins")

    review = models.OneToOneField(
        ProviderCustomerReview,
        on_delete=models.PROTECT,
        related_name="provider_reply",
    )
    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="customer_review_replies",
    )
    body = models.TextField(max_length=1200)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_customer_review_replies",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provider_customer_review_replies_moderated",
    )
    moderation_note = models.TextField(max_length=1200, blank=True)

    class Meta:
        ordering = ("-submitted_at", "-id")
        permissions = [
            (
                "moderate_customer_review_reply",
                "Poate modera răspunsurile furnizorilor la recenzii",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(body=""),
                name="customer_review_reply_content_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="pending",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                        moderation_note="",
                    )
                    | Q(
                        status__in=("approved", "rejected"),
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                    )
                    & ~Q(moderation_note="")
                ),
                name="customer_review_reply_state_contract",
            ),
        ]


class ProviderCustomerReviewReplyEvent(models.Model):
    """Append-only moderation decision for one immutable provider response."""

    reply = models.OneToOneField(
        ProviderCustomerReviewReply,
        on_delete=models.PROTECT,
        related_name="decision_event",
    )
    decision = models.CharField(
        max_length=16,
        choices=(
            (ProviderCustomerReviewReply.Status.APPROVED, _("Publică")),
            (ProviderCustomerReviewReply.Status.REJECTED, _("Respinge")),
        ),
    )
    internal_note = models.TextField(max_length=1200)
    policy_version = models.CharField(max_length=20)
    acknowledgement = models.CharField(max_length=180)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_customer_review_reply_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(internal_note="")
                    & ~Q(policy_version="")
                    & ~Q(acknowledgement="")
                ),
                name="customer_review_reply_event_contract",
            )
        ]


class PublicProviderReport(models.Model):
    """One immutable visitor report pinned to the exact visible profile snapshot."""

    class Reason(models.TextChoices):
        INCORRECT_INFORMATION = "incorrect_information", _("Informații incorecte")
        WRONG_SERVICE = "wrong_service", _("Servicii prezentate greșit")
        UNREACHABLE_CONTACT = "unreachable_contact", _("Date de contact nefuncționale")
        INAPPROPRIATE_PORTFOLIO = "inappropriate_portfolio", _("Portofoliu nepotrivit")
        OTHER = "other", _("Altă problemă")

    submission = models.ForeignKey(
        ProviderPublicationSubmission,
        on_delete=models.PROTECT,
        related_name="public_reports",
    )
    reason = models.CharField(max_length=32, choices=Reason)
    details = models.TextField(max_length=1200)
    reporter_session_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    retention_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        permissions = [
            (
                "view_public_provider_report_insights",
                "Poate vedea sumarul operațional al sesizărilor publice",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "reporter_session_digest"),
                name="uniq_public_report_session_snapshot",
            )
        ]
        indexes = [
            models.Index(
                fields=("reason", "created_at"),
                name="public_report_reason_idx",
            )
        ]


class PublicProviderReportCase(models.Model):
    """Stable lock row holding only the current operational report state."""

    class State(models.TextChoices):
        NEW = "new", "Nouă"
        IN_REVIEW = "in_review", "În analiză"
        CLOSED = "closed", "Închisă"

    class Outcome(models.TextChoices):
        NO_ISSUE_FOUND = "no_issue_found", "Nu s-a confirmat o problemă"
        DUPLICATE = "duplicate", "Sesizare duplicată"
        INSUFFICIENT_INFORMATION = "insufficient_information", "Informații insuficiente"
        SEPARATE_FOLLOW_UP_REQUIRED = (
            "separate_follow_up_required",
            "Necesită o acțiune separată",
        )

    report = models.OneToOneField(
        PublicProviderReport,
        on_delete=models.PROTECT,
        related_name="triage_case",
    )
    state = models.CharField(max_length=16, choices=State, default=State.NEW)
    outcome = models.CharField(max_length=32, choices=Outcome, blank=True)
    revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            (
                "triage_public_provider_report",
                "Poate analiza sesizările despre profiluri publice",
            )
        ]
        indexes = [
            models.Index(fields=("state", "updated_at"), name="report_case_queue_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(state="closed") & ~Q(outcome="")
                    | Q(state__in=("new", "in_review"), outcome="")
                ),
                name="public_report_case_state_contract",
            )
        ]


class PublicProviderReportTriageEvent(models.Model):
    """Append-only audit event for one report-case transition."""

    case = models.ForeignKey(
        PublicProviderReportCase,
        on_delete=models.PROTECT,
        related_name="events",
    )
    previous_state = models.CharField(max_length=16, choices=PublicProviderReportCase.State)
    new_state = models.CharField(max_length=16, choices=PublicProviderReportCase.State)
    outcome = models.CharField(max_length=32, choices=PublicProviderReportCase.Outcome, blank=True)
    revision = models.PositiveBigIntegerField()
    internal_note = models.TextField(max_length=1200)
    policy_version = models.CharField(max_length=24)
    acknowledgement = models.CharField(max_length=160)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="public_provider_report_triage_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("created_at", "new_state", "outcome"),
                name="report_event_window_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("case", "revision"),
                name="uniq_public_report_case_revision",
            ),
            models.CheckConstraint(
                condition=(~Q(internal_note="") & ~Q(policy_version="") & ~Q(acknowledgement="")),
                name="public_report_event_content_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(new_state="closed") & ~Q(outcome="")
                    | Q(new_state="in_review", outcome="")
                ),
                name="public_report_event_state_contract",
            ),
        ]


class ProviderMembership(models.Model):
    """An audited user's access to exactly one provider profile."""

    class State(models.TextChoices):
        INVITED = "invited", "Invitat"
        ACTIVE = "active", "Activ"
        REVOKED = "revoked", "Revocat"

    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_memberships",
    )
    state = models.CharField(max_length=16, choices=State, default=State.INVITED)
    invited_at = models.DateTimeField()
    activated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "user"), name="uniq_provider_profile_user"
            ),
            models.UniqueConstraint(
                fields=("profile",),
                condition=Q(state__in=("invited", "active")),
                name="uniq_current_provider_owner",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="invited",
                        activated_at__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | Q(
                        state="active",
                        activated_at__isnull=False,
                        revoked_at__isnull=True,
                    )
                    | Q(state="revoked", revoked_at__isnull=False)
                ),
                name="provider_membership_state_timestamps",
            ),
        ]


class ProviderTeamMember(models.Model):
    """Technician access is distinct from the sole owner membership."""

    class State(models.TextChoices):
        ACTIVE = "active", _("Activ")
        REVOKED = "revoked", _("Revocat")

    profile = models.ForeignKey(
        ProviderProfile, on_delete=models.PROTECT, related_name="team_members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_team_memberships",
    )
    state = models.CharField(max_length=16, choices=State, default=State.ACTIVE)
    activated_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="revoked_provider_team_memberships",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "user"), name="uniq_provider_team_profile_user",
            ),
            models.UniqueConstraint(
                fields=("user",), condition=Q(state="active"),
                name="uniq_active_provider_team_user",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="active", revoked_at__isnull=True, revoked_by__isnull=True)
                    | Q(state="revoked", revoked_at__isnull=False, revoked_by__isnull=False)
                ),
                name="provider_team_state_timestamps",
            ),
        ]


class ProviderTeamInvitation(models.Model):
    """One short-lived, revocable mailbox proof for joining a provider team."""

    profile = models.ForeignKey(
        ProviderProfile, on_delete=models.PROTECT, related_name="team_invitations",
    )
    normalized_email = models.EmailField(max_length=254)
    token_digest = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="provider_team_invitations_sent",
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="provider_team_invitations_accepted",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="provider_team_invitations_revoked",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "normalized_email"),
                condition=Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="uniq_pending_provider_team_invite",
            ),
            models.CheckConstraint(
                condition=(
                    Q(accepted_at__isnull=True, accepted_by__isnull=True, revoked_at__isnull=True, revoked_by__isnull=True)
                    | Q(accepted_at__isnull=False, accepted_by__isnull=False, revoked_at__isnull=True, revoked_by__isnull=True)
                    | Q(accepted_at__isnull=True, accepted_by__isnull=True, revoked_at__isnull=False, revoked_by__isnull=False)
                ),
                name="provider_team_invite_terminal_state",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="provider_team_invite_future_expiry",
            ),
        ]


class DataSubjectRequest(models.Model):
    """Immutable intake plus the current state of one personal-data rights request."""

    class Kind(models.TextChoices):
        ACCESS = "access", "Acces"
        RECTIFICATION = "rectification", "Rectificare"
        ERASURE = "erasure", "Ștergere"
        RESTRICTION = "restriction", "Restricționare"
        PORTABILITY = "portability", "Portabilitate"
        OBJECTION = "objection", "Opoziție"
        OTHER = "other", "Alt drept privind datele"

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        POST = "post", "Poștă"
        OTHER = "other", "Alt canal"

    class Status(models.TextChoices):
        RECEIVED = "received", "Primită"
        IDENTITY_PENDING = "identity_pending", "Așteaptă confirmarea identității"
        IN_REVIEW = "in_review", "În analiză"
        FULFILLED = "fulfilled", "Soluționată"
        REFUSED = "refused", "Refuzată motivat"

    request_kind = models.CharField(max_length=24, choices=Kind)
    channel = models.CharField(max_length=16, choices=Channel)
    requester_name = models.CharField(max_length=160)
    contact_email = models.EmailField(max_length=254)
    details = models.TextField(max_length=1200)
    status = models.CharField(max_length=24, choices=Status, default=Status.RECEIVED)
    revision = models.PositiveBigIntegerField(default=0)
    received_at = models.DateTimeField()
    due_at = models.DateTimeField()
    extended_due_at = models.DateTimeField(null=True, blank=True)
    extension_notified_at = models.DateTimeField(null=True, blank=True)
    identity_verified_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_data_subject_requests",
    )
    retention_applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "cerere privind datele personale"
        verbose_name_plural = "cereri privind datele personale"
        permissions = [
            (
                "process_data_subject_request",
                "Poate procesa cereri privind datele personale",
            )
        ]
        ordering = ("status", "due_at", "id")
        indexes = [
            models.Index(fields=("status", "due_at"), name="data_request_due_idx"),
            models.Index(fields=("closed_at",), name="data_request_closed_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(due_at__gt=models.F("received_at")),
                name="data_request_due_after_received",
            ),
            models.CheckConstraint(
                condition=(
                    Q(extended_due_at__isnull=True, extension_notified_at__isnull=True)
                    | (
                        Q(
                            extended_due_at__isnull=False,
                            extension_notified_at__isnull=False,
                        )
                        & Q(extended_due_at__gt=models.F("due_at"))
                    )
                ),
                name="data_request_extension_contract",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=("received", "identity_pending"),
                        identity_verified_at__isnull=True,
                        closed_at__isnull=True,
                    )
                    | Q(
                        status="in_review",
                        identity_verified_at__isnull=False,
                        closed_at__isnull=True,
                    )
                    | Q(
                        status__in=("fulfilled", "refused"),
                        identity_verified_at__isnull=False,
                        closed_at__isnull=False,
                    )
                ),
                name="data_request_status_timestamps",
            ),
        ]

    @property
    def effective_due_at(self):
        """Expose the notified extension when one exists, otherwise the initial due date."""

        return self.extended_due_at or self.due_at


class DataSubjectRequestEvent(models.Model):
    """Append-only evidence for one request workflow or export action."""

    class Action(models.TextChoices):
        STATUS_TRANSITION = "status_transition", "Schimbare de stare"
        DEADLINE_EXTENDED = "deadline_extended", "Prelungire termen"
        EXPORT_GENERATED = "export_generated", "Pachet de date generat"

    request = models.ForeignKey(
        DataSubjectRequest,
        on_delete=models.PROTECT,
        related_name="events",
    )
    action = models.CharField(max_length=24, choices=Action)
    previous_status = models.CharField(max_length=24, choices=DataSubjectRequest.Status)
    new_status = models.CharField(max_length=24, choices=DataSubjectRequest.Status)
    revision = models.PositiveBigIntegerField()
    internal_note = models.TextField(max_length=1200)
    policy_version = models.CharField(max_length=24)
    acknowledgement = models.CharField(max_length=180)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="data_subject_request_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "eveniment al cererii privind datele"
        verbose_name_plural = "evenimente ale cererilor privind datele"
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("request", "revision"),
                name="uniq_data_request_revision",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0),
                name="data_request_event_positive_revision",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        action="status_transition",
                        previous_status="received",
                        new_status__in=("identity_pending", "in_review"),
                    )
                    | Q(
                        action="status_transition",
                        previous_status="identity_pending",
                        new_status="in_review",
                    )
                    | Q(
                        action="status_transition",
                        previous_status="in_review",
                        new_status__in=("fulfilled", "refused"),
                    )
                    | Q(
                        action="deadline_extended",
                        previous_status=models.F("new_status"),
                    )
                    | Q(
                        action="export_generated",
                        previous_status="in_review",
                        new_status="in_review",
                    )
                ),
                name="data_request_event_transition_contract",
            ),
        ]


class ProviderPasswordResetThrottle(models.Model):
    """Shared, pseudonymous send budget for one reset requester and account address."""

    key_digest = models.CharField(max_length=64, unique=True)
    window_started_at = models.DateTimeField()
    send_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("window_started_at",),
                name="provider_reset_window_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(send_count__lte=3),
                name="provider_reset_send_count_lte_3",
            )
        ]


class AccountLoginThrottle(models.Model):
    """Shared, pseudonymous failed-login budget for one normalized account key."""

    key_digest = models.CharField(max_length=64, unique=True)
    window_started_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("window_started_at",),
                name="account_login_window_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(attempt_count__lte=5),
                name="account_login_attempt_count_lte_5",
            )
        ]


class ProviderAccountInvitation(models.Model):
    """One rotating, hashed activation credential for a provider membership."""

    class DeliveryState(models.TextChoices):
        PENDING = "pending", "În așteptare"
        SENT = "sent", "Trimisă"
        FAILED = "failed", "Eșuată"

    membership = models.OneToOneField(
        ProviderMembership,
        on_delete=models.PROTECT,
        related_name="invitation",
    )
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    delivery_state = models.CharField(
        max_length=16, choices=DeliveryState, default=DeliveryState.PENDING
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(accepted_at__isnull=True)
                    | Q(accepted_at__isnull=False, delivery_state="sent")
                ),
                name="provider_invitation_acceptance_state",
            )
        ]


class ImportQuarantine(models.Model):
    """A privacy-minimized, deterministic trace of an import rejection."""

    import_run = models.ForeignKey(
        ImportRun, on_delete=models.CASCADE, related_name="quarantine_records"
    )
    resource_kind = models.CharField(max_length=32)
    reason = models.CharField(max_length=64)
    source_row_number = models.PositiveBigIntegerField(null=True, blank=True)
    record_key_hash = models.CharField(max_length=64)
    payload_fingerprint = models.CharField(max_length=64, blank=True)
    diagnostic = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("import_run", "resource_kind", "reason", "record_key_hash"),
                name="uniq_quarantine_record",
            )
        ]


class PublicationApproval(models.Model):
    """A revocable legal/publication decision for exactly one imported run."""

    class State(models.TextChoices):
        APPROVED = "approved", "Aprobată"
        REVOKED = "revoked", "Revocată"

    import_run = models.ForeignKey(
        ImportRun, on_delete=models.PROTECT, related_name="publication_approvals"
    )
    approval_version = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=16, choices=State, default=State.APPROVED)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="catalogue_publication_approvals",
    )
    approved_at = models.DateTimeField()
    review_reference = models.CharField(max_length=500)
    review_due_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="catalogue_publication_revocations",
    )

    class Meta:
        permissions = [
            (
                "approve_catalogue_publication",
                "Can record or revoke catalogue publication approval",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("import_run", "approval_version"),
                name="uniq_run_publication_approval_version",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="approved", revoked_at__isnull=True, revoked_by__isnull=True)
                    | Q(
                        state="revoked",
                        revoked_at__isnull=False,
                        revoked_by__isnull=False,
                    )
                ),
                name="publication_approval_revocation_contract",
            )
        ]


class CatalogueScope(models.Model):
    """The single lockable catalogue pointer for one provider and county."""

    class Visibility(models.TextChoices):
        OFF = "off", "Oprit"
        INTERNAL_PREVIEW = "internal_preview", "Previzualizare internă"
        PUBLIC = "public", "Public"

    provider = models.CharField(max_length=40)
    county = models.CharField(max_length=80)
    current_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="active_catalogue_scopes",
    )
    current_approval = models.ForeignKey(
        PublicationApproval,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="active_catalogue_scopes",
    )
    visibility = models.CharField(
        max_length=24, choices=Visibility, default=Visibility.OFF
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "county"), name="uniq_provider_county_scope"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        visibility="off",
                        current_run__isnull=True,
                        current_approval__isnull=True,
                    )
                    | Q(
                        visibility="internal_preview",
                        current_run__isnull=False,
                        current_approval__isnull=True,
                    )
                    | Q(
                        visibility="public",
                        current_run__isnull=False,
                        current_approval__isnull=False,
                    )
                ),
                name="catalogue_scope_visibility_contract",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider} — {self.county} — {self.visibility}"


class CatalogueActivationEvent(models.Model):
    """Append-only audit event for a catalogue pointer transition."""

    class Action(models.TextChoices):
        ACTIVATE = "activate", "Activare"
        DEACTIVATE = "deactivate", "Dezactivare"

    scope = models.ForeignKey(
        CatalogueScope, on_delete=models.PROTECT, related_name="activation_events"
    )
    action = models.CharField(max_length=16, choices=Action)
    previous_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="catalogue_events_as_previous",
    )
    new_run = models.ForeignKey(
        ImportRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="catalogue_events_as_new",
    )
    approval = models.ForeignKey(
        PublicationApproval,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activation_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="catalogue_activation_events",
    )
    previous_visibility = models.CharField(max_length=24)
    new_visibility = models.CharField(max_length=24)
    acknowledgement = models.CharField(max_length=80)
    audited_counters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
