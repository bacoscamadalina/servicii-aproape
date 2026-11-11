"""Search forms for the service catalogue."""

from datetime import timedelta
from decimal import Decimal
import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from .catalog import CATEGORIES
from .locations import county_choices, locality_choices, locality_name
from .models import (
    DataSubjectRequest,
    ManagedSiteInquiry,
    ProviderRepresentationEvidence,
    ProviderLead,
    ProviderProfile,
    ProviderPublicationScope,
    ProviderPublicationSubmission,
    ProviderSubscriptionEvent,
    PublicProviderReport,
    PublicProviderReportCase,
    ServiceCategoryPolicy,
)
from .provider_access import claim_account_login_attempt, clear_account_login_attempts
from .customer_accounts import active_customer_account
from .provider_team import active_provider_team_member


class ThrottledAdminAuthenticationForm(AdminAuthenticationForm):
    """Share a bounded administrator-login budget across every application worker."""

    def clean(self):
        username = self.cleaned_data.get("username", "")
        if username and not claim_account_login_attempt(
            scope="admin", identifier=username
        ):
            raise forms.ValidationError(
                _("Prea multe încercări. Reîncearcă peste 15 minute."),
                code="admin_login_throttled",
            )
        cleaned = super().clean()
        if self.user_cache is not None:
            clear_account_login_attempts(scope="admin", identifier=username)
        return cleaned


class ProviderSearchForm(forms.Form):
    """Validate the location-first marketplace search contract."""

    county = forms.ChoiceField(
        label=_("Județ"),
        choices=(("", _("Alege județul")), *county_choices()),
        error_messages={"required": _("Alege județul.")},
    )
    locality = forms.ChoiceField(
        label=_("Localitate"),
        required=False,
        choices=(("", _("Alege întâi județul")),),
        error_messages={
            "invalid_choice": _("Alege o localitate din județul selectat."),
        },
    )
    category = forms.ChoiceField(
        label=_("Serviciu"),
        required=False,
        choices=(
            ("", _("Toate serviciile")),
            *((slug, label) for slug, label, _description in CATEGORIES),
        ),
    )

    def __init__(self, *args, category_choices=None, **kwargs):
        """Populate locality choices only from the currently selected county."""

        super().__init__(*args, **kwargs)
        if category_choices is not None:
            self.fields["category"].choices = (
                ("", _("Toate serviciile")), *category_choices
            )
        county = (
            self.data.get("county") if self.is_bound else self.initial.get("county", "")
        ) or ""
        localities = locality_choices(county)
        self.fields["locality"].choices = (
            (("", _("Toate localitățile din județ")), *localities)
            if localities
            else (("", _("Alege întâi județul")),)
        )
        self.fields["locality"].widget.attrs.update(
            {
                "disabled": not localities,
                "data-placeholder": _("Toate localitățile din județ"),
            }
        )


