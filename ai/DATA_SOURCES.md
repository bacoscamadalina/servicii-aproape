# Provider data sources and publication boundary

## Selected official snapshot

The first audit targets the ONRC dataset **Firme înregistrate la Registrul Comerțului
până la data de 08.07.2026** and the nomenclatures published for the same date. The
machine-readable manifest is stored at
`apps/casa_mea/services/data/onrc/manifest-2026-07-08.json`.

The source is licensed CC BY 4.0. Every derived listing must retain attribution, the
snapshot date, and a link to the official dataset. Raw exports are not committed to the
repository.

## Facts we may derive

- Legal name, registration number, CUI/EUID when present, and legal form.
- Registered-office county and locality, without publishing the full street address.
- Official status codes decoded with the nomenclature from the same snapshot.
- Authorized CAEN activities decoded with both code and CAEN version.
- A conservative ServiciiAproape category derived from an explicit, reviewable CAEN rule.

## Facts we must not infer

- Registered office does not mean the company serves that locality.
- Authorized CAEN activity does not prove skill, availability, pricing, or quality.
- An ONRC record is not a verified ServiciiAproape provider profile.
- Phone, email, portfolio, rating, review, and coverage are not invented or harvested
  without a lawful, documented, provider-verifiable workflow.

## Safe rollout

1. Download all three ONRC exports and all nomenclatures from one dated snapshot.
2. Compute local checksums and run `audit_onrc_snapshot`; publish nothing.
3. Review schema, duplicates, orphan relations, CAEN versions, category counts, and
   SIRUTA reconciliation rates.
4. Load a one-county, two-category pilot into PostgreSQL staging.
5. Show unclaimed records only as “firmă cu sediul în localitate”, with ONRC source date.
6. Add service coverage and public contact only through a claimed and reviewed profile.

## First national audit result

The manifest-verified audit completed in 229.56 seconds with a 67,656 KiB peak
resident-memory footprint and a 2,017,665,024-byte scratch database. It found
4,202,257 company rows (4,197,473 unique registration numbers), 19,287,520
authorized-activity rows, and 4,637,408 status rows.
The detailed machine-readable result lives in `ai/reports/onrc-audit-2026-07-08.json`.

The snapshot is not clean enough for direct publication: 1,161 repeated registration
numbers have identical payloads, 3,558 have conflicting payloads, 65 company rows are
invalid, 35 activity rows are structurally invalid, and 133 activities reference CAEN
keys absent from the same-date nomenclature. Conflicting and invalid rows must remain
quarantined during staging. After correctly treating literal quotes in ONRC company
names as data rather than CSV syntax, the verified relationships contain no orphan
activity or status rows.

The conservative reconciliation over coherent unique companies counted 773,651 exact
SIRUTA matches, 248 ambiguous matches, 3,419,854 unmatched offices, and 162 records
with a missing county or locality. The low exact-match rate blocks locality publication
and requires a versioned alias/review table rather than aggressive string guessing.

The verified unique-company supply is 364,234 construction, 270,536 installation,
212,751 carpentry/furniture, 92,380 cleaning, 46,889 gardening, and 21,598 repair
companies before applying a final status/publication policy. The CAEN rules remain
curated product rules; legacy CAEN versions 1998/2003 are counted but deliberately not
auto-mapped.

## Status eligibility for internal staging

Status policy v1 is approved only as a technical gate for PostgreSQL staging. A coherent
firm is eligible only when its complete official status set is exactly `1048 — funcțiune`.
Any set containing `1084 — radiată` is excluded; `1048` combined with another status
requires review; every other set remains quarantined. This conservative policy admits
1,571,865 firms, excludes 2,170,374 radiated firms, sends 206,453 mixed-status firms to
review, and quarantines 245,223 firms without `1048`.

The audit accounts separately for all 4,633,692 status memberships linked to coherent
firms and the 3,713 memberships linked to 3,558 conflicting firms. Nothing is silently
dropped. The complete 2,452-combination audit is summarized in
`ai/reports/onrc-status-policy-2026-07-08.json`. Status eligibility does not prove that
a firm trades, is available, is competent, has public contact details, or serves its
registered-office locality.

## Locality reconciliation work

