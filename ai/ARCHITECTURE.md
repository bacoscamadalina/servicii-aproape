# Architecture

## Application boundary

The ServiciiAproape web application lives in the legacy-compatible technical namespace `apps/casa_mea` and uses Django. Server-rendered templates provide a fast, accessible baseline; small progressive-enhancement scripts may improve interactions without becoming the source of truth.

## Invariants

- Search criteria are represented by an explicit county name, a SIRUTA locality code, and an optional category.
- `electricieni` is a narrow discovery specialty over the immutable `instalatii`
  catalogue: only a retained MF CAEN Rev.2 `4321` row qualifies. It never broadens
  plumbing or other installation firms and preserves the source run's audit contract.
  The visitor-facing `instalatii` filter excludes those electrical-only rows; the
  unfiltered catalogue may still show both specialties.
- The county owns the valid locality choice set. A locality submitted for another county is always rejected server-side.
- Progressive enhancement may update the locality select in place, but the server-rendered fallback must expose the same authoritative choices.
- Domain data is accessed through the services application, not embedded into templates.
- Search remains usable without JavaScript.
- Visit proposals are private child records of snapshot-pinned provider leads.
  Owner-scoped proposal creation and customer capability/account-scoped response
  lock the lead row, prevent competing pending proposals, and append a customer
  status event only when a contacted lead's visit is accepted. Retention deletes
  appointment times and notes with the closed request; proposal e-mails include
  only the existing private-workspace route, not project or appointment details.
  Cancellation locks the same lead, records the cancelling party, and releases
  the database-enforced single accepted slot. It reverses `visit_scheduled` to
  `contacted` only when that is the current funnel state; quote and won states
  are independent. Customer export includes cancellation metadata.
- An accepted quote opens one `ProviderWorkOrder` in the same lead-locked
  transaction. The order points to the immutable accepted quote and starts only
  in `awaiting_schedule`. Owner-scoped scheduling and completion lock the lead
  and order, require an expected revision, and append an actor-attributed
  `ProviderWorkOrderEvent`. Cancellation of a future slot clears both interval
  edges and returns the same accepted job to `awaiting_schedule` without changing
  the lead or accepted quote; its event retains the former interval and actor.
  Completion requires a scheduled time no later than
  the current time and also advances the lead funnel; neither scheduling nor
  completion certifies payment, warranty or fiscal issuance. Both direct and
  comparison acceptance use this path. A data
  migration backfills active historical acceptances, while closed-lead retention
  removes these non-fiscal order records before quote anonymization. Fiscal
  documents later require an independent legal-retention boundary.
  The read-only owner work queue derives its status counts and paginated rows
  from active, non-retained leads with work orders; it never infers an execution
  state from the lead funnel or from visit proposals. Its weekly agenda uses
  the same boundary and only `scheduled` work-order start times, filtered by
  the owner's local-week boundaries. A bounded page and per-day counts avoid
  declaring a day empty when additional jobs are on another page.
  The optional scheduled end is owner-declared, must follow the start and stay
  within a bounded 14-day window; every revision records both interval edges.
  Historical schedules retain a null end rather than an inferred duration.
  The weekly agenda annotates each complete interval with an owner-scoped,
  non-retained `Exists` overlap check against all scheduled orders, including
  off-page and adjacent-week starts. Touching endpoints do not overlap. The
  result is an advisory, not a free/busy guarantee without assigned crews.
  A second `Exists` annotation flags complete overlapping intervals assigned
  to the same currently active technician, including off-page jobs. It is a
  warning on the owner calendar, owner request and technician list, not an
  exclusive booking constraint; missing end times remain unknown.
- Every newly sent `ProviderQuote` owns one or more immutable priced
  `ProviderQuoteLine` rows. The submitted total is recomputed server-side from
  quantity × unit price; JavaScript only previews the result. Historical offers
  are migrated as one equivalent line. These rows remain commercial offer detail,
  not VAT treatment or fiscal invoice content, and follow the request's current
  export and retention boundary.
- `ProviderTeamMember` is separate from the one-owner `ProviderMembership`;
  technician membership never grants the owner lead reader. Assignment is
  revisioned on the scheduled work order and every change records old/new
  member and actor. A technician reader filters the active member, active user,
  same profile, scheduled job, won lead and non-retained request at evaluation
  time. Revocation denies the reader immediately, while cancellation clears
  the current assignment and records that removal. Owner-issued invitations
  use a 48-hour bearer token stored only as a digest; sending failure revokes
  the pending record. Acceptance binds a new account or an existing account
  authenticated with the exact invited e-mail, with throttled password checks.
  The technician list is paginated and reveals customer details only for the
  member's own active scheduled jobs. Owner assignment and team
  revocation are separate POST actions with CSRF protection; the technician
  never receives owner lead or billing permissions.
  A technician may POST a revision-checked start only after the scheduled time,
  then a separately confirmed completion. Both lock the current membership,
  lead and order, recheck the exact assignment and append an actor-attributed
  work-order event; completion also advances the lead funnel. `started_at` is
  optional for historical and owner-completed jobs, but once set it prevents
  rescheduling, cancellation and reassignment. Revocation cuts technician
  access even mid-job; the owner retains the existing completion fallback.
- A completed order may own one `ProviderInvoiceDraft`. It is provider-private,
  seeded from the accepted quote and updated only through an owner-scoped,
  revision-checked transaction. It contains no fiscal number, tax calculation,
  issuance state, customer delivery or payment state. Current lead retention
  cascades through this non-fiscal draft; a future issued invoice cannot reuse
  that deletion policy without a separate legal-retention design. The owner's
  billing-preparation list reads only active, non-retained leads and completed
  work orders, with server-side pagination; its saved/pending labels describe
  drafts, never invoice issuance or payment.
- `ProviderBillingIdentity` is a separate private, provider-declared aggregate.
  Its normalized edits lock the active membership and profile, require the
  expected revision and append an actor-attributed snapshot event. It is never
  copied into the public publication snapshot or read as a verified ONRC fact.
  Saving it grants no authority to issue a document; future issued invoices
  must pin validated issuer details at issuance rather than dereference a mutable
  billing profile.
- Demonstration records are clearly marked as illustrative until provider verification and persistence are implemented.
- The ONRC legal registry and an editable marketplace provider profile are separate domains. Imports never overwrite provider-supplied profile, contact, or coverage data.
- Registered-office locality and declared service coverage are separate facts. Only confirmed provider coverage may support the claim that a provider serves a locality.
- A national ONRC snapshot is audited completely before any subset is imported or published. Partial imports never deactivate the last valid catalogue.
- User-facing Romanian text keeps diacritics, English copy is served only through the
  explicit localized route, and form fields have visible labels in either language.
- A declared claimant role and an e-mail confirmation never establish legal authority.
  Every new catalogue claim and unlisted-company intake owns exactly one private,
  bounded PDF/JPEG/PNG representation proof and a versioned transmission declaration.
  The immutable bytes are hashed on intake and revalidated at approval, are available
  only to the dedicated administrator as a forced download, and never enter public
  projections. Conversion moves the same evidence atomically instead of copying it.

## Cloud packaging and private transfer boundary

The repository-root `docker-compose.yml` is a discovery-only exception to the
app-local configuration rule: the user's private cloud reports “No Compose file
or Dockerfile was detected” when these files exist only under `apps/casa_mea`.
The root stack explicitly sets its build context to `./apps/casa_mea` and deliberately
avoids Compose `extends`. It is the persistent managed-cloud development entry:
PostgreSQL and private media use named volumes, while the full application image runs
the complete URLconf and provider workflows. The app-local Compose remains the
independent read-only preview.
Both entry points use the same Dockerfile but intentionally have different state and
route contracts.

The managed cloud rejects `cap_drop` before building. The portable root Compose
therefore avoids host-specific cap_drop,
security_opt, read_only, tmpfs and restart settings live in the explicitly selected
`apps/casa_mea/deploy/compose.local-hardening.yml`, never automatically included.
Only cap_drop is confirmed unsupported; the others are kept out of the portable
contract rather than assuming support. Container isolation/restarts belong to the
managed platform. The image still runs as UID 10001, and its catalogue is root-owned
and not writable by that user; the SQLite immutable reader and GET/HEAD-only routes
do not depend on a writable-rootfs restriction supplied by Compose.

