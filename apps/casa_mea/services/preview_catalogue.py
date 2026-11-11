"""Historical, privacy-minimized catalogue reader; never connects to the source DB."""

from contextlib import closing
from datetime import date, datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator

from .locations import read_locations_catalogue, siruta_catalogue_sha256
from .registry_catalogue import (
    CATEGORY_LABELS, RegistryCompanyDetail, RegistryListing, RegistrySearchPage,
)


# Older immutable exports retain electrical rows in the broad installations
# variant. Filter by the already-whitelisted display slug at read time so both
# existing snapshots and freshly exported ones use the same distinct service.
INSTALLATIONS_SCOPE_CLAUSE = (
    "EXISTS (SELECT 1 FROM json_each(listings.payload, '$.category_slugs') "
    "WHERE value = 'instalatii')"
)


@lru_cache(maxsize=2)
def read_snapshot_metadata(path: str, require_complete: bool = True) -> dict:
    """Validate once per immutable image, refusing missing or mismatched artifacts."""

    snapshot = Path(path)
    try:
        manifest = json.loads(snapshot.with_suffix('.json').read_text(encoding='utf-8'))
        if manifest['schema'] != 1 or manifest['purpose'] != 'private-development-snapshot':
            raise ValueError('Unsupported snapshot contract')
        with snapshot.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest != manifest['sha256']:
            raise ValueError('Snapshot checksum mismatch')
        with closing(sqlite3.connect(f'{snapshot.resolve().as_uri()}?mode=ro&immutable=1', uri=True)) as db:
            metadata = json.loads(db.execute('SELECT payload FROM metadata').fetchone()[0])
            variants = db.execute('SELECT count(*) FROM listings').fetchone()[0]
            businesses = db.execute("SELECT count(*) FROM listings WHERE category = ''").fetchone()[0]
            actual_counties = {row[0] for row in db.execute('SELECT DISTINCT county FROM listings')}
        if any((manifest[key] != metadata[key] or metadata[key] != actual)
               for key, actual in (('variants', variants), ('businesses', businesses))):
            raise ValueError('Snapshot row counts mismatch')
        if manifest['counties'] != len(metadata['counties']):
            raise ValueError('County count mismatch')
        if require_complete and (
            set(metadata['counties']) != set(read_locations_catalogue())
            or actual_counties != set(metadata['counties'])
            or any(sorted(source['categories']) != sorted(CATEGORY_LABELS)
                   for source in metadata['counties'].values())
        ):
            raise ValueError('National catalogue is incomplete')
        if metadata['localities_sha256'] != siruta_catalogue_sha256():
            raise ValueError('Locality catalogue differs from snapshot')
        if metadata['categories'] != sorted(CATEGORY_LABELS):
            raise ValueError('Category contract differs from snapshot')
        if metadata['captured_at'] != manifest['captured_at']:
            raise ValueError('Snapshot date mismatch')
        return metadata
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise ImproperlyConfigured(
            'Development catalogue missing or invalid. Rebuild with the prepared '
            'deploy/preview/catalogue.snapshot and catalogue.json; no live DB fallback is allowed.'
        ) from exc


def snapshot_metadata() -> dict:
    """Read metadata for the explicitly configured immutable snapshot."""

    return read_snapshot_metadata(str(settings.PREVIEW_CATALOGUE_PATH),
                                  getattr(settings, 'PREVIEW_REQUIRE_COMPLETE', True))


def catalogue_state(county: str):
    """Return only captured counties; an absent county never becomes demo data."""

    source = snapshot_metadata()['counties'].get(county)
    return SimpleNamespace(
        status='active' if source else 'unavailable', preview=True,
        run=SimpleNamespace(categories=source['categories']) if source else None,
    )


def _source(county: str) -> dict:
    """Project captured provenance with native dates for the shared templates."""

    source = snapshot_metadata()['counties'][county]
    return {
        key: date.fromisoformat(value) if key == 'snapshot_date' else value
        for key, value in source.items() if key != 'categories'
    }


def _listing(payload: str) -> RegistryListing:
    """Translate stable category slugs at request time, not at export time."""

    fields = json.loads(payload)
    fields['category_slugs'] = tuple(fields['category_slugs'])
    fields['category_labels'] = tuple(CATEGORY_LABELS[slug] for slug in fields['category_slugs'])
    retrieved = fields['evidence_retrieved_at']
    fields['evidence_retrieved_at'] = datetime.fromisoformat(retrieved) if retrieved else None
    return RegistryListing(**fields)


def registry_search(*, county, siruta_code, category, page_number, page_size=20, **_unused):
    """Read one indexed page; never materialize the national catalogue per request."""

    source = _source(county)
    uri = f'{Path(settings.PREVIEW_CATALOGUE_PATH).resolve().as_uri()}?mode=ro&immutable=1'
    parameters = [county]
    clauses = ['county = ?']
    if siruta_code:
        clauses.append('siruta = ?')
        parameters.append(siruta_code)
    clauses.append('category = ?')
    parameters.append(category)
    if category == 'instalatii':
        clauses.append(INSTALLATIONS_SCOPE_CLAUSE)
    where = ' AND '.join(clauses)
    parameters = tuple(parameters)
    with closing(sqlite3.connect(uri, uri=True)) as db:
        total = db.execute(f'SELECT count(*) FROM listings WHERE {where}', parameters).fetchone()[0]
        page = Paginator(range(total), page_size).get_page(page_number)
        rows = db.execute(
            f'SELECT payload FROM listings WHERE {where} ORDER BY position LIMIT ? OFFSET ?',
            (*parameters, page_size, (page.number - 1) * page_size),
        ).fetchall()
        has_direct = db.execute(
            f'SELECT 1 FROM listings WHERE {where} AND has_direct = 1 LIMIT 1', parameters,
        ).fetchone() is not None
    page.object_list = [_listing(row[0]) for row in rows]
    return RegistrySearchPage(page=page, total=total, contains_direct_service_evidence=has_direct, **source)


def registry_company_detail(*, county, siruta_code, category, business_id, **_unused):
    """Require the captured county and optional locality context for a business id."""

    source = _source(county)
    uri = f'{Path(settings.PREVIEW_CATALOGUE_PATH).resolve().as_uri()}?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        parameters = [county]
        clauses = ['county = ?']
        if siruta_code:
            clauses.append('siruta = ?')
            parameters.append(siruta_code)
        clauses.extend(('category = ?', 'business_id = ?'))
        parameters.extend((category, business_id))
        if category == 'instalatii':
            clauses.append(INSTALLATIONS_SCOPE_CLAUSE)
        row = db.execute(
            f"SELECT payload FROM listings WHERE {' AND '.join(clauses)}",
            tuple(parameters),
        ).fetchone()
    return RegistryCompanyDetail(listing=_listing(row[0]), **source) if row else None


def preview_context(request):
    """Expose only the dated read-only contract to shared discovery templates."""

    return {'read_only_preview': True, 'preview_captured_at': datetime.fromisoformat(snapshot_metadata()['captured_at'])}


class ReadOnlyPreviewMiddleware:
    """Reject writes globally and mark all preview responses as non-indexable."""

    def __init__(self, get_response):
        """Validate the packaged snapshot before accepting the first request."""
        snapshot_metadata()
        self.get_response = get_response

    def __call__(self, request):
        """Allow safe reads only; there are no sessions, accounts or live updates."""
        from django.http import HttpResponseNotAllowed

        response = (self.get_response(request) if request.method in ('GET', 'HEAD')
                    else HttpResponseNotAllowed(['GET', 'HEAD']))
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response