class ProviderClaimForm(forms.Form):
    """Collect contact data and private evidence of company representation."""

    first_name = forms.CharField(
        label=_("Prenume"),
        max_length=150,
        min_length=2,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label=_("Nume"),
        max_length=150,
        min_length=2,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    username = forms.CharField(
        label=_("Nume de utilizator"),
        max_length=150,
        validators=(UnicodeUsernameValidator(),),
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    role = forms.ChoiceField(
        label=_("Rolul tău în firmă"),
        choices=(
            ("administrator", _("Administrator")),
            ("asociat", _("Asociat")),
            ("angajat_autorizat", _("Angajat autorizat")),
            ("alt_reprezentant", _("Alt reprezentant împuternicit")),
        ),
    )
    email = forms.EmailField(
        label=_("E-mail"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    password1 = forms.CharField(
        label=_("Parolă"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label=_("Confirmă parola"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    evidence_type = forms.ChoiceField(
        label=_("Cum demonstrezi dreptul de reprezentare?"),
        choices=ProviderRepresentationEvidence.EvidenceType.choices,
    )
    evidence_document = forms.FileField(
        label=_("Document justificativ"),
        help_text=_("PDF, JPEG sau PNG, maximum 5 MB. Nu încărca actul de identitate."),
        error_messages={
            "required": _(
                "Încarcă documentul care dovedește dreptul de reprezentare."
            )
        },
        widget=forms.FileInput(
            attrs={"accept": "application/pdf,image/jpeg,image/png"}
        ),
    )
    representation_declaration = forms.BooleanField(
        label=_(
            "Confirm că documentul este autentic, că am dreptul să îl transmit și "
            "că nu conține date personale care nu sunt necesare verificării."
        ),
        error_messages={"required": _("Confirmă declarația privind documentul.")},
    )
    privacy_consent = forms.BooleanField(
        label=_(
            "Sunt de acord ca datele introduse să fie folosite pentru verificarea "
            "reprezentării firmei."
        ),
        error_messages={"required": _("Confirmă acordul pentru a continua.")},
    )
    website = forms.CharField(
        required=False,
        label=_("Website"),
        widget=forms.HiddenInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def clean_first_name(self):
        return " ".join(self.cleaned_data["first_name"].split())

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split())

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("Acest nume de utilizator este deja folosit."))
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Există deja un cont cu această adresă de e-mail."))
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", _("Parolele nu coincid."))
        if password1 and password1 == password2:
            candidate = get_user_model()(
                username=cleaned.get("username", ""),
                email=cleaned.get("email", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
            )
            try:
                password_validation.validate_password(password1, candidate)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def clean_evidence_document(self):
        document = self.cleaned_data["evidence_document"]
        if document.size > 5 * 1024 * 1024:
            raise forms.ValidationError(_("Documentul poate avea maximum 5 MB."))
        return document

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError(_("Cererea nu a putut fi trimisă."))
        return ""


class ProviderRegistrationForm(ProviderClaimForm):
    """Collect legal identity hints for a company absent from the catalogue."""

    legal_name = forms.CharField(
        label=_("Denumirea juridică a firmei"),
        max_length=500,
        min_length=2,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
    )
    cui = forms.CharField(
        label=_("CUI / CIF"),
        max_length=12,
        widget=forms.TextInput(attrs={"autocomplete": "off", "inputmode": "numeric"}),
        help_text=_("Exemplu: RO12345678 sau 12345678"),
    )
    registration_number = forms.CharField(
        label=_("Număr de înregistrare în registrul comerțului"),
        max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
        help_text=_("Exemplu: J22/1234/2024"),
    )
    requested_category = forms.ChoiceField(
        label=_("Serviciul principal prestat"),
        choices=(
            ("", _("Alege serviciul")),
            *((slug, label) for slug, label, _description in CATEGORIES),
        ),
        help_text=_(
            "Alege categoria principală în care vrei să apară firma. "
            "Serviciul va fi verificat înainte de publicare."
        ),
        error_messages={"required": _("Alege serviciul principal prestat.")},
    )
    registered_county = forms.ChoiceField(
        label=_("Județul sediului social"),
        choices=(("", _("Alege județul")), *county_choices()),
    )
    registered_office_siruta = forms.ChoiceField(
        label=_("Localitatea sediului social"),
        choices=(("", _("Alege întâi județul")),),
        error_messages={
            "required": _("Alege localitatea."),
            "invalid_choice": _("Alege o localitate din județul selectat."),
        },
    )

    field_order = (
        "legal_name", "cui", "registration_number", "requested_category",
        "registered_county", "registered_office_siruta", "last_name", "first_name",
        "username", "role", "email", "password1", "password2", "evidence_type",
        "evidence_document", "representation_declaration", "privacy_consent", "website",
    )

    def __init__(self, *args, category_choices=None, **kwargs):
        """Limit locality choices to the submitted registered county."""

        super().__init__(*args, **kwargs)
        if category_choices is not None:
            self.fields["requested_category"].choices = (("", _("Alege serviciul")), *category_choices)
        self.fields["registered_county"].widget.attrs["id"] = "id_county"
        self.fields["registered_office_siruta"].widget.attrs["id"] = "id_locality"
        county = (self.data.get("registered_county") if self.is_bound else self.initial.get("registered_county", "")) or ""
        localities = locality_choices(county)
        self.fields["registered_office_siruta"].choices = (
            (("", _("Alege localitatea")), *localities)
            if localities else (("", _("Alege întâi județul")),)
        )
        self.fields["registered_office_siruta"].widget.attrs.update(
            {"disabled": not localities, "data-placeholder": _("Alege localitatea")}
        )

    def clean_legal_name(self):
        return " ".join(self.cleaned_data["legal_name"].split())

    def clean_cui(self):
        value = re.sub(r"[\s.-]", "", self.cleaned_data["cui"].upper())
        if not re.fullmatch(r"(?:RO)?\d{2,10}", value):
            raise forms.ValidationError(_("Introdu un CUI / CIF valid."))
        return value

    def clean_registration_number(self):
        return " ".join(self.cleaned_data["registration_number"].upper().split())


class CustomerRegistrationForm(forms.Form):
    """Create a customer account with the same explicit credential flow as providers."""

    last_name = forms.CharField(
        label=_("Nume"), min_length=2, max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    first_name = forms.CharField(
        label=_("Prenume"), min_length=2, max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    username = forms.CharField(
        label=_("Nume de utilizator"), max_length=150,
        validators=(UnicodeUsernameValidator(),),
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    email = forms.EmailField(
        label=_("E-mail"), max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    password1 = forms.CharField(
        label=_("Parolă"), strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label=_("Confirmă parola"), strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    privacy_consent = forms.BooleanField(
        label=_("Sunt de acord cu folosirea datelor mele pentru administrarea contului și a solicitărilor trimise."),
        error_messages={"required": _("Confirmă acordul pentru a continua.")},
    )
    website = forms.CharField(
        required=False, label=_("Website"),
        widget=forms.HiddenInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split())

    def clean_first_name(self):
        return " ".join(self.cleaned_data["first_name"].split())

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("Acest nume de utilizator este deja folosit."))
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Există deja un cont cu această adresă de e-mail."))
        return email

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError(_("Contul nu a putut fi creat."))
        return ""

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", _("Parolele nu coincid."))
        if password1 and password1 == password2:
            candidate = get_user_model()(
                username=cleaned.get("username", ""), email=cleaned.get("email", ""),
                first_name=cleaned.get("first_name", ""), last_name=cleaned.get("last_name", ""),
            )
            try:
                password_validation.validate_password(password1, candidate)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned


class ProviderTeamInviteForm(forms.Form):
    """Collect one recipient address without granting access at submission."""

    email = forms.EmailField(
        label=_("E-mailul tehnicianului"), max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class ProviderTeamNewAccountForm(forms.Form):
    """Create credentials only for the exact mailbox proven by an invitation."""

    first_name = forms.CharField(
        label=_("Prenume"), min_length=2, max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label=_("Nume"), min_length=2, max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    username = forms.CharField(
        label=_("Nume de utilizator"), max_length=150,
        validators=(UnicodeUsernameValidator(),),
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    password1 = forms.CharField(
        label=_("Parolă"), strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label=_("Confirmă parola"), strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("Acest nume de utilizator este deja folosit."))
        return username

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password1")
        if password and password != cleaned.get("password2"):
            self.add_error("password2", _("Parolele nu coincid."))
        if password and password == cleaned.get("password2"):
            candidate = get_user_model()(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
            )
            try:
                password_validation.validate_password(password, candidate)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned


class ProviderTeamExistingAccountForm(forms.Form):
    """Confirm control of an existing account before accepting an invitation."""

    password = forms.CharField(
        label=_("Parola contului existent"), strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class ProviderRegistrationReviewForm(forms.Form):
    """Require a documented decision on one unlisted-company registration."""

    decision = forms.ChoiceField(
        label="Decizie",
        choices=(("convert", "Identitate verificată"), ("reject", "Respinge")),
        widget=forms.RadioSelect,
    )
    verified_registration_number = forms.CharField(
        label="Număr oficial verificat",
        max_length=80,
        required=False,
        help_text=(
            "Obligatoriu la verificare. Dacă identitatea există deja, cererea va fi "
            "legată de ea; altfel va fi creată identitatea internă stabilă."
        ),
    )
    review_note = forms.CharField(
        label="Baza deciziei",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Documentează sursa verificării fără copii de acte sau date inutile.",
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că am verificat identitatea juridică separat și că această "
            "decizie nu publică firma sau serviciile."
        )
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "convert" and not cleaned.get(
            "verified_registration_number"
        ):
            self.add_error(
                "verified_registration_number",
                "Introdu numărul oficial verificat.",
            )
        return cleaned


class PublicProviderReportForm(forms.Form):
    """Collect no visitor identity and only the facts needed to inspect a report."""

    reason = forms.ChoiceField(
        label=_("Ce problemă ai observat?"),
        choices=PublicProviderReport.Reason.choices,
    )
    details = forms.CharField(
        label=_("Descrie concret problema"),
        min_length=20,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 6}),
        error_messages={
            "required": _("Descrie problema observată."),
            "min_length": _("Descrierea trebuie să aibă cel puțin 20 de caractere."),
            "max_length": _("Descrierea poate avea cel mult 1.200 de caractere."),
        },
        help_text=_(
            "Nu include CNP, copii de acte, parole, date bancare sau alte date personale."
        ),
    )
    website = forms.CharField(
        required=False,
        label=_("Website"),
        widget=forms.HiddenInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def clean_details(self):
        return " ".join(self.cleaned_data["details"].split())

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError(_("Sesizarea nu a putut fi trimisă."))
        return ""


class ProviderLeadForm(forms.Form):
    """Collect the minimum contact and project facts needed by one provider."""

    category = forms.ChoiceField(label=_("Serviciul solicitat"), choices=())
    customer_name = forms.CharField(
        label=_("Numele tău"),
        min_length=2,
        max_length=120,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    customer_email = forms.EmailField(
        label=_("E-mail"),
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    customer_phone = forms.CharField(
        label=_("Telefon"),
        min_length=7,
        max_length=32,
        widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
    )
    project_address = forms.CharField(
        required=False,
        label=_("Adresa aproximativă a lucrării (opțional)"),
        max_length=300,
        widget=forms.TextInput(attrs={"autocomplete": "street-address"}),
        help_text=_("Poți indica doar strada sau zona; nu este necesară adresa completă."),
    )
    description = forms.CharField(
        label=_("Descrie lucrarea"),
        min_length=30,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 7}),
        help_text=_("Include dimensiunea aproximativă, starea actuală și rezultatul dorit."),
    )
    budget = forms.ChoiceField(label=_("Buget orientativ"), choices=ProviderLead.Budget.choices)
    desired_start = forms.ChoiceField(
        label=_("Când ai dori să înceapă lucrarea?"),
        choices=ProviderLead.DesiredStart.choices,
    )
    consent = forms.BooleanField(
        label=_("Sunt de acord ca datele introduse să fie transmise acestei firme pentru a răspunde solicitării."),
    )
    website = forms.CharField(
        required=False,
        label=_("Website"),
        widget=forms.HiddenInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def __init__(self, *args, service_choices=(), customer_account=None, **kwargs):
        super().__init__(*args, **kwargs)
        if "category" in self.fields:
            self.fields["category"].choices = service_choices
        if customer_account is not None:
            full_name = customer_account.user.get_full_name().strip()
            self.fields["customer_name"].initial = full_name or customer_account.user.username
            self.fields["customer_email"].initial = customer_account.normalized_email
            self.fields["customer_name"].disabled = True
            self.fields["customer_email"].disabled = True

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError(_("Solicitarea nu a putut fi trimisă."))
        return ""

    def clean(self):
        cleaned = super().clean()
        for field in ("customer_name", "customer_phone", "project_address", "description"):
            if cleaned.get(field):
                cleaned[field] = " ".join(cleaned[field].split())
        return cleaned


class GeneralProviderLeadForm(ProviderLeadForm):
    """Collect one project that may be dispatched to several eligible providers."""

    category = None
    consent = forms.BooleanField(
        label=_(
            "Sunt de acord ca datele introduse să fie transmise tuturor firmelor "
            "eligibile cu abonament activ pentru a răspunde solicitării."
        ),
    )


class ProviderLeadUpdateForm(forms.Form):
    """Apply an optimistic owner update to one private customer request."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    status = forms.ChoiceField(label=_("Stare"), choices=())
    owner_notes = forms.CharField(
        required=False,
        label=_("Notițe private"),
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Aceste notițe sunt vizibile numai în contul firmei."),
    )

    def __init__(self, *args, status_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = status_choices


class ProviderQuoteForm(forms.Form):
    """Collect one complete offer; submitted offers are immutable."""

    LINE_COUNT = 4
    UNIT_CHOICES = (
        ("lucrare", _("lucrare")),
        ("buc", _("buc.")),
        ("oră", _("oră")),
        ("mp", _("mp")),
        ("ml", _("ml")),
        ("set", _("set")),
    )

    amount_ron = forms.DecimalField(
        label=_("Total ofertă (lei)"), required=False,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            "inputmode": "decimal", "step": "0.01", "readonly": True,
            "data-quote-total": "",
        }),
    )
    estimated_duration = forms.CharField(
        label=_("Durată estimată"),
        min_length=2,
        max_length=120,
        help_text=_("Exemplu: 3–4 săptămâni de la semnarea contractului."),
    )
    valid_until = forms.DateField(
        label=_("Ofertă valabilă până la"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    summary = forms.CharField(
        label=_("Ce include oferta"),
        min_length=20,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=_("Descrie lucrările, materialele incluse și eventualele excluderi."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for position in range(1, self.LINE_COUNT + 1):
            self.fields[f"item_{position}_description"] = forms.CharField(
                required=False, max_length=240, label=_("Descriere"),
            )
            self.fields[f"item_{position}_quantity"] = forms.DecimalField(
                required=False, min_value=Decimal("0.01"), max_value=Decimal("99999999"),
                max_digits=10, decimal_places=2, label=_("Cantitate"),
                widget=forms.NumberInput(attrs={
                    "inputmode": "decimal", "step": "0.01", "data-quote-quantity": "",
                }),
            )
            self.fields[f"item_{position}_unit"] = forms.ChoiceField(
                required=False, choices=(("", _("Unitate")), *self.UNIT_CHOICES),
                label=_("Unitate"),
            )
            self.fields[f"item_{position}_unit_price_ron"] = forms.DecimalField(
                required=False, min_value=0, max_value=99_999_999,
                decimal_places=2, label=_("Preț unitar (lei)"),
                widget=forms.NumberInput(attrs={
                    "inputmode": "decimal", "step": "0.01", "data-quote-unit-price": "",
                }),
            )

    @property
    def core_fields(self):
        """Expose the non-line fields in their deliberate visual order."""

        return [self[name] for name in (
            "estimated_duration", "valid_until", "summary", "amount_ron",
        )]

    @property
    def line_rows(self):
        """Group bound line fields without introducing a separate formset state."""

        return [
            {
                "position": position,
                "description": self[f"item_{position}_description"],
                "quantity": self[f"item_{position}_quantity"],
                "unit": self[f"item_{position}_unit"],
                "unit_price": self[f"item_{position}_unit_price_ron"],
            }
            for position in range(1, self.LINE_COUNT + 1)
        ]

    def clean(self):
        cleaned = super().clean()
        for field in ("estimated_duration", "summary"):
            if cleaned.get(field):
                cleaned[field] = " ".join(cleaned[field].split())
        lines = []
        for position in range(1, self.LINE_COUNT + 1):
            names = {
                "description": f"item_{position}_description",
                "quantity": f"item_{position}_quantity",
                "unit": f"item_{position}_unit",
                "unit_price_ron": f"item_{position}_unit_price_ron",
            }
            values = {key: cleaned.get(name) for key, name in names.items()}
            if not any(value not in (None, "") for value in values.values()):
                continue
            missing = [name for key, name in names.items() if values[key] in (None, "")]
            for name in missing:
                self.add_error(name, _("Completează această poziție."))
            if missing:
                continue
            values["description"] = " ".join(values["description"].split())
            values["position"] = position
            lines.append(values)
        for position in range(1, self.LINE_COUNT + 1):
            for suffix in ("description", "quantity", "unit", "unit_price_ron"):
                cleaned.pop(f"item_{position}_{suffix}", None)
        if not lines:
            raise forms.ValidationError(_("Adaugă cel puțin o poziție în ofertă."))
        if not self.errors:
            cleaned["amount_ron"] = sum(
                (line["quantity"] * line["unit_price_ron"] for line in lines),
                Decimal("0.00"),
            )
            if cleaned["amount_ron"] <= 0:
                self.add_error("amount_ron", _("Totalul ofertei trebuie să fie mai mare decât zero."))
        cleaned["line_items"] = lines
        return cleaned


class ProviderOwnerCommandForm(forms.Form):
    """Keep a bounded, private instruction until the owner reviews a draft."""

    command = forms.CharField(
        label=_("Instrucțiune pentru asistent"),
        max_length=500,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": _(
                    "Creează ofertă pentru dl. Ionescu: montare 3 aparate AC, 7.500 lei"
                ),
            }
        ),
    )


class ProviderCRMCustomerForm(forms.Form):
    """Collect one provider-private contact with explicit lawful-use confirmation."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    customer_id = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    name = forms.CharField(label=_("Nume client"), min_length=2, max_length=160)
    email = forms.EmailField(label=_("E-mail"), required=False, max_length=254)
    phone = forms.CharField(label=_("Telefon"), required=False, max_length=32)
    address = forms.CharField(label=_("Adresă (opțional)"), required=False, max_length=500)
    notes = forms.CharField(
        label=_("Notițe private (opțional)"), required=False, max_length=1200,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    lawful_use_confirmed = forms.BooleanField(
        label=_("Confirm că am un motiv legitim să păstrez aceste date pentru relația cu acest client."),
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("email") and not cleaned.get("phone"):
            raise forms.ValidationError(_("Completează cel puțin e-mailul sau telefonul."))
        for field in ("name", "phone", "address", "notes"):
            if cleaned.get(field):
                cleaned[field] = " ".join(cleaned[field].split())
        if cleaned.get("email"):
            cleaned["email"] = cleaned["email"].strip().lower()
        return cleaned


class ProviderCRMCustomerArchiveForm(forms.Form):
    """Archive one contact with optimistic concurrency instead of deleting PII silently."""

    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    customer_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirmed = forms.BooleanField(label=_("Confirm arhivarea clientului."))


class ProviderCRMCustomerLinkForm(forms.Form):
    """Bind one request to a chosen private contact without copying its PII."""

    lead_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    customer_id = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class ProviderCRMCustomerFromLeadForm(ProviderCRMCustomerForm):
    """Create a private contact from reviewed request data, then link it explicitly."""

    lead_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    expected_link_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class ProviderWorkOrderScheduleForm(forms.Form):
    """Capture the planned execution start and optional end without inventing duration."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    starts_at = forms.DateTimeField(
        label=_("Începutul lucrării"),
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    ends_at = forms.DateTimeField(
        label=_("Ora estimată de încheiere (opțional)"),
        required=False,
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )


class ProviderWorkOrderCompleteForm(forms.Form):
    """Require explicit confirmation before recording completion."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirmed = forms.BooleanField(
        label=_("Confirm că lucrarea a fost efectiv finalizată."),
    )


class ProviderWorkOrderCancelForm(forms.Form):
    """Require explicit consent before removing a future job booking."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirmed = forms.BooleanField(
        label=_("Confirm anularea programării. Oferta acceptată și lucrarea rămân active."),
    )


class ProviderWorkAssignmentForm(forms.Form):
    """Offer only active technicians while the server rechecks the exact assignment."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    member_id = forms.ChoiceField(label=_("Tehnician"))

    def __init__(self, *args, members=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member_id"].choices = (
            ("", _("Fără tehnician")),
            *((str(member.pk), member.user.get_full_name() or member.user.email) for member in members),
        )

    def clean_member_id(self):
        value = self.cleaned_data["member_id"]
        return int(value) if value else None


class ProviderInvoiceDraftForm(forms.Form):
    """Edit only non-fiscal billing details for one completed job."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    amount_ron = forms.DecimalField(
        label=_("Sumă de pregătit (lei)"), min_value=0.01, max_value=99999999.99,
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0.01", "max": "99999999.99", "step": "0.01", "inputmode": "decimal"}),
    )
    description = forms.CharField(
        label=_("Descriere pentru facturare"), min_length=10, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_description(self):
        """Keep the saved draft concise and comparable across revisions."""

        return " ".join(self.cleaned_data["description"].split())


class ProviderReceivableForm(forms.Form):
    """Open a non-fiscal internal amount-due record from a saved draft."""

    due_date = forms.DateField(
        label=_("Scadență internă"), widget=forms.DateInput(attrs={"type": "date"}),
    )
    reference = forms.CharField(
        label=_("Referință internă (opțional)"), required=False, max_length=200,
    )


class ProviderManualPaymentForm(forms.Form):
    """Record money declared received outside ServiciiAproape."""

    amount_ron = forms.DecimalField(
        label=_("Sumă încasată manual (lei)"), min_value=0.01,
        max_value=99999999.99, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0.01", "max": "99999999.99", "step": "0.01", "inputmode": "decimal"}),
    )
    received_on = forms.DateField(
        label=_("Data încasării"), widget=forms.DateInput(attrs={"type": "date"}),
    )
    reference = forms.CharField(
        label=_("Referință declarată (opțional)"), required=False, max_length=200,
    )


class ProviderManualPaymentVoidForm(forms.Form):
    """Require an auditable reason instead of deleting a payment declaration."""

    payment_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    reason = forms.CharField(
        label=_("Motivul anulării înregistrării"), min_length=8, max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class ProviderReceivableFollowUpForm(forms.Form):
    """Schedule an internal follow-up without contacting the customer."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    follow_up_on = forms.DateField(
        label=_("Reamintește-mi în data de"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class ProviderReceivableFollowUpCompleteForm(forms.Form):
    """Confirm one internal follow-up while preserving revision safety."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class ProviderBillingIdentityForm(forms.Form):
    """Collect the provider's own issuer details without claiming verification."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    legal_name = forms.CharField(
        label=_("Denumirea legală a emitentului"), min_length=2, max_length=500,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
    )
    fiscal_identifier = forms.CharField(
        label=_("Identificator fiscal declarat"), min_length=2, max_length=40,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    registration_number = forms.CharField(
        label=_("Număr de înregistrare declarat"), min_length=3, max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    registered_address = forms.CharField(
        label=_("Adresa declarată a emitentului"), min_length=10, max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "autocomplete": "street-address"}),
    )


class ProviderVisitProposalForm(forms.Form):
    """Collect a concrete local visit time; the customer must confirm it."""

    starts_at = forms.DateTimeField(
        label=_("Data și ora vizitei"),
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    note = forms.CharField(
        label=_("Detalii pentru vizită (opțional)"),
        required=False,
        max_length=300,
        widget=forms.TextInput(attrs={"placeholder": _("Ex.: estimăm 30 de minute")}),
    )

    def clean_starts_at(self):
        starts_at = self.cleaned_data["starts_at"]
        if not timezone.now() + timedelta(hours=1) <= starts_at <= timezone.now() + timedelta(days=90):
            raise forms.ValidationError(_("Alege o oră între o oră și 90 de zile de acum."))
        return starts_at


class ProviderLeadMessageForm(forms.Form):
    """Collect one short message without attachments or rich content."""

    body = forms.CharField(
        label=_("Mesaj"),
        min_length=2,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def clean_body(self):
        return " ".join(self.cleaned_data["body"].split())


class ProviderCustomerReviewForm(forms.Form):
    """Collect one public review after the customer accepted an offer."""

    rating = forms.TypedChoiceField(
        label=_("Evaluarea ta"),
        choices=((5, _("5 — Excelent")), (4, _("4 — Foarte bine")), (3, _("3 — Bine")), (2, _("2 — Slab")), (1, _("1 — Foarte slab"))),
        coerce=int,
        widget=forms.RadioSelect,
    )
    body = forms.CharField(
        label=_("Cum a fost colaborarea?"),
        min_length=30,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=_("Descrie comunicarea, respectarea ofertei și rezultatul lucrării."),
    )
    consent = forms.BooleanField(
        label=_("Sunt de acord ca evaluarea și prenumele meu cu inițiala numelui să fie afișate public după verificare."),
    )

    def clean_body(self):
        return " ".join(self.cleaned_data["body"].split())


class ProviderCustomerReviewModerationForm(forms.Form):
    """Require one explicit, documented review-moderation decision."""

    decision = forms.ChoiceField(
        label="Decizie",
        choices=(("approved", "Publică"), ("rejected", "Respinge")),
        widget=forms.RadioSelect,
    )
    internal_note = forms.CharField(
        label="Motivul deciziei",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Nu include date personale care nu sunt necesare deciziei.",
    )
    acknowledgement = forms.BooleanField(
        label="Confirm că am verificat recenzia și eligibilitatea solicitării asociate.",
    )


class ProviderCustomerReviewReplyForm(forms.Form):
    """Collect one immutable response from the verified provider."""

    body = forms.CharField(
        label=_("Răspunsul firmei"),
        min_length=20,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Răspunde profesionist și nu include date personale despre client."),
    )

    def clean_body(self):
        return " ".join(self.cleaned_data["body"].split())


class ProviderCustomerReviewReplyModerationForm(forms.Form):
    """Require an explicit response-moderation decision."""

    decision = forms.ChoiceField(
        label="Decizie",
        choices=(("approved", "Publică"), ("rejected", "Respinge")),
        widget=forms.RadioSelect,
    )
    internal_note = forms.CharField(
        label="Motivul deciziei",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    acknowledgement = forms.BooleanField(
        label="Confirm că am verificat răspunsul firmei și recenzia asociată.",
    )


class ProviderClaimReviewForm(forms.Form):
    """Require an explicit, documented administrative claim decision."""

    decision = forms.ChoiceField(
        label="Decizie",
        choices=(("approve", "Aprobă"), ("reject", "Respinge")),
        widget=forms.RadioSelect,
    )
    review_note = forms.CharField(
        label="Baza deciziei",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Nu include copii de acte, CNP sau alte date care nu sunt necesare.",
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că am verificat separat dreptul de reprezentare și că decizia "
            "nu modifică datele ONRC."
        )
    )


class ProviderActivationForm(SetPasswordForm):
    """Set the first password only after the invitation POST is validated."""

    new_password1 = forms.CharField(
        label=_("Parolă nouă"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    new_password2 = forms.CharField(
        label=_("Confirmă parola"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class ProviderLoginForm(forms.Form):
    """Authenticate a provider by the unique e-mail reserved at approval."""

    email = forms.EmailField(
        label=_("E-mail"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    password = forms.CharField(
        label=_("Parolă"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class CustomerLoginForm(ProviderLoginForm):
    """Authenticate an active customer with their e-mail and password."""


class ProviderPasswordResetForm(PasswordResetForm):
    """Send reset links only for active provider owners or technicians."""

    email = forms.EmailField(
        label=_("E-mailul contului"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def get_users(self, email):
        """Preserve Django's silent lookup while excluding unrelated or revoked users."""

        for user in super().get_users(email):
            memberships = list(
                user.provider_memberships.filter(
                    state="active", profile__state=ProviderProfile.State.DRAFT
                ).values_list("pk", flat=True)[:2]
            )
            if len(memberships) == 1 or active_provider_team_member(user):
                yield user


class CustomerPasswordResetForm(PasswordResetForm):
    """Send reset links only to active customer accounts, never provider owners."""

    email = forms.EmailField(
        label=_("E-mailul contului"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def get_users(self, email):
        """Keep Django's silent lookup and exclude users outside the customer role."""

        for user in super().get_users(email):
            if active_customer_account(user):
                yield user


class AccountPasswordChangeForm(PasswordChangeForm):
    """Collect the current credential before replacing an authenticated password."""

    error_messages = {
        **PasswordChangeForm.error_messages,
        "password_incorrect": _("Parola curentă nu este corectă."),
    }

    old_password = forms.CharField(
        label=_("Parola curentă"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    new_password1 = forms.CharField(
        label=_("Parola nouă"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    new_password2 = forms.CharField(
        label=_("Confirmă parola nouă"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class ProviderProfileForm(forms.ModelForm):
    """Whitelist only provider-owned draft fields; legal facts stay immutable."""

    class Meta:
        model = ProviderProfile
        fields = (
            "display_name",
            "description",
            "public_address",
            "public_phone",
            "public_email",
            "website",
            "availability",
            "contact_preference",
        )
        labels = {
            "display_name": _("Nume public"),
            "description": _("Descriere"),
            "public_address": _("Adresă profesională publică (opțional)"),
            "public_phone": _("Telefon public"),
            "public_email": _("E-mail public"),
            "website": _("Website"),
            "availability": _("Disponibilitate declarată"),
            "contact_preference": _("Metodă de contact preferată"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 7}),
            "public_address": forms.TextInput(
                attrs={"autocomplete": "street-address", "maxlength": 300}
            ),
            "public_phone": forms.TextInput(attrs={"autocomplete": "tel"}),
            "public_email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "website": forms.URLInput(attrs={"autocomplete": "url"}),
        }
        help_texts = {
            "public_address": _(
                "Completeaz-o numai dacă vrei ca adresa să apară în profilul aprobat. "
                "Localitățile deservite se declară separat."
            ),
            "availability": _("Este o declarație curentă și poate fi modificată oricând."),
            "contact_preference": _(
                "Alege numai o metodă pentru care ai completat datele publice."
            ),
        }

    def clean(self):
        """Keep the preferred contact method backed by a visible contact value."""

        cleaned = super().clean()
        preference = cleaned.get("contact_preference")
        required_field = {
            ProviderProfile.ContactPreference.PHONE: "public_phone",
            ProviderProfile.ContactPreference.EMAIL: "public_email",
            ProviderProfile.ContactPreference.WEBSITE: "website",
        }.get(preference)
        if required_field and not cleaned.get(required_field):
            self.add_error(
                required_field,
                _("Completează această metodă înainte să o alegi ca preferată."),
            )
        return cleaned


class PublicProviderReportTriageForm(forms.Form):
    """Collect an explicit terminal report decision without publication side effects."""

    outcome = forms.ChoiceField(
        label="Concluzie",
        choices=PublicProviderReportCase.Outcome.choices,
        widget=forms.RadioSelect,
    )
    internal_note = forms.CharField(
        label="Notă internă",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=(
            "Notează verificările efectuate și motivul deciziei. Nu include CNP, "
            "copii de acte, parole sau alte date personale inutile."
        ),
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că analiza nu retrage automat profilul și nu modifică "
            "sesizarea inițială."
        )
    )
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, closing=False, **kwargs):
        """Require a conclusion only for the terminal close transition."""

        super().__init__(*args, **kwargs)
        self.fields["outcome"].required = closing


class DataSubjectRequestIntakeForm(forms.ModelForm):
    """Record only the contact and request facts received by the operator."""

    class Meta:
        model = DataSubjectRequest
        fields = (
            "request_kind",
            "channel",
            "requester_name",
            "contact_email",
            "details",
            "received_at",
        )
        widgets = {
            "details": forms.Textarea(attrs={"rows": 6}),
        }
        help_texts = {
            "details": (
                "Rezumați cererea și sistemele vizate. Nu încărcați copii de acte, "
                "CNP-uri, parole sau date bancare."
            )
        }

    def clean_requester_name(self):
        return " ".join(self.cleaned_data["requester_name"].split())

    def clean_contact_email(self):
        return self.cleaned_data["contact_email"].strip().lower()

    def clean_details(self):
        details = " ".join(self.cleaned_data["details"].split())
        if len(details) < 8:
            raise forms.ValidationError("Rezumatul trebuie să aibă cel puțin 8 caractere.")
        return details

    def clean_received_at(self):
        received_at = self.cleaned_data["received_at"]
        if received_at > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("Data primirii nu poate fi în viitor.")
        return received_at


class DataSubjectRequestProcessForm(forms.Form):
    """Collect one explicit transition or deadline-extension decision."""

    action = forms.ChoiceField(label="Acțiune", widget=forms.RadioSelect)
    internal_note = forms.CharField(
        label="Notă internă",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=(
            "Documentați verificarea și răspunsul. Nu includeți copii de acte, CNP, "
            "parole sau alte date personale inutile."
        ),
    )
    acknowledgement = forms.BooleanField(label="Confirm respectarea regulilor afișate.")
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, item, **kwargs):
        """Expose only actions valid for the request's current persisted state."""

        super().__init__(*args, **kwargs)
        export_choices = (
            (
                (
                    "generate_export",
                    "Generează pachetul JSON pentru acces / portabilitate",
                ),
            )
            if item.request_kind in (
                DataSubjectRequest.Kind.ACCESS,
                DataSubjectRequest.Kind.PORTABILITY,
            )
            else ()
        )
        choices = {
            DataSubjectRequest.Status.RECEIVED: (
                (DataSubjectRequest.Status.IDENTITY_PENDING, "Solicită confirmarea identității"),
                (DataSubjectRequest.Status.IN_REVIEW, "Confirmă identitatea și începe analiza"),
            ),
            DataSubjectRequest.Status.IDENTITY_PENDING: (
                (DataSubjectRequest.Status.IN_REVIEW, "Confirmă identitatea și începe analiza"),
            ),
            DataSubjectRequest.Status.IN_REVIEW: (
                *export_choices,
                (DataSubjectRequest.Status.FULFILLED, "Înregistrează soluționarea"),
                (DataSubjectRequest.Status.REFUSED, "Înregistrează refuzul motivat"),
            ),
        }.get(item.status, ())
        if (
            item.extended_due_at is None
            and timezone.now() <= item.due_at
            and choices
        ):
            choices = (*choices, ("extend_deadline", "Prelungește termenul cu două luni"))
        self.fields["action"].choices = choices
        self.fields["internal_note"].required = False

    def clean(self):
        """Require an operator note for decisions, never for the generated export audit."""

        cleaned_data = super().clean()
        note = " ".join(cleaned_data.get("internal_note", "").split())
        if cleaned_data.get("action") != "generate_export" and len(note) < 8:
            self.add_error(
                "internal_note",
                "Nota internă trebuie să explice acțiunea efectuată.",
            )
        cleaned_data["internal_note"] = note
        return cleaned_data


class ProviderPortfolioImageInput(forms.ClearableFileInput):
    """Allow one explicit portfolio submission to carry several image files."""

    allow_multiple_selected = True


class ProviderPortfolioImageField(forms.FileField):
    """Validate every selected file with Django's normal upload checks."""

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        return [single_file_clean(item, initial) for item in data] if isinstance(
            data, (list, tuple)
        ) else [single_file_clean(data, initial)]


class ProviderPortfolioUploadForm(forms.Form):
    """Collect a private portfolio image batch and explicit rights confirmation."""

    images = ProviderPortfolioImageField(
        label=_("Fotografii"),
        widget=ProviderPortfolioImageInput(
            attrs={"accept": "image/jpeg,image/png,image/webp"}
        ),
    )
    caption = forms.CharField(
        label=_("Descriere scurtă"),
        max_length=240,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Ex.: Renovare completă a bucătăriei")}),
    )
    rights_confirmation = forms.BooleanField(
        label=_(
            "Confirm că am dreptul să public această imagine și că nu conține "
            "date personale, documente sau persoane identificabile fără acord."
        )
    )


class ProviderPublicationSubmitForm(forms.Form):
    """Require an explicit confirmation before snapshotting the whole profile."""

    acknowledgement = forms.BooleanField(
        label=_(
            "Confirm că informațiile, serviciile, localitățile și fotografiile sunt "
            "corecte și pot fi trimise pentru publicare."
        )
    )


class ProviderPublicationReviewForm(forms.Form):
    """Keep content review, provider feedback, and visibility explicit."""

    decision = forms.ChoiceField(
        label="Decizie",
        choices=(
            (ProviderPublicationSubmission.Decision.APPROVED, "Aprobă și activează"),
            (
                ProviderPublicationSubmission.Decision.CHANGES_REQUIRED,
                "Solicită modificări",
            ),
        ),
        widget=forms.RadioSelect,
    )
    visibility = forms.ChoiceField(
        label="Vizibilitate după aprobare",
        choices=(
            (
                ProviderPublicationScope.Visibility.INTERNAL_PREVIEW,
                "Previzualizare internă",
            ),
            (ProviderPublicationScope.Visibility.PUBLIC, "Public"),
        ),
    )
    internal_note = forms.CharField(
        label="Notă internă",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Nu include CNP, copii de acte, parole sau alte date inutile.",
    )
    provider_feedback = forms.CharField(
        label="Mesaj pentru furnizor",
        required=False,
        max_length=700,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că am verificat exact snapshotul afișat și că aprobarea "
            "profilului este separată de aprobarea juridică a catalogului ONRC/MF."
        )
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("decision")
            == ProviderPublicationSubmission.Decision.CHANGES_REQUIRED
            and len((cleaned.get("provider_feedback") or "").strip()) < 8
        ):
            self.add_error(
                "provider_feedback", "Explică furnizorului ce trebuie modificat."
            )
        return cleaned


class ProviderSubscriptionAdminForm(forms.Form):
    """Require an explicit, revision-bound decision for a test entitlement."""

    action = forms.ChoiceField(
        label="Acțiune",
        choices=(
            (ProviderSubscriptionEvent.Action.ACTIVATE, "Activează / prelungește 30 zile"),
            (ProviderSubscriptionEvent.Action.DEACTIVATE, "Dezactivează"),
        ),
        widget=forms.RadioSelect,
    )
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    internal_note = forms.CharField(
        label="Notă internă",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Documentează motivul fără parole, acte sau alte date inutile.",
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că acesta este un abonament de test activat manual, fără o plată "
            "înregistrată de platformă."
        )
    )


class ServiceCategoryPolicyUpdateForm(forms.Form):
    """Bind one operational category change to the rendered revision."""

    category = forms.ChoiceField(
        choices=tuple((slug, label) for slug, label, _description in CATEGORIES),
        widget=forms.HiddenInput,
    )
    state = forms.ChoiceField(
        label="Disponibilitate",
        choices=ServiceCategoryPolicy.State.choices,
        widget=forms.RadioSelect,
    )
    display_order = forms.IntegerField(
        label="Poziție în listă",
        min_value=1,
        max_value=99,
        help_text="Numerele mai mici apar primele. Pozițiile egale sunt ordonate după slug.",
    )
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Motiv intern",
        min_length=8,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Explică schimbarea fără date personale sau documente juridice.",
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că schimbarea controlează doar descoperirea și înscrierile noi; "
            "nu modifică date CAEN și nu șterge serviciile firmelor existente."
        )
    )


class ProviderSimulatedCheckoutForm(forms.Form):
    """Confirm a zero-payment simulation without collecting financial data."""

    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    acknowledgement = forms.BooleanField(
        label=_(
            "Înțeleg că aceasta este o simulare: nu introduc date de card, nu se "
            "retrage nicio sumă și nu se emite factură."
        )
    )


class ManagedSiteInquiryForm(forms.Form):
    """Collect a bounded brief without duplicating provider-account identity."""

    goal = forms.ChoiceField(
        label=_("Obiectivul principal"), choices=ManagedSiteInquiry.Goal.choices
    )
    desired_launch = forms.ChoiceField(
        label=_("Când ai vrea să fie gata?"),
        choices=ManagedSiteInquiry.DesiredLaunch.choices,
    )
    current_website = forms.URLField(
        required=False,
        label=_("Site existent (opțional)"),
        max_length=500,
        widget=forms.URLInput(attrs={"autocomplete": "url", "placeholder": "https://"}),
    )
    brief = forms.CharField(
        label=_("Ce trebuie să prezinte site-ul?"),
        min_length=40,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=_(
            "Descrie serviciile importante, localitățile vizate și ce acțiune vrei să facă vizitatorii."
        ),
    )
    consent = forms.BooleanField(
        label=_(
            "Sunt de acord ca echipa ServiciiAproape să folosească aceste informații pentru a mă contacta despre planul Partener."
        )
    )
    website = forms.CharField(
        required=False,
        label=_("Website"),
        widget=forms.HiddenInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError(_("Solicitarea nu a putut fi trimisă."))
        return ""

    def clean_brief(self):
        return " ".join(self.cleaned_data["brief"].split())


class ManagedSiteInquiryProcessForm(forms.Form):
    """Collect one explicit operator decision for a Partner inquiry."""

    action = forms.ChoiceField(label="Următoarea stare", widget=forms.RadioSelect)
    internal_note = forms.CharField(
        label="Notă internă",
        min_length=10,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=(
            "Documentați contactul sau decizia fără date bancare, parole ori alte "
            "date personale care nu sunt necesare."
        ),
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că această acțiune actualizează doar urmărirea solicitării; "
            "nu activează abonamentul și nu înregistrează o plată."
        )
    )
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, item, **kwargs):
        """Expose only transitions allowed by the current persisted state."""

        from .managed_site_inquiries import allowed_managed_site_inquiry_transitions

        super().__init__(*args, **kwargs)
        self.fields["action"].choices = tuple(
            (status, ManagedSiteInquiry.Status(status).label)
            for status in allowed_managed_site_inquiry_transitions(item.status)
        )

    def clean_internal_note(self):
        return " ".join(self.cleaned_data["internal_note"].split())


class ProviderServicesCoverageForm(forms.Form):
    """Edit one versioned private declaration without accepting labels from POST."""

    services = forms.MultipleChoiceField(
        label=_("Servicii prestate"),
        choices=tuple((slug, label) for slug, label, _description in CATEGORIES),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Alege cel puțin un serviciu autorizat.")},
    )
    coverage_county = forms.ChoiceField(
        label=_("Județ"),
        required=False,
        choices=(("", _("Alege județul")), *county_choices()),
    )
    coverage_locality = forms.ChoiceField(
        label=_("Localitate"),
        required=False,
        choices=(("", _("Alege întâi județul")),),
    )
    remove_coverage = forms.MultipleChoiceField(
        label=_("Localități de eliminat"),
        required=False,
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(
        self,
        *args,
        authorized_categories=(),
        selected_county="",
        existing_coverage=(),
        **kwargs,
    ):
        """Pin category and removal choices to server-resolved legal facts."""

        super().__init__(*args, **kwargs)
        self.authorized_categories = frozenset(authorized_categories)
        self.fields["services"].choices = tuple(
            (slug, label)
            for slug, label, _description in CATEGORIES
            if slug in self.authorized_categories
        )
        county = (
            (self.data.get("coverage_county", "") if self.is_bound else selected_county)
            or ""
        )
        localities = locality_choices(county)
        self.fields["coverage_locality"].choices = (
            (("", _("Alege localitatea")), *localities)
            if localities
            else (("", _("Alege întâi județul")),)
        )
        self.fields["coverage_locality"].widget.attrs["disabled"] = not localities
        self.fields["remove_coverage"].choices = tuple(
            (
                f"{coverage_county}|{siruta_code}",
                f"{locality_name(coverage_county, siruta_code)} — {coverage_county}",
            )
            for coverage_county, siruta_code in existing_coverage
        )

    def clean_services(self):
        services = frozenset(self.cleaned_data["services"])
        if not services.issubset(self.authorized_categories):
            raise forms.ValidationError(
                _("Poți declara numai servicii care apar în activitățile autorizate ONRC.")
            )
        return services

    def clean(self):
        cleaned = super().clean()
        county = cleaned.get("coverage_county", "")
        locality = cleaned.get("coverage_locality", "")
        if bool(county) != bool(locality):
            self.add_error(
                "coverage_locality", _("Alege județul și localitatea împreună.")
            )
        return cleaned


class ProviderServiceAreaSubmitForm(forms.Form):
    """Submit only the provider's exact currently rendered revision."""

    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class ProviderServiceAreaReviewForm(forms.Form):
    """Collect an explicit private decision and separate safe provider feedback."""

    decision = forms.ChoiceField(
        label="Decizie",
        choices=(
            ("approved", "Aprobă intern"),
            ("changes_required", "Solicită modificări"),
        ),
        widget=forms.RadioSelect,
    )
    internal_note = forms.CharField(
        label="Notă internă",
        min_length=8,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=(
            "Nu include CNP, copii de acte, parole sau alte date care nu sunt necesare."
        ),
    )
    provider_feedback = forms.CharField(
        label="Mesaj pentru furnizor",
        required=False,
        max_length=700,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Obligatoriu când soliciți modificări; nota internă nu este afișată.",
    )
    acknowledgement = forms.BooleanField(
        label=(
            "Confirm că decizia privește exact revizia afișată, nu publică "
            "profilul și nu transformă autorizarea ONRC în dovadă de calitate."
        )
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("decision") == "changes_required"
            and len(" ".join(cleaned.get("provider_feedback", "").split())) < 8
        ):
            self.add_error(
                "provider_feedback", "Explică furnizorului ce trebuie modificat."
            )
        return cleaned
