"""Controlled provider publication, private portfolio processing, and public projection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import uuid
import warnings

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext
from PIL import Image, ImageOps, UnidentifiedImageError

from .catalog import CATEGORIES
from .catalogue_activation import publication_approval_is_valid
from .locations import SIRUTA_CATALOGUE_VERSION, locality_name, siruta_catalogue_sha256
from .models import (
    CatalogueScope,
    ImportRun,
    ProviderMembership,
    ProviderPortfolioAsset,
    ProviderPortfolioItem,
    ProviderProfile,
    ProviderPublicationCoverage,
    ProviderPublicationEvent,
    ProviderPublicationPortfolioItem,
    ProviderPublicationScope,
    ProviderPublicationService,
    ProviderPublicationSubmission,
    ProviderServiceAreaDraft,
    ProviderServiceAreaSubmission,
    ProviderSubscription,
    RegisteredBusinessSnapshot,
    SourceSnapshot,
)
from .provider_offerings import provider_authorization
from .provider_subscriptions import require_active_provider_subscription


MAX_PORTFOLIO_ITEMS = 8
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MAX_PUBLIC_EDGE = 2000
SUBMISSION_SCHEMA_VERSION = 3
REVIEW_POLICY_VERSION = "2026-08-26-v1"
REVIEW_ACKNOWLEDGEMENT = "PROVIDER_PUBLICATION_CONTENT_AND_SOURCE_REVIEWED"
UNPUBLISH_NOTE = "Retragere solicitată de proprietarul profilului."
CATEGORY_LABELS = {slug: label for slug, label, _description in CATEGORIES}


@dataclass(frozen=True)
class PublishedPortfolioImage:
    """One safe image reference from an immutable publication snapshot."""

    opaque_id: object
    caption: str
    width: int
    height: int


@dataclass(frozen=True)
class ProviderPublicationReadiness:
    """Current private prerequisites for one whole-profile publication snapshot."""

    profile_content: bool
    public_contact: bool
    service_area_approved: bool
    portfolio: bool

    @property
    def complete(self) -> bool:
        return all(
            (
                self.profile_content,
                self.public_contact,
                self.service_area_approved,
                self.portfolio,
            )
        )


@dataclass(frozen=True)
class PublishedServiceArea:
    """One public service area with separately renderable locality facts."""

    county: str
    locality: str
    siruta_code: str


@dataclass(frozen=True)
class PublishedProvider:
    """Whitelisted provider publication safe for search and profile templates."""

    public_id: object
    business_id: int
    display_name: str
    legal_name: str
    description: str
    public_phone: str
    public_email: str
    website: str
    public_address: str
    availability: str
    availability_label: str
    contact_preference: str
    contact_preference_label: str
    category_slugs: tuple[str, ...]
    category_labels: tuple[str, ...]
    coverage_areas: tuple[PublishedServiceArea, ...]
    searched_locality_label: str
    searched_locality_code: str
    portfolio: tuple[PublishedPortfolioImage, ...]
    preview: bool

    @property
    def initials(self) -> str:
        words = [word for word in self.display_name.split() if word]
        return "".join(word[0] for word in words[:2]).upper() or "F"


def _lock_owner_profile(user) -> ProviderProfile:
    """Lock the caller's only active provider membership and profile."""

    if not user.is_authenticated or not user.is_active:
        raise PermissionError(_("Contul furnizorului nu este activ."))
    memberships = list(
        ProviderMembership.objects.select_for_update()
        .filter(
            user=user,
            state=ProviderMembership.State.ACTIVE,
            profile__state=ProviderProfile.State.DRAFT,
        )[:2]
    )
    if len(memberships) != 1:
        raise PermissionError(_("Accesul la profil nu mai este activ."))
    return ProviderProfile.objects.select_for_update().select_related("business").get(
        pk=memberships[0].profile_id
    )


def _profile_values(profile: ProviderProfile) -> dict[str, str]:
    return {
        "display_name": " ".join(profile.display_name.split()),
        "description": " ".join(profile.description.split()),
        "public_address": " ".join(profile.public_address.split()),
        "public_phone": " ".join(profile.public_phone.split()),
        "public_email": profile.public_email.strip().lower(),
        "website": profile.website.strip(),
        "availability": profile.availability,
        "contact_preference": profile.contact_preference,
    }


