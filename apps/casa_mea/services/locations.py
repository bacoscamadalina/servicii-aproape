"""Read-only access to Romania's official county-locality catalogue."""

import json
import hashlib
from functools import lru_cache
from pathlib import Path


CATALOGUE_PATH = Path(__file__).with_name("data") / "localities.json"
SIRUTA_CATALOGUE_VERSION = "2025"


@lru_cache(maxsize=1)
def siruta_catalogue_sha256() -> str:
    """Return the pinned content identity used by private coverage drafts."""

    return hashlib.sha256(CATALOGUE_PATH.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def read_locations_catalogue() -> dict[str, list[list[str]]]:
    """Read and cache the generated SIRUTA catalogue for this process."""

    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


def county_choices() -> tuple[tuple[str, str], ...]:
    """Return alphabetized county choices from the authoritative catalogue."""

    return tuple((county, county) for county in read_locations_catalogue())


def locality_choices(county: str) -> tuple[tuple[str, str], ...]:
    """Return SIRUTA code and disambiguated label choices for one county."""

    return tuple(
        (code, label)
        for code, _name, label in read_locations_catalogue().get(county, ())
    )


def locality_name(county: str, siruta_code: str) -> str:
    """Resolve a selected SIRUTA code to its display name within a county."""

    return next(
        (
            name
            for code, name, _label in read_locations_catalogue().get(county, ())
            if code == siruta_code
        ),
        "",
    )


def locality_code(county: str, name: str) -> str:
    """Resolve a legacy locality-name query to its first matching SIRUTA code."""

    return next(
        (
            code
            for code, locality, _label in read_locations_catalogue().get(county, ())
            if locality.casefold() == name.casefold()
        ),
        "",
    )