The privacy-minimized candidate inventory contains 29,474 normalized combinations of
country, county, locality, and sector. It contains no company identity, CUI, street
address, or contact data. Country is part of every decision, so a foreign office cannot
receive a Romanian SIRUTA code through a coincidental name match.

Four explicit administrative-form rules are hierarchy-validated: `Municipiul X`,
`Oraș X`, `Comuna X`, and `Sat X, Comuna/Oraș/Municipiul Y`. A target is proposed only
when child name, parent name, official `SIRSUP`, locality TIP, and parent TIP all match
inside the same county. Name uniqueness alone is never accepted. Exhaustive independent
comparison of all 25,053 proposals against the official SIRUTA workbook found zero
differences. If separately approved for application, they would raise deterministic
matches from 773,651 to 3,746,109 coherent unique firms while leaving 447,395 unresolved.
The four rules were subsequently approved only for the reviewed internal pilot and
are now gated by explicit `application_approved` flags. The importer remains
exact-first and will not use any proposed or merely hierarchy-validated rule. This
approval does not publish records or establish service coverage. The summary lives in
`ai/reports/onrc-locality-reconciliation-2026-07-08.json`.

Before a public launch, a Romanian legal/privacy review must confirm the transparency,
rectification, objection/delisting, retention, and PFA/II/IF handling process.

## Pilot staging foundation

The database schema isolates every county/category pilot under an `ImportRun` owned by
one verified `SourceSnapshot`. Stable business identity uses only the ONRC registration
number; CUI, EUID, legal facts, registered-office locality, statuses, CAEN activities,
and derived categories remain snapshot facts. Runs pin the CAEN mapping hash/version,
status-policy version, locality policy, and approved locality-rules hash in a
deterministic scope key.

A stable activation pointer exists per provider/county. It can select only a succeeded
run backed by a verified snapshot, exact or hierarchy-approved SIRUTA, and the approved
technical status. Internal preview and public visibility remain separate states.

The first real PostgreSQL pilot for Iași, `constructii` and `instalatii`, succeeded on
21 August 2026. The exact-only audit run intentionally staged zero records because
ONRC expresses the county's offices through administrative forms such as
`Municipiul Iași` and `Sat X, Comuna Y`. The separately pinned hierarchy-rule run
staged 9,895 coherent records with exact status set `{1048}`, 64,720 versioned CAEN
memberships, and 15,550 category memberships. There are 8,519 businesses in
construction and 7,031 in installations; overlap is expected. One conflicting
candidate is retained as a privacy-minimized quarantine record. The rerun was a
no-op with identical counters. Details and reconciliations are in
`ai/reports/onrc-pilot-iasi-2026-07-08.json`.

The Iași catalogue is connected to the UI only through an explicitly activated
`internal_preview` pointer. It shows 20 privacy-minimized rows per page and labels
every row `Sediu social`, with ONRC source/date/license and a registered-office versus
coverage disclosure. Counties without a pointer may still show clearly marked
demonstration records; a stale or unavailable active pointer never falls back to demo.

There is no `PublicationApproval` for either current county run. Internal preview is readable only
with Django `DEBUG` explicitly enabled, while the production-safe default is off.
Public activation remains blocked until a documented, versioned, revocable legal/
privacy publication review exists for the exact run. Provider contact and service
coverage remain separate future workflows.

The first complete Neamț pilot for the same two categories was completed on 21 August 2026 as
`ImportRun 4`. A preliminary run exposed a material spelling gap between ONRC
`Municipiul Piatra Neamț` and SIRUTA `Piatra-Neamț`. The final run pins a reviewed,
county-scoped comparison alias and a Neamț-only `Loc. X, Oraș X` hierarchy rule.
The review accepted 29,968 coherent candidate matches and rejected 155 satellite-town
forms; details are in `ai/reports/onrc-locality-rules-neamt-2026-08-21.json`.

That Neamț run staged 4,229 eligible businesses, 23,323 CAEN memberships and
6,284 category memberships. Piatra-Neamț has 1,062 staged businesses, Târgu Neamț
202, Bicaz 52, and Roznov 101. The run was an `internal_preview` until superseded,
had no publication approval, and is documented historically in
`ai/reports/catalogue-preview-neamt-2026-08-21.json`.

