"""Parse a narrow owner command into an editable offer, without external AI calls.

The parser never writes data. An offer still requires the existing, explicit
provider form submission and its owner/lead authorization checks.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _


@dataclass(frozen=True)
class QuoteDraft:
    customer_name: str
    summary: str
    amount_ron: Decimal


_QUOTE_COMMAND = re.compile(
    r"^\s*(?:Creează\s+ofertă\s+pentru|Create\s+(?:an?\s+)?offer\s+for)\s+"
    r"(?:(?:dl|dna|Mr|Ms)\.?|domnul|doamna)\s*"
    r"(?P<name>[^:]{2,120}):\s*(?P<summary>[^:]{5,2000}?),\s*"
    r"(?P<amount>(?:\d{1,3}(?:[., ]\d{3})+|\d+)(?:[.,]\d{1,2})?)\s*(?:lei|RON)\.?\s*$",
    re.IGNORECASE,
)
_OUTSTANDING_COMMANDS = {
    "cine nu mi-a plătit?",
    "cine nu mi-a platit?",
    "cine nu mi-a plătit",
    "cine nu mi-a platit",
    "who has not paid me?",
    "who hasn't paid me?",
}


def owner_command_kind(command: str) -> str:
    """Classify only the two supported, explicit command families."""

    normalized = " ".join(command.strip().split()).casefold()
    return "outstanding" if normalized in _OUTSTANDING_COMMANDS else "quote"


def parse_quote_command(command: str) -> QuoteDraft:
    """Extract only the supported quote syntax; never infer missing terms."""

    match = _QUOTE_COMMAND.fullmatch(command)
    if not match:
        raise ValueError(
            _("Folosește formatul: «Creează ofertă pentru dl. Ionescu: montare 3 aparate AC, 7.500 lei». ")
            + _("Durata și valabilitatea se completează înainte de trimitere.")
        )
    name = " ".join(match.group("name").split()).strip(" .")
    summary = " ".join(match.group("summary").split()).strip(" .")
    if not name or len(summary) < 20:
        raise ValueError(_("Numele clientului și descrierea lucrării trebuie să fie complete."))
    try:
        raw_amount = match.group("amount")
        fraction = re.search(r"[.,](\d{1,2})$", raw_amount)
        whole = raw_amount[:fraction.start()] if fraction else raw_amount
        amount = Decimal(whole.replace(".", "").replace(",", "").replace(" ", ""))
        if fraction:
            amount += Decimal(f"0.{fraction.group(1)}")
    except InvalidOperation as error:
        raise ValueError(_("Valoarea ofertei nu este validă.")) from error
    if not Decimal("1") <= amount <= Decimal("99999999"):
        raise ValueError(_("Valoarea ofertei trebuie să fie între 1 și 99.999.999 lei."))
    return QuoteDraft(customer_name=name, summary=summary, amount_ron=amount)
