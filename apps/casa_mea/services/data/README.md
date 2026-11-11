# Romanian locality catalogue

`localities.json` is generated from **SIRUTA S1 2025**, published by Romania's National Institute of Statistics on data.gov.ro.

- Source: https://data.gov.ro/en/dataset/siruta-2025/resource/0ab29d86-302c-4cfa-b9b9-fd5c7ff90710
- Direct resource: https://data.gov.ro/dataset/fcba1a54-cffd-422c-b3ac-920f63564085/resource/0ab29d86-302c-4cfa-b9b9-fd5c7ff90710/download/siruta_s1_2025.csv
- License: Creative Commons Attribution 4.0
- Included hierarchy level: `NIV = 3` (localities)
- Generated entries: 13,755 localities in 42 county-level groups, including Bucharest

The downloaded resource is an Excel workbook even though its public filename ends in
`.csv`. Check for a new official S1 release once per year and again before adopting a
new ONRC snapshot; never replace the checked-in JSON files directly.

Generate a candidate outside `services/data/` and pin its complete provenance:

```bash
python tools/build_locations_catalog.py /path/to/siruta.xlsx /tmp/localities.json \
  --hierarchy-destination /tmp/localities_hierarchy.json \
  --release-id 2026 \
  --source-url https://data.gov.ro/.../siruta_s1_2026.xlsx \
  --published-date 2026-01-15 \
  --retrieved-at 2026-08-28T12:00:00+03:00
```

Schema 2 records the raw workbook SHA-256, official URL, publication/retrieval dates,
generator policy, generated catalogue hash and exact counts. Audit that pair against
the pinned release:

```bash
python manage.py audit_siruta_refresh \
  /tmp/localities.json /tmp/localities_hierarchy.json
```

The command prints the complete deterministic report and exits non-zero on any byte
or semantic change. `--report-only` permits exporting the report with exit zero, but
does not install or approve the candidate. Adoption still requires review of additions,
removals, names, display labels, TIP and SIRSUP ownership; updating
`SIRUTA_CATALOGUE_VERSION`; regenerating ONRC manifests and locality-alias review;
revalidating provider source pins; staging new runs; and only then an explicit atomic
activation. The current active files are never modified by the generator or audit.