def provider_publication_readiness(
    *, profile: ProviderProfile, service_submission, portfolio
) -> ProviderPublicationReadiness:
    """Project the exact mutable prerequisites used by publication submission."""

    values = _profile_values(profile)
    portfolio_items = tuple(portfolio)
    return ProviderPublicationReadiness(
        profile_content=(
            len(values["display_name"]) >= 2 and len(values["description"]) >= 60
        ),
        public_contact=any(
            (values["public_phone"], values["public_email"], values["website"])
        ),
        service_area_approved=(
            service_submission is not None
            and service_submission.decision
            == ProviderServiceAreaSubmission.Decision.APPROVED
            and service_submission.superseded_at is None
            and service_submission.draft.profile_id == profile.pk
        ),
        portfolio=(
            0 < len(portfolio_items) <= MAX_PORTFOLIO_ITEMS
            and all(
                item.profile_id == profile.pk
                and item.asset.profile_id == profile.pk
                and item.asset.state == ProviderPortfolioAsset.State.ACTIVE
                for item in portfolio_items
            )
        ),
    )


def _current_submission(profile: ProviderProfile, *, lock: bool = False):
    query = ProviderPublicationSubmission.objects.filter(
        profile=profile, superseded_at__isnull=True
    )
    return (query.select_for_update() if lock else query).first()


def _unpublish_locked(
    *, profile: ProviderProfile, actor, note: str, superseding_version: int | None = None
) -> bool:
    """Turn off one locked profile scope and preserve an append-only pointer event."""

    scope, _created = ProviderPublicationScope.objects.select_for_update().get_or_create(
        profile=profile
    )
    current = scope.current_submission
    if superseding_version is not None:
        submission = _current_submission(profile, lock=True)
        if submission:
            next_version = max(superseding_version, submission.version + 1)
            submission.superseded_at = timezone.now()
            submission.superseded_by = actor
            submission.superseded_by_version = next_version
            submission.save(
                update_fields=(
                    "superseded_at",
                    "superseded_by",
                    "superseded_by_version",
                )
            )
    if scope.visibility == ProviderPublicationScope.Visibility.OFF:
        return False
    ProviderPublicationEvent.objects.create(
        scope=scope,
        previous_submission=current,
        action=ProviderPublicationEvent.Action.UNPUBLISH,
        visibility=ProviderPublicationScope.Visibility.OFF,
        actor=actor,
        note=note,
    )
    scope.visibility = ProviderPublicationScope.Visibility.OFF
    scope.current_submission = None
    scope.activated_at = None
    scope.save(update_fields=("visibility", "current_submission", "activated_at"))
    return True


@transaction.atomic
def save_provider_profile_for_owner(*, user, values: dict[str, str]) -> tuple[ProviderProfile, bool]:
    """Replace provider-owned text and invalidate any visible snapshot on real change."""

    profile = _lock_owner_profile(user)
    normalized = {
        "display_name": " ".join(values.get("display_name", "").split()),
        "description": " ".join(values.get("description", "").split()),
        "public_address": " ".join(values.get("public_address", "").split()),
        "public_phone": " ".join(values.get("public_phone", "").split()),
        "public_email": values.get("public_email", "").strip().lower(),
        "website": values.get("website", "").strip(),
        "availability": values.get("availability", profile.availability),
        "contact_preference": values.get(
            "contact_preference", profile.contact_preference
        ),
    }
    if normalized["availability"] not in ProviderProfile.Availability.values:
        raise ValueError(_("Disponibilitatea declarată nu este validă."))
    if normalized["contact_preference"] not in ProviderProfile.ContactPreference.values:
        raise ValueError(_("Metoda de contact preferată nu este validă."))
    required_contact = {
        ProviderProfile.ContactPreference.PHONE: "public_phone",
        ProviderProfile.ContactPreference.EMAIL: "public_email",
        ProviderProfile.ContactPreference.WEBSITE: "website",
    }.get(normalized["contact_preference"])
    if required_contact and not normalized[required_contact]:
        raise ValueError(_("Metoda de contact preferată trebuie completată în profil."))
    if normalized == _profile_values(profile):
        return profile, False
    next_revision = profile.public_content_revision + 1
    _unpublish_locked(
        profile=profile,
        actor=user,
        note="Conținutul profilului a fost modificat.",
        superseding_version=next_revision,
    )
    for field, value in normalized.items():
        setattr(profile, field, value)
    profile.public_content_revision = next_revision
    profile.save(update_fields=(*normalized.keys(), "public_content_revision", "updated_at"))
    return profile, True


