"""Export only the current discovery projection, never a private database backup."""

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def export_catalogue_snapshot(output: Path, *, counties=None, audit=True) -> dict:
    """Atomically write a historical projection from a consistent read-only source.

    Production publication state is never changed. Non-off provider publications
    are rejected until their separate whitelisted projection can be supported.
    """
    from django.conf import settings
    from django.db import connection, transaction
    from django.utils import timezone, translation
    from services.catalogue_activation import audit_run_for_catalogue, catalogue_state
    from services.locations import read_locations_catalogue, siruta_catalogue_sha256
    from services.models import ProviderPublicationScope
    from services.registry_catalogue import (
        CATEGORY_LABELS,
        _project_listing,
        _visible_records,
        catalogue_categories,
    )

    if not settings.DEBUG:
        raise ValueError('Export requires explicit local development settings, never production.')
    if connection.in_atomic_block:
        raise ValueError('Export must own the source transaction to guarantee read-only consistency.')
    output = output.resolve()
    if output.exists():
        raise ValueError('Output already exists. Export to a new directory; do not overwrite a release.')
    output.parent.mkdir(parents=True, exist_ok=True)
    locations = read_locations_catalogue()
    selected_counties = sorted(locations if counties is None else counties)
    with tempfile.TemporaryDirectory(prefix='catalogue-export-', dir=output.parent) as temporary:
        stage = Path(temporary)
        snapshot = stage / 'catalogue.snapshot'
        with sqlite3.connect(snapshot) as target, transaction.atomic(), translation.override('ro'):
            # This must be the first SQL statement inside the source transaction.
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            if ProviderPublicationScope.objects.exclude(visibility='off').exists():
                raise ValueError('Provider publications exist: registry-only export would not preserve parity.')
            instant = timezone.now()
            metadata = {
                'captured_at': instant.isoformat(), 'localities_sha256': siruta_catalogue_sha256(),
                'categories': sorted(CATEGORY_LABELS), 'counties': {}, 'businesses': 0, 'variants': 0,
            }
            target.executescript('''
                CREATE TABLE metadata (payload TEXT NOT NULL);
                CREATE TABLE listings (
                    county TEXT NOT NULL, siruta TEXT NOT NULL, category TEXT NOT NULL,
                    position INTEGER NOT NULL, business_id INTEGER NOT NULL,
                    has_direct INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (county, siruta, category, position),
                    UNIQUE (county, siruta, category, business_id)
                );
            ''')
            slug_by_label = {str(label): slug for slug, label in CATEGORY_LABELS.items()}
            for county in selected_counties:
                state = catalogue_state(county)
                if state.status != 'active':
                    raise ValueError(f'County is not readable: {county}')
                run = state.run
                if audit:
                    audit_run_for_catalogue(run)
                names = {code: name for code, name, _label in locations[county]}
                exported_categories = catalogue_categories(run)
                metadata['counties'][county] = {
                    'categories': exported_categories, 'snapshot_date': str(run.snapshot.snapshot_date),
                    'dataset_url': run.snapshot.dataset_url, 'license_label': run.snapshot.license_label,
                    'activity_evidence_year': run.activity_evidence_year,
                    'activity_evidence_dataset_url': run.activity_evidence_snapshot.dataset_url if run.activity_evidence_snapshot_id else '',
                    'activity_evidence_license_label': run.activity_evidence_snapshot.license_label if run.activity_evidence_snapshot_id else '',
                }
                # All-category and category-specific evidence are different projections.
                for category in ('', *exported_categories):
                    records, overlay, direct = _visible_records(
                        run=run, county=county, allow_direct_evidence=state.preview,
                        siruta_code=None, category=category, instant=instant,
                    )
                    positions = defaultdict(int)
                    for record in records.iterator(chunk_size=1000):
                        code = record.registered_office_siruta
                        if code not in names:
                            raise ValueError(f'Invalid county-locality pair: {county}/{code}')
                        listing = _project_listing(record=record, county=county, locality_label=names[code],
                                                   overlay_evidence=overlay, direct_by_business=direct)
                        fields = asdict(listing)
                        fields['category_slugs'] = [slug_by_label[str(label)] for label in fields.pop('category_labels')]
                        fields['evidence_retrieved_at'] = listing.evidence_retrieved_at.isoformat() if listing.evidence_retrieved_at else None
                        target.execute('INSERT INTO listings VALUES (?, ?, ?, ?, ?, ?, ?)', (
                            county, code, category, positions[code], listing.business_id,
                            bool(listing.evidence_source_url), json.dumps(fields, ensure_ascii=False),
                        ))
                        positions[code] += 1
                        metadata['variants'] += 1
                        if not category:
                            metadata['businesses'] += 1
            target.execute('INSERT INTO metadata VALUES (?)', (json.dumps(metadata, ensure_ascii=False),))
        with snapshot.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        manifest = {
            'schema': 1, 'purpose': 'private-development-snapshot', 'captured_at': metadata['captured_at'],
            'sha256': digest, 'bytes': snapshot.stat().st_size, 'businesses': metadata['businesses'],
            'variants': metadata['variants'], 'counties': len(metadata['counties']),
        }
        (stage / 'catalogue.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        # Directory rename publishes the data and manifest together, never half a bundle.
        stage.rename(output)
    return manifest


def main():
    """Prepare a portable development artifact using local, unprinted credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--local-container', action='store_true')
    arguments = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    os.environ['CASAMEA_DEBUG'] = '1'
    if arguments.local_container:
        from config.local_catalogue import configure_runserver_catalogue_from_local_container
        configure_runserver_catalogue_from_local_container()
    import django
    django.setup()
    print(json.dumps(export_catalogue_snapshot(arguments.output), indent=2))


if __name__ == '__main__':
    main()