The shared Docker base contains Python application dependencies and root-owned source,
but not the PostgreSQL command-line client. Only the explicit `production` stage adds
the PostgreSQL 17 client needed by backup/restore operations. The default `preview`
stage therefore has a smaller package and attack surface while retaining the complete
embedded SQLite catalogue. Both stages declare UID/GID `10001:10001`, use `/tmp` as the
non-root home/worker directory and receive `SIGTERM` for graceful cloud shutdown.

The `preview` Docker target and app-local Compose package a private, read-only
development snapshot. `config.preview` has a dummy ORM database and an
allowlisted URLconf (home, contextual company detail, locality API, RO/EN), with no
session/authentication/message middleware. Every non-GET/HEAD request is rejected.
The cloud must supply private access controls and HTTPS; noindex is not access control.

The root Compose builds the explicit `managed-cloud` Docker stage, whose build validates
the complete catalogue and its one-to-one workflow identity seed before producing an
image, and selects `config.managed_cloud_development`. Search and contextual
company detail still read the immutable, checksum-pinned SQLite projection, but
accounts, claims, provider drafts, publications and portfolio metadata live in
persistent PostgreSQL. A deterministic gzip seed contains only the exact opaque
business ids and public ONRC registration numbers referenced by that projection.
Startup verifies both artifact checksums and exact identity-set equality, inserts into
an empty identity table, resets the PostgreSQL sequence and refuses partial or divergent
state. It then creates the environment-owned initial administrator once; restarts never
rotate its password. No local accounts, e-mail addresses, claims, audits or private
media are packaged.

The development target accepts the platform's changing HTTP hostname and uses Django's
console e-mail backend, so domain and SMTP ownership are not prerequisites. Confirmation
messages and bearer links therefore appear only in private container logs. This target
must not be mistaken for production. `config.managed_cloud` and the separate production
Compose retain fail-closed HTTPS, exact-domain, legal-identity, strong-secret and SMTP
requirements. In both modes, migrations and seed validation complete before Gunicorn
accepts traffic and database/media volumes survive container recreation.

`deploy/export_preview.py` reads the source in a repeatable-read/read-only PostgreSQL
transaction with one evidence evaluation instant, audits every run, and reuses the
registry whitelist for all-category and per-category variants. It refuses non-off
provider publications rather than silently losing the separate provider reader.
Only the display projection, opaque company id, source metadata and locality pins
enter an indexed SQLite artifact. Accounts, raw addresses, legal identifiers, audit
records and private files never enter that artifact. A directory rename installs
the artifact and its SHA-256 manifest together; existing outputs are refused.

The image opens SQLite immutable/read-only and validates checksum, locality/category
pins, counts and the complete 42-county set at build and worker startup. Pagination
reads only one indexed page. Dates and evidence represent the captured historical
instant, not a claim of ongoing approval; the company-detail dated notice explains
that no updates or revocations propagate. At the user's request, the home page has
no top snapshot banner; result-level provenance remains visible. Production
publication gates remain untouched.

`apps/casa_mea/docker-compose.production.yml` is a single-host deployment, not a public-data
approval mechanism. PostgreSQL 17 and private media use separate named volumes;
only Caddy exposes host ports. Gunicorn runs as UID 10001 with WhiteNoise serving
build-time collected public static assets. The localized home promotion films are
deterministic H.264 assets generated by `tools/generate_home_promo.py` from pinned,
locally rendered neural narration; their small WebP covers provide the no-autoplay and
reduced-motion state, while browser-side control starts sound only after an explicit
visitor action and pauses playback outside the viewport without changing marketplace data.
`config.production` never honors a debug
override or SQLite fallback, requires an explicit hostname/new secret, enforces secure
cookies and HTTPS, and trusts proxy scheme headers only behind the unexposed app port.
The local `runserver` contract is unchanged.

Local catalogue schema maintenance is explicit. Bare `python manage.py migrate`
retains Django's ordinary SQLite development default; it must never discover and mutate
the complete catalogue merely because its Docker container exists. The deliberate
`python manage.py migrate_catalogue` alias first applies the same secret-safe container
discovery as `runserver`, then delegates all remaining arguments to Django's standard
`migrate` command. This prevents the browser and migration commands from silently
addressing different databases while preserving an unmistakable mutation boundary.

The Docker build excludes runtime databases, credentials, raw imports, transfer bundles
and private portfolio content. `deploy/backup_local.py` creates a restricted private
custom-format SQL dump, media archive and checksum/source-pin manifest. Operators must
pause writes for cross-store consistency. A complete backup preserves private accounts,
claims and audit chains; it is never an artifact for public distribution. The deployment
completion marker is omitted on reexport because it is metadata, not a media asset.
Manifest schema 2 additionally pins the regular-file count and total uncompressed media
bytes; schema 1 remains restorable for previously validated bundles.

`deploy/verify_backup.py` is a read-only periodic boundary, separate from restore. It
revalidates hashes and source pins, asks PostgreSQL 17 `pg_restore --list` to parse the
dump, rejects unsafe tar members, compares schema-2 media inventory and optionally fails
on backup age. Its JSON output contains only aggregate sizes/counts and no paths or
record identity. The Compose tool mounts the selected private bundle read-only and has
no dependency on the live database. Verification does not replace an isolated recovery
drill, off-host encrypted storage or a write pause during export.

The explicit `restore` tool checks the exact source artifacts and file hashes, rejects
nonempty targets, serializes itself with a PostgreSQL advisory lock and restores SQL
in one transaction. It stages/validates media and writes its completion marker only
after both stores are installed. This is not a cross-store transaction: a filesystem
failure after SQL commit blocks startup and requires recovery into fresh volumes from
the retained private bundle, never automatic deletion or overwrite. Bootstrap requires
that marker, migrates, audits every current county run using the existing activation
invariants and checks deployment settings. Public readability is reported separately
from persisted row counts and never mutated. Production still hides internal previews.

The runbook documents credential rotation, SMTP, recoverability and the launch boundary.
Production validation used synthetic records only; actual private export, real-domain
TLS/SMTP and cloud deployment remain explicit follow-up operations. The distinct
development artifact contains the sanitized real catalogue, not that private backup.

Production liveness and launch readiness are separate contracts. The Docker healthcheck
proves PostgreSQL and the internal HTTP stack are reachable; it deliberately does not
assert that a commercial launch area is public. The read-only
`audit_production_readiness` command instead requires an explicit, unique set of official
county names and re-audits each current run, public pointer and exact unexpired,
non-revoked approval. It also checks the identity-free public-report triage and
personal-data request audits, pending migrations and the completed-restore marker. Its
deterministic JSON contains only aggregate counts and fails non-zero on drift. It is a
pre-launch/periodic monitor, not bootstrap or liveness, so a failed marketplace gate
cannot prevent staff recovery.

The external post-deploy smoke is a third read-only contract. It starts from one
canonical HTTPS origin, verifies the exact plain-HTTP redirect, performs normally
validated TLS requests with bounded response bodies, and checks Romanian/English home
pages, the admin login, the provider-dashboard authentication redirect, denial of a
generic private-media path, secure CSRF issuance and the production browser-security
headers. It rejects development-preview copy but deliberately does not infer catalogue
publication from an HTTP response; the launch-readiness audit remains authoritative for
that decision. The smoke tool is operator/monitoring input and is never a liveness gate.

Production installs one application-owned browser-security middleware immediately
after Django's security middleware. Every response receives a fixed CSP with same-origin
scripts, styles, forms, fonts and connections; images additionally admit `data:`;
objects and framing are denied; insecure subresources are upgraded. The policy contains
neither `unsafe-inline` nor `unsafe-eval`. A separate Permissions-Policy disables camera,
microphone and geolocation. App-owned templates contain no inline style or script blocks;
custom administrative presentation lives in collected static CSS. The external smoke
requires both headers so a proxy or configuration drift cannot silently remove them.

