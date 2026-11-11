"""Curated CAEN rules for direct home services offered through ServiciiAproape."""

import hashlib
import json


CAEN_VERSION_LABELS = {
    "0": "1998",
    "1": "2003",
    "2": "2008",
    "3": "2025",
}

# Only direct services are admitted. Retail, manufacturing, property development and
# other adjacent activities stay excluded until a product review explicitly adds them.
CAEN_CATEGORY_CODES = {
    "2": {
        "constructii": {
            "4120", "4311", "4312", "4313", "4331", "4333", "4334",
            "4391", "4399",
        },
        "instalatii": {"4321", "4322", "4329"},
        "gradinarit": {"8130"},
        "curatenie": {"8121", "8122", "8129"},
        # Category promise includes made-to-order furniture and building joinery,
        # not only installation/repair. Broad plastics manufacturing stays excluded.
        "tamplarie": {"1623", "2512", "3101", "3102", "3109", "4332", "9524"},
        "reparatii": {"9521", "9522"},
    },
    "3": {
        "constructii": {
            "4100", "4311", "4312", "4313", "4331", "4333", "4334",
            "4335", "4341", "4342", "4399",
        },
        "instalatii": {"4321", "4322", "4323", "4324"},
        "gradinarit": {"8130"},
        "curatenie": {"8121", "8122", "8123"},
        "tamplarie": {"1623", "2512", "3100", "4332", "9524"},
        "reparatii": {"9521", "9522"},
    },
}


def _build_category_index() -> dict[tuple[str, str], str]:
    """Build a deterministic reverse index and fail fast on overlapping rules."""

    index: dict[tuple[str, str], str] = {}
    for version, categories in CAEN_CATEGORY_CODES.items():
        for category, codes in categories.items():
            for code in codes:
                key = (version, code)
                if key in index:
                    raise ValueError(
                        f"CAEN {code} v{version} apare în categoriile "
                        f"{index[key]} și {category}"
                    )
                index[key] = category
    return index


CAEN_CATEGORY_INDEX = _build_category_index()
CAEN_MAPPING_VERSION = "2"
CAEN_MAPPING_HASH = hashlib.sha256(
    json.dumps(
        {
            version: {
                category: sorted(codes)
                for category, codes in sorted(categories.items())
            }
            for version, categories in sorted(CAEN_CATEGORY_CODES.items())
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


def category_for_caen(code: str, version: str) -> str:
    """Return the one ServiciiAproape category for an explicitly admitted CAEN activity."""

    normalized_code = code.strip().zfill(4)
    return CAEN_CATEGORY_INDEX.get((version.strip(), normalized_code), "")