Both county catalogues were then rebuilt as complete three-category scopes after the
curated CAEN `8130 — Activități de întreținere peisagistică` gardening category was
added to the pilot scopes. `ImportRun 5` for Iași staged 10,267 distinct firms,
including 1,169 gardening firms (612 in Iași municipality). `ImportRun 6` for Neamț staged
4,395 distinct firms, including 401 gardening firms (99 in Piatra-Neamț). Both reruns
were idempotent and were atomically swapped into `internal_preview`; details are in
`ai/reports/catalogue-preview-gardening-iasi-neamt-2026-08-21.json`.

The historical complete scopes were `ImportRun 7` for Iași and `ImportRun 8` for Neamț.
They add the already curated `curatenie`, `tamplarie`, and `reparatii` categories
without changing CAEN mapping v1. Iași now stages 11,622 distinct firms and 25,259
category relations; Neamț stages 5,013 distinct firms and 9,776 category relations.
Both imports reran as no-ops before an atomic `internal_preview` pointer swap. The
six-category counts and browser verification are in
`ai/reports/catalogue-preview-all-services-iasi-neamt-2026-08-21.json`.

On 21 August 2026 the same pinned six-category contract was extended to every
Romanian county. The importer scanned the national bundle once, retained global
conflict detection, staged each county in its own PostgreSQL transaction, and then
swapped all 40 new county pointers atomically into `internal_preview`. At that stage,
the 42 preview scopes contained 275,679 distinct registered businesses. No scope was
public and no publication approval was created. Full counts
and validation are in `ai/reports/catalogue-preview-national-2026-08-21.json`.

On 24 August 2026 CAEN mapping v2 corrected the `Tâmplărie & mobilă` taxonomy.
The previous mapping covered installation/repair but omitted firms whose reported
predominant activity is furniture or joinery manufacturing. The new conservative
set admits Rev.2 `1623`, `2512`, `3101`, `3102`, `3109`, `4332`, `9524` and
Rev.3 `1623`, `2512`, `3100`, `4332`, `9524`; nearby broad classes such as
`1629`, `2223`, `2511`, `3103`, and `9529` remain excluded.

All 42 ONRC bases were rebuilt as hidden runs and then refined again through the
same fail-closed MF 2024 gate. The shadow partition closes exactly:
286,973 candidates = 72,880 retained + 622 mapped-but-not-authorized + 114,045
without MF filing + 99,426 with an unrelated reported activity. The 42 refined
runs were swapped atomically into `internal_preview`; no publication approval was
created. Săbăoani now returns `OASE ART S.R.L.` once for `tamplarie`, based on
reported CAEN Rev.2 `3109`, while transport CAEN `4941` remains excluded. Build
provenance and the CAS plan are fixed in
`ai/reports/catalogue-primary-activity-v2-build-2026-08-24.json` and
`ai/reports/catalogue-primary-activity-v2-activation-plan-2026-08-24.json`.
The completed swap and end-to-end verification are recorded in
`ai/reports/catalogue-primary-activity-v2-activation-2026-08-24.json`.

## Reviewed direct-service evidence pilot

The fail-closed MF gate can omit a real service when that service is legally
authorized but is not the firm's MF-reported predominant activity. This is treated as
a source limitation, not solved by exposing every secondary CAEN activity. A separate
reviewed overlay requires exact evidence of legal identity, category, and declared
coverage, while preserving the same ONRC status, authorization, and SIRUTA gates.

For Săbăoani gardening, the official Nacela Robu service page identifies `Nacela Robu
SRL`, describes tree cleaning, pruning, felling, deforestation, and hedge maintenance,
and explicitly declares coverage in Neamț, Iași, Bacău, Suceava, and Vaslui. The page
was retrieved on 24 August 2026; the private audit capture has SHA-256
`74b8e2a087467833149abbc4cb156575fc4d5a482673d0cbb71bc7e8a7f405c8`. The public
card links to the source and states only that the site declares those services and
coverage. It does not claim ServiciiAproape verification of competence, availability, or
quality.

The evidence is versioned, revocable, and expires on 20 February 2027 unless renewed
after another review. It is active only in internal preview and does not modify the MF
snapshot, ONRC facts, or public catalogue approval. The durable implementation and
validation record is `ai/reports/verified-service-evidence-nacela-robu-2026-08-24.json`.