Production security controls emit operational events through the dedicated
`services.security` logger. Its JSON formatter projects only timestamp, severity,
logger, fixed message, stable event code, authentication scope and exception class;
arbitrary `LogRecord` fields are discarded. Login/reset/claim throttles and claim or
invitation delivery failures therefore support cloud-side alerts without recording
e-mail addresses, usernames, passwords, tokens, provider identities, exception text or
request URLs. Logging is observation only and cannot change an account, claim,
publication or catalogue state.

Production SMTP is a required authorization dependency because claim confirmation,
account invitation and password reset all rely on it. `config.production` refuses an
empty/malformed SMTP hostname or port, missing credentials, an invalid/header-injected
sender, disabled STARTTLS or an unbounded connection attempt. The operator command
`verify_smtp_delivery` audits configuration without opening a connection by default.
Actual delivery requires `--send`, a syntactically valid recipient and the exact
`SEND_SYNTHETIC_SMTP_PROBE` acknowledgement; its bilingual-account workflows are not
invoked and the synthetic message contains no token or domain record. Results and
security events omit the recipient and SMTP exception text.

## Personal-data request boundary

`DataSubjectRequest` is a private administrative register for requests received through
the operator's published privacy contact. Intake stores the minimum contact, channel,
right exercised and bounded summary, pins the recording administrator and calculates a
one-calendar-month initial deadline. The received facts cannot be edited afterward.

Processing is separate from intake and requires a dedicated permission. A stable row is
locked and compared by revision before the fixed transitions from received through
identity confirmation/review to fulfilled or reasoned refusal. Every accepted action
appends a protected event. The single optional extension adds two calendar months to the
initial deadline and records its reason/notification before that initial deadline; it is
not a manually editable date. Closing a request documents the response but never directly
mutates accounts, profiles, claims, reports or publications. Closed-request contact data,
summaries and internal notes join the explicitly acknowledged retention workflow after
the operator-configured period, while status, deadlines, actors and decision history remain.

For an access or portability request already in review, `data_subject_exports.py`
generates a structured UTF-8 JSON projection from the verified exact e-mail and explicit
provider-ownership relations. It excludes credentials, token digests, security counters,
staff identities, moderation notes, unrelated records and binary portfolio media. The
transaction returns bytes directly with a no-store response and persists no export file.
An `export_generated` event advances only the case revision and stores the package
SHA-256; the request remains open until the operator records the response separately.

`audit_data_subject_requests` is the read-only integrity observer for this register. It
starts from every request with a streaming `LEFT JOIN`, reconstructs the status machine
and checks revisions, calendar deadlines, the single extension, workflow chronology,
approved event metadata and export digest notes. Retention-minimized event notes remain
valid only when the parent carries its retention marker. Output is a fixed identity-free
aggregate and drift causes a non-zero exit without any repair or record-level detail.

## Internationalization boundary

Romanian is the unprefixed default language. Every non-admin route included from
`services.urls` is wrapped by Django `i18n_patterns(prefix_default_language=False)`, so
the same surface is available in English under `/en/`. `LocaleMiddleware` derives the
active language from that route prefix; the URL is authoritative and language choice
is not hidden in a cookie or session. Django admin remains outside the localized route
set, unprefixed and Romanian.

The shared language-navigation context projects equivalent Romanian and English URLs
for the current path while preserving the complete query string. Templates use those
links for the RO/EN switch and publish one canonical URL plus reciprocal Romanian,
English and `x-default` alternates. Account, claim and public-report workflow pages are
explicitly `noindex`; localization does not turn private or transitional workflows
into search landing pages.

Source strings use Django gettext and the English catalogue lives in
`locale/en/LC_MESSAGES/django.po`, with its compiled `.mo` artifact available at
runtime. Progressive-enhancement scripts do not contain a parallel translation
system: templates provide translated copy through data attributes and JavaScript only
interpolates runtime values. Stable category slugs, policy versions, audit
acknowledgements, persisted status codes and other machine contracts are never
translated. In particular, `instalatii` remains the stored slug while its English
label is “Plumbing, heating & electrics”. Claim and activation e-mails are explicitly
bilingual so an administrator-triggered message does not depend on an unavailable
recipient-language preference.

## SIRUTA release boundary

The official SIRUTA 2025 locality catalogue remains a generated, read-only JSON
artifact loaded once per process. A future release is generated only as a separate
schema-2 pair. Its provenance pins the exact raw workbook bytes, official URL,
publication and retrieval timestamps, release id, generator policy, generated
catalogue hash and national counts. The generator reads the workbook bytes once and
parses those same bytes.

`audit_siruta_refresh` reads and hashes each generated artifact once, validates the UI
catalogue against the NIV3 hierarchy, requires the complete current county set,
enforces unique child codes and consistent `(county, parent name, parent TIP)` identity
for every SIRSUP, and reports code additions, removals and every semantic field change.
Any byte drift fails by default after printing the deterministic JSON report;
`--report-only` is observation, never approval or installation. Adoption must update
the application release constant, ONRC manifests and reviewed locality aliases,
revalidate provider source pins, stage new runs, and use the existing explicit atomic
activation path. Neither generation nor audit mutates the pinned files, database,
active catalogue or provider state.

The ONRC pipeline starts with a read-only, disk-backed audit of one complete snapshot.
Production persistence uses PostgreSQL staging tables and atomic snapshot activation;
SQLite remains a development and pilot-test database. Django admin provides the first
operational back office before a custom administration interface is justified.

## ONRC staging boundary

`SourceSnapshot` identifies one immutable, manifest-verified national bundle. Each
partial county/category load is owned by an isolated `ImportRun`; staged legal records
and their CAEN/status/category children are unique inside that run, so overlapping
scopes cannot corrupt each other. A pending, running, or failed run is never returned
by the staging-candidate queryset.

SQLite remains the zero-setup development default. Setting `CASAMEA_DB_ENGINE` to
`postgresql` selects the PostgreSQL backend using the `CASAMEA_POSTGRES_DB`,
`CASAMEA_POSTGRES_USER`, `CASAMEA_POSTGRES_PASSWORD`, `CASAMEA_POSTGRES_HOST`, and
`CASAMEA_POSTGRES_PORT` environment variables. PostgreSQL migrations and concurrency
behavior must pass against a real server before any run can be activated.

The PostgreSQL county scopes pin all six curated categories (`constructii`,
`instalatii`, `gradinarit`, `curatenie`, `tamplarie`, and `reparatii`), CAEN
mapping v2, status policy v1, and the SHA-256 of the approved locality-rule
artifact in each scope key.
The customer-facing seventh choice, `electricieni`, is an exact specialty view over
retained `instalatii` rows with MF CAEN Rev.2 `4321`; it does not alter those
six immutable source-scope categories.

Locality reconciliation is exact-first. Approved
hierarchy forms may run only after an exact miss, and each must prove the official
child and parent names, `SIRSUP`, and both TIP values. Neamț additionally admits a
county-scoped spelling alias for Piatra-Neamț and an omonim TIP17/TIP2 town-centre
form; neither rule is applied to another county. The national importer fingerprints
the full firms export once, stores county ownership explicitly in its disk-backed
scratch index, and stages each county under a separate claim and transaction.
Rule loading and hash validation occur once per process, and normalized target-
county forms use a bounded cache; global fingerprinting still covers every firm
before the county optimization so conflicting identities cannot escape detection.

Import execution claims a run through an atomic compare-and-swap UUID token. The
same token is required to finalize or fail it, preventing concurrent workers from
overwriting one another. All staged facts and their children commit atomically,
and a completed run is an idempotent no-op. These guarantees were exercised on a
real PostgreSQL server, including a two-connection concurrency test. They do not
constitute public publication by themselves.

## Catalogue activation and reader

