"""Illustrative catalogue used to validate the marketplace discovery flow."""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Provider:
    """Read-only provider projection for the first product milestone."""

    name: str
    trade: str
    category: str
    locality: str
    county: str
    experience: str
    response: str
    initials: str


CATEGORIES = (
    ("constructii", _("Construcții & renovări"), _("Zidărie, finisaje, acoperișuri")),
    ("electricieni", _("Electricitate"), _("Instalații, reparații și mentenanță electrică")),
    ("instalatii", _("Instalații"), _("Sanitare, termice și alte instalații")),
    ("gradinarit", _("Grădină & exterior"), _("Întreținere și servicii peisagistice")),
    ("curatenie", _("Curățenie"), _("Locuințe, geamuri și după constructor")),
    ("tamplarie", _("Tâmplărie & mobilă"), _("Mobilă la comandă și reparații")),
    ("reparatii", _("Reparații rapide"), _("Intervenții și mentenanță")),
)

PROVIDERS = (
    Provider(
        "Nord Construct", _("Renovări complete"), "constructii", "Cluj-Napoca",
        "Cluj", _("12 ani experiență"), _("Răspunde în aceeași zi"), "NC",
    ),
    Provider(
        "Atelier Lemn Bun", _("Mobilă la comandă"), "tamplarie", "Cluj-Napoca",
        "Cluj", _("9 ani experiență"), _("Răspunde în 2 ore"), "LB",
    ),
    Provider(
        "Verde Urban", _("Amenajări grădini"), "gradinarit", "Cluj-Napoca",
        "Cluj", _("7 ani experiență"), _("Răspunde în aceeași zi"), "VU",
    ),
    Provider(
        "Instal Pro Iași", _("Instalații sanitare"), "instalatii", "Iași", "Iași",
        _("11 ani experiență"), _("Răspunde în 3 ore"), "IP",
    ),
    Provider(
        "Casa Curată", _("Curățenie rezidențială"), "curatenie", "Brașov", "Brașov",
        _("6 ani experiență"), _("Răspunde în aceeași zi"), "CC",
    ),
    Provider(
        "Repar Acum", _("Reparații și mentenanță"), "reparatii", "București",
        "București", _("8 ani experiență"), _("Răspunde în 90 minute"), "RA",
    ),
)