def _processed_image(upload) -> tuple[bytes, int, int]:
    """Decode and re-encode one bounded image, removing EXIF and original metadata."""

    if upload.size > MAX_UPLOAD_BYTES:
        raise ValueError(_("Imaginea depășește limita de 10 MB."))
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(_("Imaginea depășește limita de 10 MB."))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(BytesIO(raw))
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError(_("Sunt acceptate numai imagini JPEG, PNG sau WebP."))
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(_("Imaginea are prea mulți pixeli."))
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError(_("Fișierul nu este o imagine validă.")) from error
    image.thumbnail((MAX_PUBLIC_EDGE, MAX_PUBLIC_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="WEBP", quality=86, method=6, exif=b"")
    return output.getvalue(), image.width, image.height


@transaction.atomic
def add_portfolio_images_for_owner(
    *, user, uploads, caption: str
) -> tuple[ProviderPortfolioItem, ...]:
    """Validate and append one atomic batch of sanitized private portfolio images."""

    uploads = tuple(uploads)
    if not uploads:
        raise ValueError(_("Selectează cel puțin o fotografie."))
    profile = _lock_owner_profile(user)
    items = list(
        ProviderPortfolioItem.objects.select_for_update()
        .filter(profile=profile)
        .order_by("position")
    )
    if len(items) + len(uploads) > MAX_PORTFOLIO_ITEMS:
        raise ValueError(
            ngettext(
                "Portofoliul poate conține maximum %(count)s imagine.",
                "Portofoliul poate conține maximum %(count)s imagini.",
                MAX_PORTFOLIO_ITEMS,
            )
            % {"count": MAX_PORTFOLIO_ITEMS}
        )
    # No database or storage mutation occurs until every file in the batch is safe.
    processed = tuple(_processed_image(upload) for upload in uploads)
    next_revision = profile.public_content_revision + 1
    _unpublish_locked(
        profile=profile,
        actor=user,
        note="Portofoliul a fost modificat.",
        superseding_version=next_revision,
    )
    created_items = []
    stored_files = []
    try:
        for offset, (rendered, width, height) in enumerate(processed, start=1):
            asset = ProviderPortfolioAsset(
                profile=profile,
                sha256=hashlib.sha256(rendered).hexdigest(),
                mime_type="image/webp",
                width=width,
                height=height,
                created_by=user,
            )
            asset.image.save(
                f"{uuid.uuid4().hex}.webp", ContentFile(rendered), save=False
            )
            stored_files.append((asset.image.storage, asset.image.name))
            asset.save()
            created_items.append(
                ProviderPortfolioItem.objects.create(
                    profile=profile,
                    asset=asset,
                    caption=" ".join(caption.split())[:240],
                    position=len(items) + offset,
                )
            )
        profile.public_content_revision = next_revision
        profile.save(update_fields=("public_content_revision", "updated_at"))
    except Exception:
        # Database rollback cannot undo storage writes from earlier batch members.
        for storage, name in stored_files:
            storage.delete(name)
        raise
    return tuple(created_items)


def add_portfolio_image_for_owner(*, user, upload, caption: str) -> ProviderPortfolioItem:
    """Append one image through the same atomic contract used by batch uploads."""

    return add_portfolio_images_for_owner(
        user=user, uploads=(upload,), caption=caption
    )[0]


@transaction.atomic
def remove_portfolio_item_for_owner(*, user, item_id: int) -> bool:
    """Remove one private placement without deleting immutable image history."""

    profile = _lock_owner_profile(user)
    items = list(
        ProviderPortfolioItem.objects.select_for_update()
        .filter(profile=profile)
        .order_by("position", "id")
    )
    target = next((item for item in items if item.pk == item_id), None)
    if target is None:
        raise ValueError(_("Imaginea nu aparține acestui profil."))
    next_revision = profile.public_content_revision + 1
    _unpublish_locked(
        profile=profile,
        actor=user,
        note="Portofoliul a fost modificat.",
        superseding_version=next_revision,
    )
    target.delete()
    for position, item in enumerate((item for item in items if item.pk != item_id), 1):
        if item.position != position:
            ProviderPortfolioItem.objects.filter(pk=item.pk).update(position=position)
    profile.public_content_revision = next_revision
    profile.save(update_fields=("public_content_revision", "updated_at"))
    return True


def _snapshot_contract(*, profile, service_submission, portfolio) -> tuple[dict, str]:
    """Build the canonical publication payload and its SHA-256 digest."""

    values = _profile_values(profile)
    payload = {
        "schema_version": SUBMISSION_SCHEMA_VERSION,
        "profile_id": profile.pk,
        "business_id": profile.business_id,
        "profile_content_revision": profile.public_content_revision,
        "profile": values,
        "service_area_submission_id": service_submission.pk,
        "service_revision": service_submission.revision,
        "services": list(service_submission.services_snapshot),
        "coverage": list(service_submission.coverage_snapshot),
        "authorization_run_id": service_submission.authorization_run_id,
        "catalogue_run_id": service_submission.catalogue_run_id,
        "siruta_catalogue_version": service_submission.siruta_catalogue_version,
        "siruta_catalogue_sha256": service_submission.siruta_catalogue_sha256,
        "portfolio": [
            {
                "asset_id": item.asset_id,
                "position": item.position,
                "caption": item.caption,
                "sha256": item.asset.sha256,
            }
            for item in portfolio
        ],
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _validate_publication_content(*, profile, service_submission, portfolio) -> None:
    readiness = provider_publication_readiness(
        profile=profile,
        service_submission=service_submission,
        portfolio=portfolio,
    )
    if not readiness.profile_content:
        raise ValueError(_("Completează numele public și o descriere de minimum 60 de caractere."))
    if not readiness.public_contact:
        raise ValueError(_("Adaugă cel puțin o metodă publică de contact."))
    if not portfolio:
        raise ValueError(_("Adaugă cel puțin o imagine în portofoliu."))
    if len(portfolio) > MAX_PORTFOLIO_ITEMS:
        raise ValueError(_("Portofoliul depășește limita permisă."))
    if any(
        item.profile_id != profile.pk
        or item.asset.profile_id != profile.pk
        or item.asset.state != ProviderPortfolioAsset.State.ACTIVE
        for item in portfolio
    ):
        raise ValueError(_("Portofoliul conține un fișier indisponibil."))
    if not readiness.service_area_approved:
        raise ValueError(_("Serviciile și acoperirea trebuie aprobate înainte de publicare."))


@transaction.atomic
def submit_provider_publication_for_review(*, user) -> tuple[ProviderPublicationSubmission, bool]:
    """Create one immutable profile, service-area, and portfolio publication snapshot."""

    profile = _lock_owner_profile(user)
    authorization = provider_authorization(profile, lock_scope=True)
    draft = ProviderServiceAreaDraft.objects.select_for_update().get(profile=profile)
    service_submission = (
        ProviderServiceAreaSubmission.objects.select_for_update()
        .select_related("draft")
        .get(draft=draft, superseded_at__isnull=True)
    )
    scope, _created = ProviderPublicationScope.objects.select_for_update().get_or_create(
        profile=profile
    )
    current = _current_submission(profile, lock=True)
    portfolio = list(
        ProviderPortfolioItem.objects.select_for_update()
        .select_related("asset")
        .filter(profile=profile)
        .order_by("position", "id")
    )
    _validate_publication_content(
        profile=profile, service_submission=service_submission, portfolio=portfolio
    )
    if (
        service_submission.authorization_run_id != authorization.run.pk
        or service_submission.catalogue_run_id != authorization.catalogue_run.pk
        or service_submission.siruta_catalogue_version != SIRUTA_CATALOGUE_VERSION
        or service_submission.siruta_catalogue_sha256 != siruta_catalogue_sha256()
    ):
        raise ValueError(_("Sursele ONRC sau SIRUTA s-au actualizat; retrimite declarația."))
    payload, contract_hash = _snapshot_contract(
        profile=profile,
        service_submission=service_submission,
        portfolio=portfolio,
    )
    if current:
        if (
            current.decision == ProviderPublicationSubmission.Decision.PENDING
            and current.contract_sha256 == contract_hash
        ):
            return current, False
        raise ValueError(
            _(
                "Versiunea curentă a fost deja trimisă sau decisă; modifică profilul "
                "înainte de retrimitere."
            )
        )
    version = (
        ProviderPublicationSubmission.objects.filter(profile=profile)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
        or 0
    ) + 1
    values = payload["profile"]
    submission = ProviderPublicationSubmission.objects.create(
        profile=profile,
        version=version,
        snapshot_schema_version=SUBMISSION_SCHEMA_VERSION,
        profile_content_revision=profile.public_content_revision,
        display_name=values["display_name"],
        description=values["description"],
        public_address=values["public_address"],
        public_phone=values["public_phone"],
        public_email=values["public_email"],
        website=values["website"],
        availability=values["availability"],
        contact_preference=values["contact_preference"],
        service_area_submission=service_submission,
        authorization_run=service_submission.authorization_run,
        catalogue_run=service_submission.catalogue_run,
        siruta_catalogue_version=service_submission.siruta_catalogue_version,
        siruta_catalogue_sha256=service_submission.siruta_catalogue_sha256,
        contract_sha256=contract_hash,
        submitted_by=user,
    )
    ProviderPublicationService.objects.bulk_create(
        ProviderPublicationService(submission=submission, category=category)
        for category in service_submission.services_snapshot
    )
    ProviderPublicationCoverage.objects.bulk_create(
        ProviderPublicationCoverage(submission=submission, county=county, siruta_code=code)
        for county, code in service_submission.coverage_snapshot
    )
    ProviderPublicationPortfolioItem.objects.bulk_create(
        ProviderPublicationPortfolioItem(
            submission=submission,
            asset=item.asset,
            position=item.position,
            caption=item.caption,
            asset_sha256=item.asset.sha256,
        )
        for item in portfolio
    )
    return submission, True


def _recalculate_submission_hash(submission: ProviderPublicationSubmission) -> str:
    profile_payload = {
        "display_name": submission.display_name,
        "description": submission.description,
        "public_phone": submission.public_phone,
        "public_email": submission.public_email,
        "website": submission.website,
    }
    if submission.snapshot_schema_version >= 2:
        profile_payload.update(
            availability=submission.availability,
            contact_preference=submission.contact_preference,
        )
    if submission.snapshot_schema_version >= 3:
        profile_payload["public_address"] = submission.public_address
    payload = {
        "schema_version": submission.snapshot_schema_version,
        "profile_id": submission.profile_id,
        "business_id": submission.profile.business_id,
        "profile_content_revision": submission.profile_content_revision,
        "profile": profile_payload,
        "service_area_submission_id": submission.service_area_submission_id,
        "service_revision": submission.service_area_submission.revision,
        "services": list(submission.services.order_by("category").values_list("category", flat=True)),
        "coverage": [
            list(pair)
            for pair in submission.coverage.order_by("county", "siruta_code").values_list(
                "county", "siruta_code"
            )
        ],
        "authorization_run_id": submission.authorization_run_id,
        "catalogue_run_id": submission.catalogue_run_id,
        "siruta_catalogue_version": submission.siruta_catalogue_version,
        "siruta_catalogue_sha256": submission.siruta_catalogue_sha256,
        "portfolio": [
            {
                "asset_id": item.asset_id,
                "position": item.position,
                "caption": item.caption,
                "sha256": item.asset_sha256,
            }
            for item in submission.portfolio_items.order_by("position", "id")
        ],
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def publication_submission_contract_is_valid(
    submission: ProviderPublicationSubmission,
) -> bool:
    """Verify that an immutable publication snapshot still matches its contract hash."""

    return submission.contract_sha256 == _recalculate_submission_hash(submission)


def _require_reviewer(reviewer, *, publish: bool) -> None:
    permission = "services.publish_provider_profile" if publish else "services.review_provider_publication"
    if not reviewer.is_active or not reviewer.is_staff or not reviewer.has_perm(permission):
        raise PermissionError("Nu ai permisiunea necesară pentru această decizie.")


@transaction.atomic
def review_provider_publication(
    *,
    submission_id: int,
    reviewer,
    decision: str,
    visibility: str,
    internal_note: str,
    provider_feedback: str,
    acknowledgement: str,
) -> tuple[ProviderPublicationSubmission, bool]:
    """Review and optionally activate exactly one immutable provider snapshot."""

    approve = decision == ProviderPublicationSubmission.Decision.APPROVED
    _require_reviewer(reviewer, publish=approve)
    if approve and not reviewer.has_perm("services.review_provider_publication"):
        raise PermissionError("Aprobarea cere și permisiunea de verificare a profilului.")
    if acknowledgement != REVIEW_ACKNOWLEDGEMENT:
        raise ValueError("Confirmarea reviziei de publicare lipsește.")
    if decision not in {
        ProviderPublicationSubmission.Decision.APPROVED,
        ProviderPublicationSubmission.Decision.CHANGES_REQUIRED,
    }:
        raise ValueError("Decizia nu este validă.")
    note = " ".join(internal_note.split())
    feedback = " ".join(provider_feedback.split())
    if len(note) < 8:
        raise ValueError("Nota internă trebuie să documenteze decizia.")
    if decision == ProviderPublicationSubmission.Decision.CHANGES_REQUIRED and len(feedback) < 8:
        raise ValueError("Explică furnizorului ce trebuie modificat.")
    if visibility not in {
        ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
        ProviderPublicationScope.Visibility.PUBLIC,
    }:
        raise ValueError("Vizibilitatea solicitată nu este validă.")

    reference = ProviderPublicationSubmission.objects.select_related(
        "profile", "catalogue_run"
    ).get(pk=submission_id)
    profile = ProviderProfile.objects.select_for_update().select_related("business").get(
        pk=reference.profile_id
    )
    # Lock only the stable scope row. PostgreSQL rejects FOR UPDATE when a
    # nullable current_approval outer join is included in the locked query.
    source_scope = CatalogueScope.objects.select_for_update().get(
        provider="ONRC", county=reference.catalogue_run.county
    )
    draft = ProviderServiceAreaDraft.objects.select_for_update().get(profile=profile)
    service_submission = ProviderServiceAreaSubmission.objects.select_for_update().get(
        pk=reference.service_area_submission_id
    )
    publication_scope, _created = ProviderPublicationScope.objects.select_for_update().get_or_create(
        profile=profile
    )
    submission = ProviderPublicationSubmission.objects.select_for_update().select_related(
        "profile", "service_area_submission"
    ).get(pk=submission_id)
    assets = list(
        ProviderPortfolioAsset.objects.select_for_update()
        .filter(publication_items__submission=submission)
        .order_by("pk")
    )

    if reviewer.pk == submission.submitted_by_id or ProviderMembership.objects.filter(
        profile=profile, user=reviewer
    ).exclude(state=ProviderMembership.State.REVOKED).exists():
        raise ValueError("Evaluatorul nu își poate publica propriul profil.")
    if submission.superseded_at is not None:
        raise ValueError("Depunerea a fost înlocuită.")
    if submission.decision != ProviderPublicationSubmission.Decision.PENDING:
        raise ValueError("Depunerea are deja o decizie finală.")
    if profile.state != ProviderProfile.State.DRAFT or not ProviderMembership.objects.filter(
        profile=profile, state=ProviderMembership.State.ACTIVE, user__is_active=True
    ).exists():
        raise ValueError("Profilul nu mai are un proprietar activ.")
    if submission.contract_sha256 != _recalculate_submission_hash(submission):
        raise ValueError("Snapshotul publicabil nu mai este intact.")

    if approve:
        # The profile row is already locked, so entitlement changes use the same
        # profile -> subscription lock order and cannot race this approval.
        require_active_provider_subscription(profile, lock=True)
        if (
            profile.public_content_revision != submission.profile_content_revision
            or service_submission.decision != ProviderServiceAreaSubmission.Decision.APPROVED
            or service_submission.superseded_at is not None
            or draft.revision != service_submission.revision
            or source_scope.current_run_id != submission.catalogue_run_id
            or submission.siruta_catalogue_version != SIRUTA_CATALOGUE_VERSION
            or submission.siruta_catalogue_sha256 != siruta_catalogue_sha256()
            or any(
                asset.state != ProviderPortfolioAsset.State.ACTIVE
                or not submission.portfolio_items.filter(
                    asset=asset, asset_sha256=asset.sha256
                ).exists()
                for asset in assets
            )
        ):
            raise ValueError("Conținutul sau sursele depunerii nu mai sunt curente.")
        authorization = provider_authorization(profile)
        if (
            authorization.run.pk != submission.authorization_run_id
            or authorization.catalogue_run.pk != submission.catalogue_run_id
        ):
            raise ValueError("Autorizarea ONRC nu mai corespunde depunerii.")
        if visibility == ProviderPublicationScope.Visibility.PUBLIC and not (
            source_scope.visibility == CatalogueScope.Visibility.PUBLIC
            and source_scope.current_approval_id
            and source_scope.current_approval.import_run_id == submission.catalogue_run_id
            and publication_approval_is_valid(source_scope.current_approval)
        ):
            raise ValueError("Catalogul sursă nu are aprobarea juridică necesară publicării.")

    instant = timezone.now()
    submission.decision = decision
    submission.reviewed_by = reviewer
    submission.reviewed_at = instant
    submission.review_policy_version = REVIEW_POLICY_VERSION
    submission.review_acknowledgement = acknowledgement
    submission.internal_review_note = note[:1200]
    submission.provider_feedback = feedback[:700]
    submission.save(
        update_fields=(
            "decision", "reviewed_by", "reviewed_at", "review_policy_version",
            "review_acknowledgement", "internal_review_note", "provider_feedback",
        )
    )
    if approve:
        previous = publication_scope.current_submission
        action = (
            ProviderPublicationEvent.Action.REPLACE
            if previous else ProviderPublicationEvent.Action.PUBLISH
        )
        ProviderPublicationEvent.objects.create(
            scope=publication_scope,
            previous_submission=previous,
            new_submission=submission,
            action=action,
            visibility=visibility,
            actor=reviewer,
            note=note,
        )
        publication_scope.visibility = visibility
        publication_scope.current_submission = submission
        publication_scope.activated_at = instant
        publication_scope.save(
            update_fields=("visibility", "current_submission", "activated_at")
        )
    return submission, True


@transaction.atomic
def unpublish_provider_profile(*, user, note: str = UNPUBLISH_NOTE) -> bool:
    """Allow an active owner to reduce visibility immediately through a POST action."""

    profile = _lock_owner_profile(user)
    return _unpublish_locked(profile=profile, actor=user, note=note)


def _scope_is_visible(scope: ProviderPublicationScope) -> bool:
    """Fail closed unless both provider and source pointers remain eligible."""

    submission = scope.current_submission
    try:
        subscription = submission.profile.subscription if submission else None
    except ProviderSubscription.DoesNotExist:
        subscription = None
    if (
        not submission
        or not subscription
        or subscription.status != subscription.Status.ACTIVE
        or subscription.period_ends_at <= timezone.now()
        or submission.decision != ProviderPublicationSubmission.Decision.APPROVED
        or submission.superseded_at is not None
        or submission.profile.state != ProviderProfile.State.DRAFT
        or submission.service_area_submission.decision
        != ProviderServiceAreaSubmission.Decision.APPROVED
        or submission.service_area_submission.superseded_at is not None
        or submission.catalogue_run.state != ImportRun.State.SUCCEEDED
        or submission.catalogue_run.snapshot.state != SourceSnapshot.State.VERIFIED
        or submission.profile_id != scope.profile_id
        or submission.portfolio_items.exclude(
            asset__state=ProviderPortfolioAsset.State.ACTIVE,
            asset__sha256=F("asset_sha256"),
        ).exists()
    ):
        return False
    source_scope = CatalogueScope.objects.select_related("current_approval").filter(
        provider="ONRC", county=submission.catalogue_run.county
    ).first()
    if not source_scope or source_scope.current_run_id != submission.catalogue_run_id:
        return False
    if scope.visibility == ProviderPublicationScope.Visibility.INTERNAL_PREVIEW:
        return bool(
            settings.DEBUG
            and source_scope.visibility
            in {
                CatalogueScope.Visibility.INTERNAL_PREVIEW,
                CatalogueScope.Visibility.PUBLIC,
            }
        )
    return bool(
        scope.visibility == ProviderPublicationScope.Visibility.PUBLIC
        and source_scope.visibility == CatalogueScope.Visibility.PUBLIC
        and source_scope.current_approval_id
        and source_scope.current_approval.import_run_id == submission.catalogue_run_id
        and publication_approval_is_valid(source_scope.current_approval)
    )


def provider_publication_effective_visibility(
    scope: ProviderPublicationScope,
) -> str:
    """Return the visibility readers can actually honor, including invalid drift."""

    if scope.visibility == ProviderPublicationScope.Visibility.OFF:
        return ProviderPublicationScope.Visibility.OFF
    try:
        subscription = scope.current_submission.profile.subscription
    except (AttributeError, ProviderSubscription.DoesNotExist):
        subscription = None
    if (
        subscription is None
        or subscription.status != ProviderSubscription.Status.ACTIVE
        or subscription.period_ends_at <= timezone.now()
    ):
        return "subscription_inactive"
    return scope.visibility if _scope_is_visible(scope) else "invalid"


def _project(
    scope: ProviderPublicationScope,
    searched_county: str,
    searched_locality_code: str | None,
) -> PublishedProvider:
    submission = scope.current_submission
    declarations_available = submission.snapshot_schema_version >= 2
    legal_name = RegisteredBusinessSnapshot.objects.get(
        import_run=submission.authorization_run,
        business=submission.profile.business,
    ).legal_name
    services = tuple(
        submission.services.order_by("category").values_list("category", flat=True)
    )
    coverage = tuple(
        PublishedServiceArea(
            county=item.county,
            locality=locality_name(item.county, item.siruta_code),
            siruta_code=item.siruta_code,
        )
        for item in submission.coverage.order_by("county", "siruta_code")
    )
    portfolio = tuple(
        PublishedPortfolioImage(
            opaque_id=item.asset.opaque_id,
            caption=item.caption,
            width=item.asset.width,
            height=item.asset.height,
        )
        for item in submission.portfolio_items.select_related("asset").order_by("position")
        if item.asset.state == ProviderPortfolioAsset.State.ACTIVE
        and item.asset.sha256 == item.asset_sha256
    )
    searched_area = next(
        (
            area
            for area in coverage
            if area.county == searched_county
            and (
                searched_locality_code is None
                or area.siruta_code == searched_locality_code
            )
        ),
        None,
    )
    if searched_area is None:
        raise ValueError("Published provider projection escaped its search coverage.")
    return PublishedProvider(
        public_id=submission.profile.public_id,
        business_id=submission.profile.business_id,
        display_name=submission.display_name,
        legal_name=legal_name,
        description=submission.description,
        public_address=(
            submission.public_address if submission.snapshot_schema_version >= 3 else ""
        ),
        public_phone=submission.public_phone,
        public_email=submission.public_email,
        website=submission.website,
        availability=submission.availability,
        availability_label=(
            ProviderProfile.Availability(submission.availability).label
            if declarations_available
            else _("Nedeclarată în versiunea profilului publicat")
        ),
        contact_preference=submission.contact_preference,
        contact_preference_label=(
            ProviderProfile.ContactPreference(submission.contact_preference).label
            if declarations_available
            else _("Nedeclarată în versiunea profilului publicat")
        ),
        category_slugs=services,
        category_labels=tuple(CATEGORY_LABELS[item] for item in services),
        coverage_areas=coverage,
        searched_locality_label=searched_area.locality,
        searched_locality_code=searched_area.siruta_code,
        portfolio=portfolio,
        preview=scope.visibility == ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
    )


def published_provider_search(
    *, county: str, siruta_code: str | None, category: str
):
    """Return stable provider publications by declared coverage, separately from ONRC rows."""

    query = ProviderPublicationScope.objects.select_related(
        "current_submission__profile__business",
        "current_submission__profile__subscription",
        "current_submission__service_area_submission",
        "current_submission__catalogue_run__snapshot",
        "current_submission__authorization_run",
    ).filter(current_submission__coverage__county=county)
    if siruta_code:
        query = query.filter(current_submission__coverage__siruta_code=siruta_code)
    if category:
        query = query.filter(current_submission__services__category=category)
    return tuple(
        _project(scope, county, siruta_code)
        for scope in query.order_by("current_submission__display_name", "pk").distinct()
        if _scope_is_visible(scope)
    )


def published_provider_detail(*, public_id, county: str, siruta_code: str, category: str):
    """Resolve an opaque provider URL only inside the exact requested search context."""

    scope = _visible_provider_scope(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    return _project(scope, county, siruta_code) if scope else None


def visible_provider_submission(*, public_id, county: str, siruta_code: str, category: str):
    """Return the exact visible immutable snapshot for a bounded trust workflow."""

    scope = _visible_provider_scope(
        public_id=public_id,
        county=county,
        siruta_code=siruta_code,
        category=category,
    )
    return scope.current_submission if scope else None


def _visible_provider_scope(*, public_id, county: str, siruta_code: str, category: str):
    """Resolve one provider scope through the same fail-closed public reader gates."""

    query = ProviderPublicationScope.objects.select_related(
        "current_submission__profile__business",
        "current_submission__profile__subscription",
        "current_submission__service_area_submission",
        "current_submission__catalogue_run__snapshot",
        "current_submission__authorization_run",
    ).filter(
        profile__public_id=public_id,
        current_submission__coverage__county=county,
        current_submission__coverage__siruta_code=siruta_code,
    )
    if category:
        query = query.filter(current_submission__services__category=category)
    scope = query.distinct().first()
    return scope if scope and _scope_is_visible(scope) else None


def portfolio_asset_for_request(*, opaque_id, user=None):
    """Authorize an owner, profile-viewing staff member, or visible public derivative."""

    asset = ProviderPortfolioAsset.objects.select_related("profile").filter(
        opaque_id=opaque_id, state=ProviderPortfolioAsset.State.ACTIVE
    ).first()
    if not asset:
        return None
    if user and user.is_authenticated and ProviderMembership.objects.filter(
        profile=asset.profile,
        user=user,
        state=ProviderMembership.State.ACTIVE,
        user__is_active=True,
    ).exists():
        return asset
    if (
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and (
            user.has_perm("services.review_provider_publication")
            or user.has_perm("services.view_providerprofile")
        )
    ):
        return asset
    scopes = ProviderPublicationScope.objects.select_related(
        "current_submission__profile",
        "current_submission__profile__subscription",
        "current_submission__service_area_submission",
        "current_submission__catalogue_run__snapshot",
    ).filter(current_submission__portfolio_items__asset=asset)
    return asset if any(_scope_is_visible(scope) for scope in scopes) else None