`CatalogueScope` is the single stable, lockable pointer for `(provider, county)`.
It can reference only one complete run for that county, so a category-empty search
cannot merge overlapping runs or duplicate businesses. Pointer changes use
`select_for_update()` and append an immutable `CatalogueActivationEvent` containing
actor, prior/new run, visibility, acknowledgement, and the audited counters. A
same-run activation is an audited no-op; deactivation is explicit and retains all
registry facts and event history.

Before a swap, the activation service recomputes scope provenance and verifies the
succeeded/claim-free run, verified snapshot, status set `{1048}`, CAEN/category
completeness, category scope, county-owned SIRUTA codes, approved locality-match
methods, and quarantine reconciliation. The reader repeats the cheap mutable-state
checks on every lookup and fails closed on drift. It never discovers or substitutes
a newer run automatically.

`internal_preview` is readable only while Django `DEBUG` is enabled.
`public` additionally requires a non-revoked, non-expired `PublicationApproval` for
the exact run. All 42 county runs are active only as internal previews; none has a
publication approval. Production defaults to `DEBUG=false`, so copying this database
or omitting environment configuration cannot expose the preview.

The local Django `runserver` command defaults to `DEBUG=true` only when
`CASAMEA_DEBUG` is not explicitly set, so it can serve the app-owned stylesheet and
dependent-locality JavaScript during development. With no explicit database engine,
`manage.py` also starts the local `casamea-postgres-pilot` Docker container, reads its
connection contract without printing or persisting its password, waits for PostgreSQL,
and refuses to start unless all 42 county pointers are present. This prevents the
previous silent fallback to an empty SQLite catalogue. Setting `CASAMEA_DB_ENGINE`
explicitly always disables the convenience path. Every non-runserver process still
defaults to `DEBUG=false`; an explicit `CASAMEA_DEBUG=0` always wins.

The registry projection is a whitelist: legal name, CAEN-derived category labels,
registered-office locality, ONRC source, snapshot date, and license. It excludes CUI,
EUID, registration number, raw address, registry web field, contacts, ratings,
experience, response time, and service coverage. Queries select only the pointer's
run and exact SIRUTA, deduplicate an empty-category search, order by legal name/id,
and paginate at 20 rows.

The legal-company detail route is deliberately a second active-catalogue read, not
an unrestricted `BusinessIdentity` lookup. It requires the county, SIRUTA locality
and optional category from the originating search, resolves the current scope again,
and reruns both the strict MF and mutable direct-evidence eligibility gates before
projecting a record. Direct evidence expiry, revocation, pointer drift or a mismatched
locality/category therefore turns a previously valid URL into a fail-closed 404. The
opaque database id appears only in the URL; legal identifiers and raw registry fields
remain outside the template context.

## Provider claim initiation

`ProviderClaimRequest` is separate from both imported legal facts and the future
editable provider profile. A claim can start only from a company that the active
catalogue reader resolves for the supplied county, SIRUTA locality and category.
The public form collects first name, last name, username, e-mail, password confirmation,
role, proof of representation and explicit processing consent; none of these fields is
added to the catalogue projection. New requests enter `review_pending` directly and do
not send an e-mail confirmation link. The submitted password is immediately encoded by
Django's configured password hasher; only that hash is retained until approval or
rejection. Intake remains limited to three requests per business/e-mail in 15 minutes.
Legacy token routes remain available only for historical `email_pending` records.

`ProviderRegistrationRequest` is a separate intake for a legal entity absent from the
active catalogue. It stores the declared legal name, normalized CUI/CIF and
trade-register number, exact SIRUTA registered office, account identity, password hash
and consent version. Submission enters administrative review without creating a
`BusinessIdentity`. Staff holding the separate
The unlisted-company intake records one required primary service category as a provider
declaration. It is preserved for audit, shown during registration review and may prefill
the first private service draft after conversion. It never authorizes, reviews or
publishes that service; the current provider-authorization boundary remains authoritative.

`review_provider_registration` permission verifies the legal identity and either
rejects the request or transactionally links/creates the stable `BusinessIdentity`
and produces a `ProviderClaimRequest` carrying the pending account credential. That claim must still pass
the existing representation review before an account exists. This bridge creates no
snapshot, category authorization, profile, service, contact or public visibility.

## Provider approval and private draft access

Administrative decisions are never model-form edits. A staff user with the dedicated
`review_provider_claim` permission records an explicit approve/reject POST, a concise
review basis and the fixed policy acknowledgement. The transaction locks the claim
and business, admits only a `review_pending` request, rejects
self-approval and case-insensitive account collisions, and writes the reviewer,
timestamp and policy version. Rejection creates no marketplace identity.

For a current request, approval atomically creates one `ProviderProfile` draft anchored
to the immutable `BusinessIdentity`, one active Django user with the chosen username,
e-mail and already-hashed password, and one active owner membership. The duplicate hash
is cleared from the claim in the same transaction; rejection also clears it. No account
activation e-mail or link is sent. Historical e-mail-confirmed claims without intake
credentials continue through the legacy invitation path so existing records remain
recoverable. PostgreSQL uniqueness and transaction locks keep profile and owner creation
single-valued under concurrent approval.

Every provider view rechecks exactly one active membership for the authenticated
user and a non-disabled profile. The private form whitelists display name, description,
an optional professional public address, phone, e-mail and website; it cannot write legal identity, ONRC facts or
publication state. The current catalogue reader never reads
`ProviderProfile`, so approval, activation and saving remain private. Provider and Django
Admin login attempts use the same database-backed primitive but distinct HMAC namespaces.
Each normalized account identifier receives five reservations in a 15-minute window
across every application worker; a failure in one domain cannot consume the other
domain's budget. The row stores only an HMAC digest keyed by the application secret; a
successful login deletes its matching budget, while each reservation removes at most
100 keys older than the 24-hour retention boundary. PostgreSQL concurrency tests prove
that simultaneous requests cannot exceed the shared budget. Logout is POST-only, and
revoked provider access fails closed on the next request.

Password recovery reuses Django's time-bound, password-state-bound reset token, but
the request form selects only active users with exactly one active provider ownership
and a draft profile. Known, unknown, inactive and revoked addresses receive the same
public redirect and copy. Sends are bounded to three per normalized e-mail and client
address in 15 minutes through one database row locked transactionally across workers;
the row stores only an HMAC digest keyed by the application secret, never the raw
e-mail or address. Confirmation rechecks the active membership before accepting either
the original token or the session-masked reset URL, so revocation immediately invalidates
an already issued credential. Resetting the password never changes profile, service,
coverage or publication state. Each reservation also removes at most 100 throttle rows
whose windows have been expired for more than 24 hours, keeping cleanup bounded while
preventing indefinite retention of pseudonymous request keys.

Authenticated password maintenance remains inside the same active-membership
authorization boundary. It uses Django's `PasswordChangeForm` to prove the current
credential and apply the configured validators, then calls `update_session_auth_hash`
only for the successful requesting session. Django's password-bound session hashes
therefore preserve that session and invalidate every other existing session without a
custom session registry. The endpoint is CSRF-protected, does not accept a target user,
and never writes profile, service-area, portfolio, moderation or publication state.

Provider service and coverage declarations form a second private aggregate,
`ProviderServiceAreaDraft`, with normalized `ProviderDraftService` and
`ProviderDraftCoverage` children. A single transactional replacement service locks
the active owner and profile, compares an optimistic revision, and validates the
entire proposed set before replacing any child. Categories must be a subset of the
current county pointer's coherent version-1 ONRC base categories; the MF predominant
category is not used as the legal ceiling. Coverage is stored only as exact
`(county, SIRUTA code)` pairs pinned to the SIRUTA 2025 artifact hash. A changed set
increments the revision and invalidates prior review, while an identical POST is a
no-op. Public catalogue readers and reviewed direct evidence do not import or read
these draft tables.

Failure to resolve the current ONRC authorization keeps this editor fail-closed by
default. The only exception is an active account whose approved claim is the exact
claim produced by an audited, converted `ProviderRegistrationRequest` for the same
business. That account may save known service categories and exact county–SIRUTA
coverage as a private draft with no authorization-run pin; the exception begins only
after legal-identity conversion, claim approval and account activation, never during
registration reconciliation. Such a draft cannot be submitted, reviewed or published.
When current authorization becomes available, the provider must save again so the
services are checked against the legal ceiling and the revision receives the current
authorization and SIRUTA pins before submission. An established catalogue provider
whose source later becomes unavailable does not qualify for this exception: the UI
withholds the service-and-coverage form, preserves every saved private child and
revision unchanged, and keeps approval and publication fail-closed until the source can
be validated again. Staff may still record a provider-safe change request on an already
pending submission, as described below, without approving the stale source pins.

Moderation never reviews the mutable aggregate directly. A provider submits the
exact current revision into an immutable `ProviderServiceAreaSubmission` containing
canonical service and coverage snapshots, the authorization and catalogue runs,
the SIRUTA pins, and a contract hash over every semantic input. Submission is
idempotent for the same pending revision. A real later edit supersedes the submission
without erasing its historic decision and resets the draft to `draft`.

Administrative review is a dedicated permission-gated transaction, not generic
model editing. It locks the profile, stable catalogue pointer, draft, and submission;
rechecks the snapshot and hash; and records either `approved` or
`changes_required`. Approval additionally requires the current ONRC authorization
source to match the submitted pins. A change request may still be recorded after
source drift so a pending revision cannot become permanently stuck. Internal review
notes remain staff-only; providers see only the explicitly separated feedback field.
Neither decision publishes the profile, creates verified service evidence, or changes
the public catalogue reader.

## Controlled provider publication

Provider publication is a third aggregate, separate from both the mutable profile and
the approved service-area declaration. `ProviderProfile.public_content_revision`
changes only on a real provider-content or portfolio edit. Private portfolio uploads
accept bounded JPEG, PNG, or WebP input, decode the complete image, apply orientation,
strip metadata through WebP re-encoding, and store an opaque UUID-named derivative
under `MEDIA_ROOT`. There is deliberately no generic `MEDIA_URL`; a protected endpoint
authorizes only the active owner, a publication reviewer, or a currently visible
publication. Database rollback cleanup explicitly removes any derived file already
written to storage.

`ProviderPublicationSubmission` is the immutable whole-profile contract. Schema 3 copies
the public text fields, including the optional normalized professional address, and
exact normalized services, county–SIRUTA coverage pairs,
ordered portfolio captions and asset digests; it also pins the approved
`ProviderServiceAreaSubmission`, authorization run, catalogue run, SIRUTA artifact,
content revision, and a canonical SHA-256 hash. The provider submits through a
CSRF-protected POST. A dedicated staff review transaction locks the profile, active
subscription, source
catalogue pointer, service-area revision, stable `ProviderPublicationScope`, exact
submission, and assets before recording `approved` or `changes_required`. Approval
and visibility require separate review and publication permissions, and the reviewer
cannot be a provider member.

`ProviderSubscription` is a fourth, stable aggregate and not a payment record. Its
initial policy grants fixed 30-day test entitlements only through a staff member with
the dedicated permission. Every activation, extension, and deactivation locks the
profile before its one-to-one subscription, compares an optimistic revision, and
writes an append-only `ProviderSubscriptionEvent`; administrative GET previews never
create state. The active period is required again when approving a publication and on
every public read. Expiry therefore hides professional description, address, contact,
services, coverage, and portfolio without mutating the reviewed snapshot or its
publication event history. Reactivation restores an otherwise valid pointer. No
checkout, invoice, payment-provider identifier, or claim of payment exists in this
test phase.

Address visibility is schema-aware: snapshots created before schema 3 project an empty
address even after the storage migration. The professional address is provider-supplied,
not derived from the ONRC registered office, and remains hidden until the exact schema-3
snapshot passes review and the ordinary publication pointer is visible.

The provider dashboard readiness guide is a read model, not workflow state. Its first
three stages reuse `provider_publication_readiness()`, the same normalized profile,
contact, approved service-submission and active portfolio predicates enforced when a
whole-profile snapshot is created. The fourth stage projects the subscription
entitlement and the fifth projects the current immutable
publication submission and stable visibility scope. No checklist value is persisted,
and every link points to the existing authoritative editor or review surface; a page
refresh therefore reflects moderation, supersession, withdrawal and source-driven
invalidation without a second progress state that could drift.

The stable publication scope has `off`, `internal_preview`, and `public` states and
every pointer change writes an append-only `ProviderPublicationEvent`. A real edit to
profile text, portfolio, services, or coverage immediately turns the pointer off and
supersedes the active publication snapshot. Provider withdrawal can only reduce
visibility. Readers additionally fail closed on disabled ownership, source-pointer
drift, superseded service review, failed or unverified runs, asset revocation or digest
drift or inactive subscription. PostgreSQL concurrency tests prove that two reviewers create one terminal
decision and one activation event.

Discovery keeps provider-declared coverage distinct from registered-office search.
`published_provider_search()` filters normalized publication copies by exact county,
SIRUTA code, and optional category, returns a whitelisted dataclass projection, and
uses an opaque profile UUID for `/furnizori/<uuid>/`. Matching business identities are
excluded from the ONRC branch to prevent duplicates. Internal previews are visible
only with `DEBUG=true` and an active source preview. `public` additionally requires
the exact source `CatalogueScope` to be public with a current, valid, unrevoked and
unexpired `PublicationApproval`; because the 42 current catalogues lack that approval,
real public profile activation is intentionally refused.

## Public provider report intake

A public report is an immutable private record about one exact
`ProviderPublicationSubmission`, never about the provider's mutable draft or profile in
the abstract. The report route accepts the same county, SIRUTA locality and optional
category context as the visible profile, then independently resolves both the public
projection and its visible submission. If either lookup fails because of withdrawal,
source drift, supersession, invalid search context or any other visibility failure, GET
and POST both return 404; a stale or guessed URL cannot create a report.

The public form stores only a reason and a normalized factual description. It does not
ask for or persist the visitor's name, contact details or IP address. For duplicate
prevention, the service stores only an HMAC-SHA-256 of the Django session key, keyed by
the application secret; the raw session key is never retained. A database uniqueness
constraint over the exact submission and this digest admits at most one report per
browser session and publication snapshot, including concurrent retries, without
turning the digest into identity or trust evidence.

Reports are not public and never withdraw a profile automatically. `PROTECT` preserves
their link to the reviewed publication history, while Django admin exposes the queue
through `ReadOnlyRegistryAdmin`: staff may inspect and filter reports but cannot edit or
delete the report itself through the administrative interface.

Each report owns exactly one `PublicProviderReportCase`, created in the same intake
transaction and backfilled by migration `0019` for existing reports. The case is the
stable lock row for operational state only: `new` → `in_review` → `closed`. It carries
an optimistic revision, requires a terminal outcome only when closed, and cannot move
backward. Each accepted transition increments that revision and appends one protected
`PublicProviderReportTriageEvent` containing the prior/new state, terminal outcome when
applicable, normalized internal note, fixed policy version and acknowledgement, actor
and timestamp. The original report and immutable publication submission never become
editable workflow state.

Triage transitions run in atomic services that lock the pre-existing case row and
compare the submitted revision. The reviewer must be active staff with the dedicated
`triage_public_provider_report` permission and must not hold a non-revoked membership
for the reported profile. Every transition revalidates the exact publication-submission
contract hash; failed integrity blocks the ordinary action while preserving the report
facts and event history for separate investigation. Mutations require CSRF-protected
POST, and simultaneous reviewers serialize through the case row so only one transition
can win for a revision.

The incumbent Django-admin triage surface is an Operate view. It presents the exact
immutable report and snapshot facts first—including services, coverage and contract
digest—then current visibility, explicit case state, action and append-only history.
Starting or closing triage has no code path that mutates the report, provider profile,
publication submission or publication scope; there is no automatic withdrawal. Closed
cases are terminal, and an old but intact snapshot remains reviewable as history.

## Public report operational insights

Operational reporting is a dedicated Django-admin view, not an extension of a report
record and not a second workflow. Access requires an active staff account, Django's
built-in `view_publicproviderreport` permission and the separate
`view_public_provider_report_insights` permission. The route accepts only GET; every
other method returns `405 Method Not Allowed`, and the page contains no action,
drilldown or mutation path.

`public_report_insights()` returns an identity-free immutable projection in exactly
four aggregate database queries. The first groups all current cases by state and finds
the oldest report intake timestamp for each state; current queue state is deliberately
all-time. The second groups report intake reasons inside the exact half-open
`[window_start, calculated_at)` interval. The third reads the append-only triage events
in the same interval and derives started transitions, closed transitions and terminal
outcomes. The fourth counts reports without their required case as an all-time integrity
anomaly; the view reports this drift but never repairs it.

The accepted rolling windows are a fixed whitelist of 7, 30 and 90 days, with 30 days
as the fallback for missing or invalid input. The projection deliberately excludes
provider and visitor identities, report descriptions, internal notes, actors,
categories, localities and individual records. This keeps operational counts from
becoming an alternate read path around the private queue.

Migration `0020` adds the custom permission and the
`(created_at, new_state, outcome)` index used by the immutable-event window aggregate.
The Operate surface names all four tables through their section headings, retains
`44px` window controls and collapses its two-column grid without horizontal overflow on
mobile.

## Public report triage integrity audit

`python manage.py audit_public_provider_report_triage` is the read-only operational
check for the persisted report → case → event chain. Its query is rooted in
`PublicProviderReport`, so the generated single aggregate query retains a `LEFT JOIN`
and cannot silently omit a report whose required case is missing. Results stream
through `QuerySet.iterator()` with a bounded chunk size; the audit does not load report
or event identities into its output and performs no repair or mutation.

The audit verifies the complete finite state contract. Every report must have one case;
the case state determines its exact revision, terminal-outcome requirement and expected
event count. Events must contain the exact `new` → `in_review` and optional
`in_review` → `closed` transitions, revisions 1 and 2 respectively, blank outcome on
start and the case's terminal outcome on close. Every event must use an allowlisted
triage policy version, the exact fixed acknowledgement and a whitespace-normalized
internal note of at least eight characters. A closed chain must also preserve strict
lexicographic chronology by `(created_at, id)`.

Output is deterministic, identity-free JSON schema v1 containing only validity, total
report/case/event counts and counts for the fixed anomaly codes. Any non-zero anomaly
count raises `CommandError` after emitting the JSON, producing a non-zero process exit
for monitoring while leaving the database untouched. The check requires no schema
migration. It validates whether the currently persisted rows satisfy the contract; it
cannot cryptographically prove that a row which is valid now was never rewritten in
the past.

## Reported predominant-activity refinement

The national preview uses a versioned second-stage contract to prevent every ONRC
authorized secondary activity from becoming a visible service category. Version-1
scope keys remain byte-for-byte compatible. A version-2 run points with `PROTECT`
to its version-1 county run and to a separately verified MF 2024 financial-statement
snapshot. Each retained business has exactly one privacy-minimized
`PrimaryActivityEvidence` row and exactly one category derived from CAEN Rev.2.

The gate is deliberately fail-closed: the MF 2024 reported predominant activity
must map to a curated ServiciiAproape category and reconcile to an authorized ONRC CAEN in
the same category. Missing filings, conflicting/unknown evidence, unrelated reported
activities, and ONRC authorization mismatches are excluded from the refined preview,
but are described only by aggregate counters. Absence from MF 2024 is never described
as proof that a firm is irrelevant; it particularly affects PFA/II/IF and entities
created after 2024. ONRC authorized activities remain stored as legal facts, while
only the reported predominant activity generates the visible category.

CAEN mapping v2 broadens only the product promise `Tâmplărie & mobilă`: Rev.2
admits building joinery (`1623`), metal doors/windows (`2512`), furniture
manufacturing (`3101`, `3102`, `3109`), installation (`4332`) and repair
(`9524`); Rev.3 uses the corresponding `3100` furniture class. Broad adjacent
manufacturing remains excluded. A mapping change always creates 42 hidden base
runs and 42 hidden MF-refined runs; the unrefined bases can never become active.
Only the fully audited refined runs replace the previous pointers in one atomic
internal-preview swap.

## Reviewed direct-service evidence

The MF predominant-activity gate remains the default source of visible categories.
It is never relaxed globally to recover a false negative. A separate, mutable
`VerifiedServiceEvidence` overlay may recover a business only when a reviewer proves
all three facts from an HTTPS source: the exact legal identity, the exact ServiciiAproape
service category, and an explicitly declared coverage county. Evidence is versioned,
time-bounded, supersedable, and revocable; coverage is stored in a normalized child
table rather than inferred from the registered office.

The overlay begins from the active refined run's hidden version-1 ONRC base. The base
business must still be a succeeded staging candidate with the selected SIRUTA and an
ONRC-authorized CAEN activity mapped to the same category. The reader performs one
stable, deduplicated query over the union of MF-retained and valid reviewed evidence,
then exposes only legal name, registered-office label, category, and a factual source
disclosure. CUI, registration number, reviewer, contact details, and raw capture data
remain private.

Direct evidence is deliberately available only in `internal_preview`. Public readers
exclude it fail-closed because an evidence row can expire or be revoked independently
of a catalogue run; future public use requires a pinned overlay revision and a fresh
publication approval. Expiry and revocation take effect on the next request.

## Administrative provider-account preview

The Django admin provider-profile list exposes a separate read-only account preview
to staff holding `view_providerprofile`. It projects the current private profile,
account state, declared services, exact coverage, portfolio and publication state
without impersonating the owner or creating workflow state. Private portfolio delivery
recognizes the same permission, and the preview GET cannot approve or publish anything.

## Provider availability and preferred contact

Availability and preferred contact are provider-owned draft fields, never ONRC facts.
The write service validates both enumerations and requires `phone`, `email`, or
`website` preference to have the matching public value. A real change advances the
profile content revision and withdraws/supersedes any visible snapshot through the
existing publication boundary. New publication submissions use schema version 2 and
copy both values into the immutable hashed payload. Schema-1 history remains
recalculable without retroactively adding fields to its original contract. Public
projection never interprets migration defaults as historical declarations: schema-1
snapshots render both values as unavailable in that published version.

## Customer-request boundary

`ManagedSiteInquiry` is a separate provider-owned commercial brief for the human-delivered
Partner plan. Only an authenticated active membership may create or view its confirmation;
read-only preview fails closed. Intake locks the provider profile and admits at most three
records per rolling 24 hours. The administrative record carries explicit privacy consent,
while the notification e-mail contains only the record and opaque profile identifiers—not
the free-text brief, website or account address. A successful intake creates no subscription,
entitlement, order or payment. The optional website and brief join the configured,
acknowledged retention workflow; audit/status fields remain identity-free evidence.

`CustomerAccount` is a one-to-one role attached to an active Django user and stores one
unique normalized e-mail plus the privacy policy version accepted at registration. It is
created immediately with a password hash and no mailbox-confirmation capability. Customer
authentication uses the shared durable login throttle under a distinct `customer`
namespace and rejects users that hold active provider ownership.
Customer password maintenance uses the same current-password validation and
session-hash rotation as provider maintenance, but rechecks active customer-only
access on every request. It changes no project ownership or request content;
the browser's current session survives while other password-bound sessions expire.

New authenticated requests retain explicit `customer_account` ownership on both the
parent `ProviderLeadBatch` and each child `ProviderLead`; public form values cannot replace
the account name or e-mail. The portal reads only these ownership edges. It never discovers
requests by e-mail, and its token-free detail routes reuse the same quote, conversation,
review, snapshot and retention contracts as capability-authenticated workspaces. Existing
and anonymous requests keep their expiring capability links unchanged.
The customer dashboard counts each owned, non-retained project once and paginates
standalone leads and comparisons independently, ten per page. Database annotations
derive per-comparison recipient and offer counts; only the selected page may hydrate
private records, and a standalone offer indicator uses existence rather than loading
every historical quote. Each owner-scoped list prioritizes live, unresponded offers;
then it sorts by the latest provider quote or message timestamp using database
subqueries, never by customer message activity or an invented unread flag. Expired,
withdrawn and answered offers do not request action. Invalid page inputs fall back
to Django's bounded page behavior.
The optional `view=offers` dashboard filter is a read-only projection of those same
live-offer predicates. It filters both owner-scoped querysets before their independent
pagination; page links preserve only this validated filter and page numbers. An empty
filtered result is not mistaken for a customer with no projects.

Public-profile measurement is a separate aggregate signal rather than a lead or a trust
claim. The browser submits only enumerated interactions for the exact currently visible
publication snapshot. `ProviderEngagementEvent` retains the immutable snapshot, event kind,
local day and a secret-keyed session digest salted by that day; a uniqueness constraint
counts each event kind at most once per session, snapshot and day. No IP address, user agent,
referrer or raw session key is stored. Owner metrics aggregate all historic snapshots of the
same profile over fixed 7, 30 and 90-day windows.
The acknowledged retention audit counts engagement rows older than the first date in
the longest reporting window. Its apply mode deletes those daily digests in indexed,
bounded batches; page views and normal dashboard reads never trigger deletion.

The pilot dashboard is a GET-only Django-admin projection under the existing private
lead-aggregate permission. It validates county, service and fixed time-window inputs,
uses the ordinary published-provider reader for effective service-area coverage, and
checks the current ONRC scope against its exact legal approval. Internal previews are
counted separately from public profiles. Recent lead aggregates are filtered in the
database by that same county/service pair; a locality without a quote is an operational
signal, not proof that no provider exists. The dashboard neither mutates visibility nor
claims to replace the production readiness audit.
Its funnel counts distinct customer projects within the selected creation window, even
when a batch reaches several providers. Offer and acceptance outcomes are read as of
report time; mean first-offer latency uses the earliest quote per project and leaves
the value blank when no project has received an offer. No search-event attribution or
payment inference is made.

`ProviderLead` is private customer intake pinned to the exact immutable
`ProviderPublicationSubmission` visible when the form was opened. Intake accepts only a
service and SIRUTA locality already present in that snapshot, and the public route becomes
unavailable as soon as the publication or subscription visibility gate closes. Contact
details and project text never enter public projections or operational logs.

Abuse control stores a secret-keyed session digest rather than an IP address and limits
one session to three requests per provider snapshot in 24 hours. The notification e-mail
contains no customer identity or project text; it directs the verified owner to the private
inbox. Delivery failure is recorded without discarding the request.
The general-request form can query an uncached, GET-only, identity-free recipient count
for one validated county/SIRUTA locality/service. It reuses the effective public
publication reader, while the POST resolves every recipient again; the displayed count
is an estimate, never a reservation or an authorization to send to a stale snapshot.
Only staff with provider-lead view access and `retry_provider_lead_notification`
may retry a failed provider
notice from a CSRF-protected confirmation page. The row lock covers the bounded
SMTP send and state transition so concurrent administrators cannot both resend.
Each outcome enters Admin history; a successful notice is never retried. SMTP
can acknowledge delivery before a later error, so the operator must explicitly
accept the possibility of a duplicate before retrying.

Only an active user with exactly one active provider membership may read or update that
provider's leads. Status changes follow a bounded state machine, use optimistic revision
checks under a row lock and append a `ProviderLeadEvent`; private note-only edits may advance
the revision without fabricating a status event. Statistics are aggregate projections over
the same owner-scoped queryset. Completed or declined request identity and free text enter
the explicitly acknowledged retention workflow after the configured period; status and
identity-free funnel history remain for aggregate reporting.
Retention also clears each aged lead's customer-account edge. For comparison projects,
the parent remains accessible while any provider copy is live. Once every child is
retained, the same acknowledged command replaces the parent session and capability
digests, expires that capability and clears parent account ownership. An explicit
retention timestamp and database constraint make the detached parent state auditable;
the project and quote status facts remain for identity-free funnel totals.
`audit_retention_integrity` separately checks retained children and parents for
leftover contact text, messages, quote text, ownership or capability links, plus
parent/child lifecycle contradictions. It streams fixed aggregate findings, changes
nothing and contributes one failure signal to production readiness; it does not
trigger the acknowledged retention mutation.
The same identity-free audit also checks retained provider claims and unlisted-company
registrations for residual contact, credentials and token digests, and for any surviving
binary representation evidence. Schema 2 adds their aggregate totals and anomaly codes;
it never reads or emits the document bytes.
Schema 3 adds retained public reports, personal-data requests and Partner inquiries,
including residual notes in their child events. The acknowledged retention operation
also scrubs public-report triage notes; previously retained closed reports with such
legacy notes become eligible again, while other retained reports remain untouched.

The private inbox derives its fixed status groups from that same owner-scoped queryset and
paginates before building forms, quotes or conversations. Filter names and page numbers are
server-validated navigation state only; customer names, contacts and project text never enter
query strings. Aggregate funnel totals continue to describe the complete retained queue, not
only the visible page, and every successful mutation redirects through the validated filter
state rather than accepting a caller-supplied return URL.
Provider notification links may carry only an opaque lead UUID as `focus`; the inbox
resolves it through the active owner's non-retained queryset, calculates the current
page from the inbox ordering and redirects to the canonical requests/all URL with a
DOM fragment. The redirect restores the exact position even after login. Invalid,
withdrawn or other-owner UUIDs fail closed. The matching DOM anchor also uses that UUID;
the URL is a navigation hint, never a bearer capability. New-request and later
conversation notifications use the same focused destination.

Every new lead receives a random customer capability. Only its secret-keyed digest and
bounded expiry are stored; the raw token exists long enough to build the one-time e-mail
link. The capability resolves exactly one non-retained lead and its response sets
`noindex`, `noarchive`, `no-referrer` and `no-store` behavior. A missing, altered or expired
token fails closed.
If the first customer e-mail fails, the submission response alone exposes the raw
capability as a relative link so the anonymous customer can open or bookmark the
workspace immediately. Both request-form responses use `no-store`, `no-referrer`
and `noindex` headers; a subsequent GET never reconstructs the token from its digest.
Successful deliveries and account-owned projects do not display a capability.
If the initial anonymous customer e-mail fails, staff with the distinct
`retry_customer_access_notification` permission may reissue a single or batch link
from a CSRF-protected Admin confirmation. The request or batch row is locked while a
fresh capability replaces the prior digest and a bounded mail send is attempted; the
original expiry is not extended. The prior link becomes invalid even after an
ambiguous SMTP error, and every retry outcome enters Admin history. Successful,
account-owned, expired and retained requests are ineligible. A failed retry leaves the
request available for another recovery attempt without exposing a raw token in logs.
The two private Admin lists expose a customer-mail state and exact reissue and expired
filters; the batch list also filters mixed active-child delivery states. A broadcast
appears once in the batch list, not once per provider copy; the single-lead filter
excludes batch children. Account-owned and retained requests are outside these
filters, and the state column does not reveal the customer's e-mail address.
The `audit_request_delivery` command projects only aggregate counts for active requests.
It counts unresolved provider sends per provider copy, anonymous customer failures per
standalone request or comparison parent, and distinguishes reissuable from expired
capabilities. Mixed child delivery states are a separate anomaly, never silently
treated as an eligible parent retry. It performs no sends or state changes, emits no
identities or project content, and exits non-zero when any unresolved state remains.
The Admin delivery page reads that same projection under the existing separate
lead-insights permission and model view permission. It is GET-only, uncached, and
links each unresolved state to an exact private filtered queue. Expired and mixed
states can be investigated there but have no automatic resend action. The provider
failed/pending links use an active-only Admin filter that mirrors the audit's
per-copy count and excludes retained requests.

`ProviderQuote` rows are immutable revisions created under the locked lead. Sending a new
revision withdraws the previous unanswered revision, while accept/decline is restricted to
the current unexpired `sent` row. The customer response advances the lead and records a
customer-attributed `ProviderLeadEvent`; provider transitions remain user-attributed.
`ProviderLeadMessage` is append-only and enforces actor presence for provider messages and
absence for capability-authenticated customer messages. E-mail notifications contain only
an activity notice and route, never quote terms or message bodies. Provider-originated
activity on an account-owned lead links to the token-free, owner-checked single or batch
workspace; an anonymous lead receives only a reminder to use its original capability,
never a newly emailed bearer token. Notification subjects describe an update rather than
mislabeling a quote as a new message. Retention invalidates the
capability, deletes message bodies and redacts free-text quote content with the lead.

`ProviderCustomerReview` is a one-to-one child of an eligible lead and belongs to the same
provider profile. Eligibility requires a customer-accepted `ProviderQuote`; possession of a
capability or a provider-side won status is insufficient. Submission normalizes and bounds
the text, minimizes the customer's name, freezes the applicable consent-policy version and
starts in `pending`. A dedicated permission-gated transaction locks the review and records
exactly one final approve/reject decision plus one immutable `ProviderCustomerReviewEvent`.
Moderation cannot edit customer content. Public projection filters only `approved` rows and
uses them as factual customer evidence; reviews do not alter ranking or publication state.
`ProviderCustomerReviewReply` is an immutable one-to-one provider response authorized
through the active membership. It requires an approved review, passes through its own
permission-gated audited moderation event, and is projected publicly only when approved.

## Anonymous provider-shortlist boundary

The provider shortlist is browser-session state, not a marketplace entity and not a new
identity store. It keeps at most six dictionaries containing an opaque provider UUID and
the exact county, SIRUTA locality and category scope used to reach that profile. It stores
no contact data, free text, IP address, ranking signal or copied provider content.

Both the toggle POST and the saved-firms GET resolve every entry through
`published_provider_detail`; therefore the shortlist cannot bypass subscription expiry,
publication withdrawal, source revocation or any other public visibility gate. Invalid or
no-longer-visible entries are pruned during list projection. Toggle redirects are selected
from a fixed internal enum rather than accepting an arbitrary return URL.

Registry-only bookmarks use a separate six-entry session namespace. Their POST toggle
and saved-page projection both pass the business id and exact search scope back through
the active catalogue detail reader. Invalid or withdrawn catalogue records are not
rendered and are pruned; saved ONRC facts are never presented as professional snapshots.

## Local service discovery pages

Category-and-locality landing pages are alternate entry points into the existing search
read model, not a second catalogue. Their route combines stable category identity, readable
county/locality slugs and the official SIRUTA code. The code disambiguates repeated locality
names; any stale readable slug receives one permanent redirect to the canonical spelling,
while an unknown category, county or cross-county code fails closed.

Both the home search and the landing page call the same catalogue projection, so active-run,
direct-evidence, provider-publication and subscription behavior cannot drift between URLs.
Localized canonical and reciprocal `hreflang` links retain the path. A page may be indexed
only when `catalogue_state` resolves a legally approved public scope; demo, missing,
unavailable and internal-preview modes publish both an HTML robots directive and an
`X-Robots-Tag` response header with `noindex`.

## Operational category policy

`ServiceCategoryPolicy` is a stable operational lock for every slug in the fixed
`CATEGORIES` taxonomy. It may order a category, pause its selection by new providers, or
hide it from public discovery. It never edits the label, CAEN mapping, imported
`BusinessCategory`, provider draft, moderation submission, or immutable publication
snapshot. A paused category remains searchable; a hidden category is rejected by public
search and canonical landing pages. Existing valid provider selections remain editable so
an operational decision cannot silently erase provider data.

Only active staff holding `manage_service_category_policy` may mutate the lock. Every
write locks the stable row, compares its rendered revision, requires a bounded reason and
explicit acknowledgement, then appends one protected `ServiceCategoryPolicyEvent`. The
seed migration must exactly match the code-owned taxonomy; a missing or extra policy fails
closed rather than restoring an unsafe default. The explicitly read-only packaged preview
has no operational database by contract and therefore projects the fixed taxonomy as active
without querying or offering category mutations.

## Simulated subscription checkout

The public Partner tier is a configured commercial proposal for human-delivered website
work. It deliberately does not map to `ProviderSubscription`, does not invoke the
simulation and does not create an entitlement or payment-shaped record. The CTA uses the
deployment-owned `CASAMEA_COMMERCIAL_EMAIL`; delivery starts only after an external brief
and calendar confirmation. Domain, licenses, advertising and bespoke development remain
outside its fixed monthly scope.

The temporary provider checkout is an entitlement simulation, not a billing subsystem.
It is enabled only by `CASAMEA_SIMULATED_CHECKOUT_ENABLED`, is unavailable in read-only
preview, requires an authenticated active membership, accepts only the current subscription
revision plus an explicit zero-payment acknowledgement, and never accepts card, billing or
invoice data. A profile with an effective active entitlement returns idempotently, so form
replay cannot extend the period.

The mutation locks the provider profile and subscription, creates exactly one 30-day period,
and appends the ordinary protected subscription event with the distinct `simulated-v1`
policy version and provider actor. This preserves the publication gate while keeping demo
provenance mechanically separable from future processor webhooks. Production payment work
must disable the simulation switch and replace this entry point; it must not reinterpret a
simulated event as payment, receipt or invoice evidence.

## Continuous integration boundary

GitHub requires workflow definitions under the repository-root `.github/workflows/`
directory, so `ci.yml` is a documented exception to the rule that application runtime
configuration belongs under `apps/casa_mea`. It orchestrates the application but owns no
application source or deployment secrets.

CI has two independent fail-closed boundaries. `Django + PostgreSQL` exercises schema
generation and all automated tests against a disposable PostgreSQL 17 service rather
than silently falling back to SQLite. `Docker contracts` validates both portable
Compose discovery paths, validates the production Compose contract with synthetic
values, builds the production and preview stages, and makes real HTTP requests to the
Romanian and English routes of the packaged preview.

The same gate checks the resolved Python environment with `pip check`, imports the
fail-closed production settings under `check --deploy`, asserts the final production
image declares UID/GID `10001:10001`, and proves the live preview returns `405` for a
write attempt. These checks make packaging invariants executable without contacting a
production service or weakening the separate publication boundary.

The independent `Browser E2E` job treats the final preview container as a black box.
Python Playwright drives Chromium at `1280×900` and `390×844`; selectors prefer stable
IDs, roles and domain classes rather than company names or result totals. Journeys cover
dependent locality loading, search/filter query integrity, detail return, pagination,
language-route equivalence and horizontal overflow. Browser console/page errors fail a
journey. Screenshots and traces exist only after failure and contain the already
sanitized preview projection, never account or production-database state.

The workflow grants only `contents: read`, contains no private catalogue, and has no
deployment step. Passing CI proves that the tested revision can be packaged and that
its automated contracts hold; it does not authorize publication or substitute for the
external production database, domain, SMTP, backup, monitoring, or legal approvals.

## Dependency maintenance boundary

Dependabot observes the three executable dependency surfaces: pinned Python packages
under `apps/casa_mea`, Docker base/service images in the same application directory,
and repository-root GitHub Actions. Its version updates target `develop` and are ordinary
reviewed pull requests; there is no auto-merge or deployment authority. Minor/patch
updates are grouped only within one ecosystem, while major updates remain separate.

Release cooldowns reduce exposure to newly published regressions but do not delay
GitHub security updates. Enabling Dependabot alerts and security updates remains an
external repository-owner action. Every proposed update must still pass the PostgreSQL
and Docker CI boundaries before integration.
## Partner inquiry workflow

Partner inquiry progress is an audited, forward-only workflow owned by
`ManagedSiteInquiry`: received → contacted → proposal sent → accepted, with a guarded
close path before acceptance. Every operator transition checks a dedicated permission,
locks the row, compares the expected revision and appends a `ManagedSiteInquiryEvent`.
The provider dashboard exposes only the current status, never operator notes. An accepted
proposal is commercial tracking only: it cannot create a subscription, payment, order or
public entitlement. Retention anonymizes both provider brief text and operator notes while
preserving the minimal state/revision audit trail.
