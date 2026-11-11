# ServiciiAproape — project plan

## Product objective

Build a Romanian marketplace where people find trustworthy professionals and companies for every home-related need, filtered first by locality and county.

The proposed next product expansion is a provider-owned job workspace from accepted
quote through warranty, with fiscal invoicing and RO e-Factura staged before real
payment. See [the CRM roadmap](CRM_ROADMAP.md); its 49/99/199 lei tiers are
proposals, not current entitlements or active prices.

The first owner-command slice prepares a quote from a narrowly recognized Romanian
or English instruction. It makes no external AI request and leaves the existing
explicit send step in place. Scheduling, fiscal drafts, receivables, and optional
generative interpretation remain separate CRM milestones.

The provider-private customer register supports explicit, audited association to
an existing owned request. Selection stays paginated, preserves the submitted
contact snapshot, and never guesses identity, creates a platform account, or sends
mail. Offers and work inherit the association through their existing request.
An unlinked request can prefill a new private customer record, but the owner must
review the fields and confirm lawful use; customer creation and request association
commit atomically, while the active directory remains available for explicit reuse.

## Electrician discovery specialty

- [x] Add a distinct Romanian/English electrician choice to search and provider service
  declarations while retaining the general installations category.
- [x] Project only exact MF 2024 CAEN Rev.2 `4321` evidence, reconciled with ONRC, so
  plumbing and other installation firms cannot be mislabeled as electricians.
- [x] Include the specialty in the immutable Docker catalogue and responsive service index.

## Development-only complete provider journey

- [x] Keep real missing-catalogue providers fail-closed until ONRC authorization is
  reconciled, while permitting one explicitly audited synthetic authorization only in
  development settings.
- [x] Pin the synthetic provider to a distinct `SERVICIIAPROAPE_DEMO` source and to the
  current real county catalogue; production ignores the grant even if its row exists.
- [x] Activate the existing audited 30-day test entitlement without claiming that a
  payment was processed, so the demo account can exercise drafting, review and internal
  publication preview end to end.

## Implemented infrastructure — Docker cloud packaging (launch deferred)

### Persistent managed-cloud application — approved ONRC seed

- [x] Turn the repository-root Compose entry into a complete persistent development
  stack with PostgreSQL, private-media volumes, migrations and full admin/account/claim
  routes; keep strict production settings in the separate production Compose.
- [x] Package the approved privacy-minimized ONRC identity seed (72,881 opaque ids plus
  public registration numbers), pin it to the immutable discovery snapshot and reject
  checksum drift or partial existing databases.
- [x] Create the initial administrator from cloud secrets exactly once and preserve all
  subsequent accounts, claims, profiles and portfolio files across container restarts.
- [x] Retain the app-local read-only preview as a separate demonstration target.
- [x] Make the root development stack independent of a real domain and SMTP; emit test
  e-mails only to container logs and require only initial administrator credentials.
- [ ] Configure the real cloud domain, SMTP, operator identity, secret values, persistent
  volume policy, backups and external monitoring before public launch.

### Private development cloud — preloaded read-only image

- [x] Simplify root cloud discovery to one autonomous Compose service without
  `extends` or registry image assumptions; separate the PostgreSQL client into the
  production-only Docker stage while preserving the complete packaged preview.
  Build, runtime, catalogue and browser evidence is recorded in
  [the cloud Compose hardening report](reports/cloud-compose-hardening-2026-09-03.json).

- [x] Remove host-specific runtime options from default cloud Compose after the
  cloud rejected `cap_drop`; retain them in an opt-in local hardening override.
  Keep the image non-root and the catalogue root-owned/read-only to the web user.
  Root/app configuration parity, both override modes, build/startup, 25 regression
  tests, 141 HTTP checks and RO/EN desktop/mobile checks pass locally. See
  [portable Compose validation](reports/portable-compose-validation-2026-08-31.json).
- [x] Add a repository-root Compose discovery entry for the private cloud's
  root-only detector, reusing the app-owned service and app-local build context.
  Both resolved services match; root build/startup is healthy with 72,881 firms,
  42 counties and 141 passing HTTP checks. See
  [root discovery validation](reports/root-compose-validation-2026-08-31.json).
- [x] Make the default Docker image and Compose run without database credentials,
  migrations, administrator creation, imports or access to the local computer.
- [x] Capture only the existing discovery projection: 72,881 companies across 42
  counties and all six categories; preserve category-specific direct evidence.
- [x] Keep production in an explicit separate target/Compose; preserve approvals.
- [x] Remove private/write routes and their calls to action; date the historical
  snapshot in both languages. Refuse incomplete or corrupt packaged catalogues.
- [x] Validate the independent image with 212 passing PostgreSQL tests (zero skips),
  84 HTTP searches, 21 live-source parity comparisons, RO/EN desktop/mobile browser
  journeys, container recreation and healthy startup without a network or database.
  See [validation evidence](reports/private-preview-validation-2026-08-31.json).

The private cloud itself is not accessible to this task; packaging is tested locally.
See [the zero-setup instructions](../apps/casa_mea/deploy/README.md).

### Full production infrastructure

- [x] Repair local catalogue schema drift through migrations `0023–0025` and add the
  explicit `python manage.py migrate_catalogue` alias so future maintenance targets the
  same PostgreSQL container as `runserver`, while bare `migrate` remains SQLite-only.

- [x] Add localized privacy and terms pages grounded in the current product behavior,
  disclose only necessary session/form-security cookies, link them from one shared
  public footer and the claim consent, and require deployment-owned operator/contact
  identity in production. Consent records now store the exact displayed policy version;
  responsive RO/EN browser checks pass without overflow or console warnings.
- [x] Add a read-only production launch-readiness audit separate from Docker
  liveness. It accepts only an explicit official county allowlist, revalidates current
  runs and mutable publication approvals, includes report-triage integrity plus
  migration/restore state, emits identity-free JSON and fails non-zero on drift. The
  complete Docker and PostgreSQL suites pass (222 tests each; PostgreSQL zero skips).
  A validated private backup preceded migrations 0018–0020; the subsequent 42-county
  audit checks every catalogue in 5.18s and reports only the expected launch gates:
  all scopes remain internal previews and the local database has no production restore
  marker. See the
  [readiness validation](reports/production-readiness-audit-2026-09-01.json).
- [x] Add an external, read-only post-deploy smoke command that requires canonical
  HTTP→HTTPS, verified TLS, browser-security headers, RO/EN entry points, secure admin
  CSRF, provider-login redirection and denial of generic private-media access. It emits
  deterministic JSON, bounds response reads and remains separate from liveness and
  catalogue publication. See the
  [smoke validation](reports/production-http-smoke-2026-09-01.json).
- [x] Add a strict production Content-Security-Policy and Permissions-Policy in Django,
  without inline/eval exceptions; move custom admin styling into collected static CSS
  and make the external smoke reject policy drift. Browser QA also found and fixed the
  320px language-switcher overflow, with no console errors. All 233 tests pass on
  PostgreSQL with zero skips. See the
  [browser-security validation](reports/production-browser-security-2026-09-01.json).
- [x] Add app-local Compose with PostgreSQL 17, persistent private media, non-root
  Gunicorn/WhiteNoise, one-shot bootstrap and a Caddy HTTPS entry point.
- [x] Keep secrets, database dumps, raw datasets and private media out of the image;
  require a new secret, an explicit hostname and PostgreSQL in production.
- [x] Add explicit private export and empty-target-only restore, checksums/source pins,
  guarded bootstrap and per-county catalogue audits; never grant publication on import.
- [x] Add manifest-v2 media inventory and a read-only Docker backup verifier covering
  SHA-256, source pins, `pg_restore` parsing, safe tar members and configurable freshness.
- [x] Run an isolated restoration drill from the retained private backup into uniquely
  named temporary volumes, migrate through 0022, recover all 42 county scopes and
  72,880 rows, prove duplicate-restore refusal and remove only the drill resources. See
  [the recovery report](reports/backup-recovery-drill-2026-09-01.json).
- [x] Validate synthetic export/restore for 42 county scopes, duplicate-restore refusal,
  restart persistence, local HTTPS, RO/EN desktop/mobile rendering and private-file denial.
- [x] Pass 201 tests in PostgreSQL with no skips (43.8s), the JavaScript race test,
  migration checks and independent engineering review. See the
  [validation report](reports/cloud-packaging-validation-2026-08-31.json).
- [ ] Obtain explicit confirmation before exporting the actual private database/media.
- [ ] Configure the chosen cloud host, real domain, SMTP, off-host backups and monitoring.
- [ ] Complete genuine publication reviews/activations before anonymous users can see
  current internal-preview catalogues; direct evidence and provider profiles retain
  their independent publication boundaries. Docker packaging is not public launch.

See [the production runbook](../apps/casa_mea/deploy/PRODUCTION.md). No full private database copy,
external cloud deployment or publication approval was performed in this step.

## Completed milestone — personal-data request register

- [x] Add immutable administrative intake for access, rectification, erasure,
  restriction, portability, objection and other personal-data requests.
- [x] Calculate the initial deadline as one calendar month, show overdue state and allow
  one separately audited two-month extension only before the initial deadline after
  notification of the individual.
- [x] Require dedicated permission, row locking, optimistic revision, explicit
  acknowledgement and append-only events for identity review and final decisions.
- [x] Keep case closure separate from account/profile/publication mutations and include
  closed request contents in the configurable, explicitly acknowledged retention flow.

## Completed milestone — controlled access and portability package

- [x] Generate structured UTF-8 JSON only after identity confirmation for access or
  portability requests, using exact e-mail matching and explicit provider ownership.
- [x] Exclude credentials, token digests, staff identities, moderation notes, security
  records, unrelated accounts and binary portfolio media from the automatic package.
- [x] Stream with no-store headers, persist no export file and append an immutable event
  containing only the package SHA-256 while leaving the request open.
- [x] Validate 264 tests in the cloud image (10 PostgreSQL-only skips) and all 264 on
  PostgreSQL 17 with zero skips; production build, deployment checks and Compose config
  pass. Desktop and 320px Admin checks found no overflow or console errors, and the
  browser observed the download plus its revision-1 audit event.

## Completed milestone — personal-data request integrity audit

- [x] Add `python manage.py audit_data_subject_requests` as a read-only,
  request-rooted audit over one streaming `LEFT JOIN` query and a bounded iterator.
- [x] Rebuild every event chain and check request state/revision, calendar deadlines,
  extension facts, verification/closure chronology, event revisions/transitions,
  approved policy metadata and export-digest notes.
- [x] Keep retention-compatible minimized notes auditable, emit only deterministic
  identity-free aggregate counts and fail non-zero on drift without repairing data.
- [x] Include this private-register control in `audit_production_readiness`, while
  keeping both audits outside bootstrap and liveness so administrative recovery remains
  available.

## Completed milestone — controlled SIRUTA release audit

- [x] Generate future hierarchy candidates as schema 2 with explicit release id,
  official URL, publication/retrieval dates, raw-workbook SHA-256, generator policy,
  generated-catalogue SHA-256 and national counts.
- [x] Compare the candidate UI catalogue and hierarchy read-only from one byte read per
  artifact, covering added/removed codes plus county, name, display label, TIP and
  SIRSUP changes in deterministic JSON.
- [x] Reject malformed provenance, inconsistent catalogue/hierarchy pairs, duplicate
  children, contradictory parent identities and incomplete county sets; fail on any
  byte drift by default while retaining an explicit report-only mode.
- [x] Keep generation and audit outside installation and activation. Require a
  coordinated update of the release constant, ONRC manifests, reviewed aliases,
  provider source pins and staged catalogue runs before any future swap.
- [x] Validate 187 Python tests (9 PostgreSQL-only skips), Django checks and migration
  checks; load the real 42-county/13,755-locality baseline in 0.58s at about 76 MiB
  RSS; preserve the existing filtered browser search with zero overflow or console
  errors. Independent engineering review: SHIP.

## Completed milestone — Romanian and English public experience

- [x] Keep Romanian as the unprefixed default and expose every non-admin services
  route in English under `/en/`, with the URL prefix as the authoritative language.
- [x] Add a persistent RO/EN switch that preserves the current path and query string,
  and publish matching canonical, `hreflang` and `x-default` metadata.
- [x] Translate public, claim and provider-account workflows through Django gettext,
  including runtime JavaScript copy supplied by translated template data attributes;
  stable codes, slugs, audit facts and user/source content remain unchanged.
- [x] Keep Django admin unprefixed and Romanian, and mark account, claim and report
  pages `noindex`; claim and activation e-mails are explicitly bilingual.
- [x] Preserve the six-service phone index as a complete two-column layout, with
  English labels including “Plumbing, heating & electrics” for the unchanged
  `instalatii` slug and `44px` language targets.
- [x] Require no migration; validate 175 Python tests (9 skipped), the JavaScript race
  test, Django check, migration check and gettext catalogue. Desktop and mobile browser
  checks found zero overflow and zero console errors; final review: SHIP.

## Completed milestone — “Jurnalul de cartier” visual system

- [x] Replace the heavy workshop visual language with a lighter masculine editorial world.
- [x] Make the locality-first search a ruled, immediately usable editorial instrument.
- [x] Add a coherent custom SVG language for search fields and all six service categories.
- [x] Extend named editorial rubrics and coherent SVG marks to ONRC results, approved
  provider profiles, legal-company detail and public provider detail.
- [x] Preserve factual ONRC sources and limitations, provider workflow boundaries,
  grammatical singular counts and provider-only results without a false empty warning.
- [x] Validate Django checks and migrations, 149 tests (8 skipped), desktop and 320px
  browser flows for ONRC search and provider detail, with no horizontal overflow,
  console errors or review blockers; final review: SHIP.

## Completed milestone — public “Pentru profesioniști” entry

- [x] Replace the generic provider entry with a dedicated public page that explains
  the real ONRC catalogue → claim → e-mail confirmation and administrative review →
  activation invitation → separately reviewed provider-profile path.
- [x] Link the home-page professional callout and provider login back to this gated
  path without implying open sign-up, automatic approval or automatic publication.
- [x] Carry the responsive “Jurnalul de cartier” editorial pattern through the hero,
  numbered roadmap and truth-boundary note; the stage band wraps on mobile.

## Completed milestone — provider publication readiness guide

- [x] Derive readiness from the same profile, contact, approved service-area and
  portfolio rules enforced by whole-profile publication submission.
- [x] Show four factual workflow stages with direct links to their dashboard sections.
- [x] Distinguish incomplete, pending, changes-required, ready and visible states
  without presenting readiness as verification, recommendation or publication.
- [x] Validate the full progression through controlled internal-preview activation.

## Completed milestone — authenticated provider password maintenance

- [x] Add password change inside the private provider account, gated by active ownership.
- [x] Require the current password and apply the configured Django password validators.
- [x] Preserve the current authenticated session while invalidating every other session.
- [x] Keep credential changes separate from profile, service, coverage and publication state.

## Completed milestone — provider password recovery

- [x] Add a generic, provider-only reset request that does not reveal account existence.
- [x] Bound reset e-mail sends and use Django's expiring, single-use password token.
- [x] Invalidate reset access when the provider membership is revoked and return the
  provider to the dedicated login flow after a successful reset.

## Completed milestone — production provider-login throttling

- [x] Replace the process-local cache counter with one database-backed attempt budget
  shared by all Gunicorn workers.
- [x] Persist only a secret-keyed digest of the normalized e-mail address, allow five
  attempts per 15 minutes, clear the budget on success and remove expired rows in
  bounded batches.
- [x] Apply migration 0021 after the validated private backup and pass all 226 tests on
  PostgreSQL with zero skips, including an eight-connection concurrency test. The
  42-county catalogue remains intact and intentionally unpublished. See the
  [validation report](reports/provider-login-hardening-2026-09-01.json).

## Completed milestone — production Django Admin login throttling

- [x] Extend the shared database-backed attempt budget to Django Admin without adding
  process-local state or storing raw administrator usernames.
- [x] Keep provider and administrator budgets in separate HMAC namespaces, allow five
  attempts per 15 minutes and clear only the matching budget after successful login.
- [x] Apply migration 0022 and pass all 236 tests on PostgreSQL with zero skips,
  including the eight-connection shared-budget test. The 42-county catalogue remains
  intact and intentionally unpublished. See the
  [validation report](reports/admin-login-hardening-2026-09-01.json).

## Completed milestone — privacy-bounded production security events

- [x] Add a dedicated production JSON logger for authentication throttles, provider
  claim throttles and failed claim/invitation e-mail delivery.
- [x] Restrict output to a fixed operational schema and discard arbitrary fields,
  account identifiers, recipients, credentials, bearer URLs and exception messages.
- [x] Validate the formatter inside the production image and pass all 238 tests on
  PostgreSQL with zero skips. See the
  [validation report](reports/operational-security-logging-2026-09-01.json).

## Completed milestone — fail-closed production SMTP readiness

- [x] Require a valid SMTP hostname/port, credentials, sender, STARTTLS and bounded
  timeout before the production application can start.
- [x] Add an identity-free configuration audit that performs no network operation and
  an explicitly acknowledged synthetic delivery probe that never exposes its recipient
  or provider exception text in output/logs.
- [x] Validate the no-send audit inside the production image and pass all 246 tests on
  PostgreSQL with zero skips. A real delivery remains an operator/cloud action. See the
  [validation report](reports/smtp-readiness-2026-09-01.json).

## Completed milestone — provider availability and contact preference

- [x] Add provider-owned availability and preferred-contact fields to the private draft.
- [x] Require the preferred method to have a corresponding public contact value.
- [x] Copy both declarations into the immutable publication snapshot and label them as
  provider-declared in search, public detail and administrative preview surfaces.

## Completed milestone — administrative provider-account preview

- [x] Add a permission-gated preview action to the provider-profile admin list.
- [x] Show current account access, private profile content, services, exact coverage,
  portfolio and publication state in one read-only surface.
- [x] Keep preview GET inert and authorize private portfolio images through the same
  `view_providerprofile` boundary.

## Completed milestone — public provider report intake

- [x] Add a contextual report action to each visible provider profile and re-resolve
  the exact county, SIRUTA locality, category and publication snapshot on the report route.
- [x] Store one immutable, private report per browser session and exact
  `ProviderPublicationSubmission`, without visitor identity or IP-address fields; retain
  only a secret-keyed session HMAC for duplicate prevention.
- [x] Fail closed when the referenced publication is no longer visible, keep reports
  non-public and non-withdrawing, and expose them to staff only as a read-only admin queue.
- [x] Ship the responsive editorial intake and its created, duplicate and invalid states
  under direction seed `serviciiaproape-public-report-v1`; the final review resolved
  contrast, `aria-describedby`, invalid-field autofocus, the mobile index, privacy/status
  copy and desktop/mobile capture findings. Verdict: SHIP.

## Completed milestone — audited public-provider-report triage

- [x] Add one stable operational case for every immutable public report, created at
  intake and backfilled for existing reports, with the explicit state sequence
  `new` → `in_review` → `closed` and optimistic revision checks.
- [x] Record each accepted transition as an append-only event with actor, policy,
  acknowledgement, internal note, revision and terminal outcome, while preserving the
  original report, reviewed publication snapshot and publication scope unchanged.
- [x] Gate triage behind active staff status, the dedicated
  `triage_public_provider_report` permission, an own-profile conflict check, CSRF POST,
  row locking and exact publication-snapshot contract integrity; an integrity failure
  leaves the facts and history readable but removes the ordinary action.
- [x] Ship the task-first Django-admin surface with exact report and snapshot facts
  before operational state and action, explicit state words, square restrained
  controls, labelled/helped/error-associated fields and a `44px` minimum action.
- [x] Apply migration `0019`; validate 158 tests OK and 9 skipped, desktop `1072×818` and
  mobile `314×1582` with zero horizontal overflow; independent verdict: SHIP.

## Completed milestone — public-report operational insights

- [x] Add a dedicated, GET-only Django-admin perspective gated by active staff status,
  the built-in report view permission and the separate
  `view_public_provider_report_insights` permission.
- [x] Keep the projection to exactly four aggregate queries: all-time current case
  states, intake reasons in the selected window, immutable transition/outcome events in
  that window, and the all-time integrity anomaly count for reports without a case.
- [x] Offer exact half-open 7, 30 and 90-day windows with a 30-day default, while
  exposing no provider or visitor identity, report details, internal notes, actors,
  drilldowns or mutation paths.
- [x] Apply migration `0020` with the `(created_at, new_state, outcome)` event index;
  label all four tables through `aria-labelledby`, preserve `44px` window controls and
  zero mobile overflow; validate 161 tests OK and 9 skipped. Independent verdict: SHIP.

## Completed milestone — read-only public-report triage integrity audit

- [x] Add `python manage.py audit_public_provider_report_triage` as a read-only,
  report-rooted audit over one aggregate `LEFT JOIN` query and a bounded iterator.
- [x] Check every report for its required case; case state, revision and outcome; event
  count, transitions, revisions and outcomes; the policy allowlist, exact
  acknowledgement, normalized note of at least eight characters, and chronological
  `(created_at, id)` order.
- [x] Emit deterministic, identity-free JSON schema v1 totals and anomaly counts, and
  return a non-zero exit status when any drift is detected without repairing or
  mutating data.
- [x] Require no migration; validate 168 tests OK and 9 skipped with a clean Django
  check. Independent verdict: SHIP.

## Completed milestone — continuous integration gate

- [x] Run Django checks, migration drift detection, the complete Python suite and the
  JavaScript race-condition suite against a disposable PostgreSQL 17 service.
- [x] Validate the nested and repository-root portable Compose entry points plus the
  production Compose contract with synthetic configuration only.
- [x] Build both production and packaged-preview Docker stages, then smoke-test the
  packaged Romanian and English routes over HTTP.
- [x] Restrict workflow permissions to read-only repository access and keep deployment,
  private data and production secrets outside CI.
- [x] Reject inconsistent installed dependencies and failing production deployment
  checks, assert the production image's non-root UID/GID, and prove the packaged
  preview refuses POST over its localhost-only smoke-test port.

## Completed milestone — controlled dependency maintenance

- [x] Monitor the pinned Python packages, Docker images and GitHub Actions through one
  repository-native Dependabot configuration.
- [x] Send version-update pull requests to `develop`, group only minor/patch updates per
  ecosystem, and leave major releases isolated for explicit compatibility review.
- [x] Stagger weekly checks, cap open update pull requests and apply release cooldowns
  without enabling auto-merge or deployment.
- [x] Keep repository-level vulnerability alerts and security-update enablement as an
  explicit GitHub-owner responsibility.

## Completed milestone — packaged-preview browser regression gate

- [x] Add Python Playwright journeys against the final read-only Docker preview rather
  than a separate development server or private database.
- [x] Exercise county-dependent locality loading, desktop control alignment, filtered
  search, company detail/return, pagination and query-preserving RO/EN switching.
- [x] Run at `1280×900` and `390×844`, fail on browser errors or horizontal overflow,
  and retain screenshots/traces only for failed CI runs.
- [x] Expose the preview only on runner localhost and add `Browser E2E` as an independent
  CI result without granting write, publication or deployment authority. Local
  validation completed 3 isolated journeys in 9.465s with no browser errors or
  horizontal overflow; see the
  [browser E2E report](reports/browser-e2e-ci-2026-09-03.json).

## Milestone 1 — Core discovery experience

- Establish the Django project and clean monorepo boundary.
- Create a distinctive, light, masculine visual direction.
- Implement required county → optional official locality → optional category search, including county-wide results with each firm's actual locality.
- Show representative service categories and provider results.
- Cover empty and invalid-search states.
- Validate desktop and mobile behavior.

## Milestone 2 — Real catalogue and provider pages

- Audit the complete ONRC 08.07.2026 snapshot and matching nomenclatures without publishing records.
- Reconcile registered-office county/locality names to SIRUTA with explicit exact, ambiguous, unmatched, and manually reviewed states.
- Review and approve only deterministic administrative-form alias rules; keep spelling changes, historic names, foreign offices, missing values, and unresolved forms quarantined.
- Make the ONRC auditor verify the manifest, all six resource hashes, same-snapshot nomenclature relations, conflicting duplicates, and unique-company category counts before staging.
- Apply the approved status-policy v1 only as an internal staging gate; preserve radiated, mixed-status, and conflicting records in explicit quarantine buckets.
- Model the read-only legal registry separately from claimed provider profiles, contacts, service coverage, and verification.
- Pilot curated home-service categories on PostgreSQL before national publication. Completed nationally across all 42 counties and all six currently curated categories, with internal-preview-only activations.
- Refine visible categories with the MF 2024 reported predominant activity, reconciled against authorized ONRC CAEN facts. Shadow audit and 42 isolated v2 runs completed; publication remains blocked.
- Add provider profile pages with portfolio, availability, contact preferences, and service radius.
- Add minimum-data provider claim initiation with hashed 24-hour e-mail tokens,
  explicit confirmation and a separate administrative-review state. Completed;
  approval and profile editing are now completed as a private draft workflow.
  Every new request also includes one private, signature-validated representation
  document and a versioned transmission declaration; approval rechecks its hash.
- Add permission-gated, audited administrative claim decisions; approved claims
  create an inactive provider account, one owner membership and a separate hashed
  activation invitation. Completed; draft content is not read by the public catalogue.
- Add a private provider panel for display name, description and voluntary public
  contact fields. Completed.
- Add a private, revisioned declaration of services and exact SIRUTA coverage,
  limited to categories authorized in the provider's current ONRC base run.
  Completed; declarations remain private and unverified.
- Add exact-revision moderation for provider-declared services and coverage, with an
  immutable audited submission, approval or provider-safe change requests, and
  automatic invalidation after a real edit. Completed; approval is still private and
  does not create public coverage by itself.
- Add controlled whole-profile publication with sanitized private portfolio media,
  immutable profile/service/coverage/portfolio snapshots, a dedicated moderation
  decision, an audited visibility pointer, provider withdrawal, and exact locality +
  category discovery without duplicating the ONRC row. Completed for explicitly
  labelled `internal_preview`; real public activation remains fail-closed until the
  exact source catalogue has a valid legal publication approval.
- Add a privacy-minimized legal-company detail page that is reachable only through the
  active catalogue scope. Completed; provider-supplied profile fields remain deferred.
- Add stable legal-name ordering and 20-row pagination. Completed for the ONRC preview reader.
- Define the refresh cadence and change-audit process for future SIRUTA releases.
  Completed with provenance-pinned schema-2 generation, an annual/pre-ONRC review
  cadence and the fail-closed `audit_siruta_refresh` command.

## Milestone 3 — Accounts and trust

- [x] Allow a company absent from the active catalogue to submit a bilingual,
  e-mail-confirmed registration request with one primary service choice; preserve that
  choice as reviewable onboarding intent and preselect it safely in the first private
  draft, while requiring a separate permissioned legal-identity reconciliation before
  the request enters the existing claim and account-approval flow.
- [x] Add an optional provider-supplied professional address to the private profile,
  immutable schema-3 publication snapshot, administrative preview and public detail;
  legacy snapshots fail closed and cannot expose an unreviewed migrated value.
- [x] Add the first subscription entitlement boundary: a revisioned, audited 30-day
  test period activated only by authorized staff, required at approval and every
  public read, with automatic expiry hiding and no payment claims or billing data.
- [x] Publish a bilingual subscription rate sheet with a configurable proposed
  launch price, exact profile benefits and explicit non-endorsement limits; keep
  checkout absent and identify the current 30-day activation as a free test.
- [x] Add a bounded, bilingual Partner proposal to the same comparison: Essential plus
  a managed five-page site, maintenance, conversion forms, basic SEO/analytics and two
  monthly content updates; capture owner interest through a private, rate-bounded brief,
  notify operations without copying its content into e-mail, apply configured retention,
  and keep it separate from the simulated entitlement flow.

- Customer and provider accounts.
- Provider onboarding and identity/business verification.
- Reviews tied to completed or confirmed work.
- Moderation, reporting, and abuse protection.

## Milestone 4 — Requests and matching

- [x] Add structured, snapshot-pinned job requests with customer contact, project
  description, desired schedule and budget range; keep customer-uploaded photos deferred
  until the separate malware-scanning and media-retention contract is designed.
- [x] Reject repeated direct-request POSTs through a signed one-time form token and
  unique digest on the lead, without weakening the existing per-session send limit.
- [x] Add immutable provider quotations, a shared append-only conversation and an
  expiring customer capability link; let the customer accept or decline only the
  current valid offer and audit the resulting funnel transition.
- [x] Notify the verified provider without copying customer PII into e-mail, expose an
  owner-only inbox, and track a bounded, revision-safe status funnel with aggregate
  30-day and conversion indicators.
- [x] Include closed requests in the configured, acknowledged data-retention mechanism
  and disclose the customer/provider recipient boundary in the bilingual privacy notice.
- [x] Add a general project request that requires one exact service and locality, selects
  every currently visible provider with a matching active subscription, pins one
  private lead to each provider snapshot and gives the customer one expiring comparison
  workspace. Accepting one valid offer closes every competing live offer atomically.
- [x] Preview the current number of eligible subscribed providers on the general
  request form after exact county, locality and service selection. Keep the count
  public and identity-free, handle stale/error responses, and revalidate recipients
  at submission instead of treating the preview as a reservation.
- [x] Guard a general request against repeated POSTs with a signed one-time form
  token and a unique stored digest. Reject replays before notification, preserve
  the token across validation errors, and let a fresh form start a distinct project.
- [x] Keep the provider inbox usable as requests accumulate: expose fixed workflow-state
  filters with aggregate counts, paginate the owner-only queue and preserve validated
  navigation state after an update, offer or message without putting customer text in URLs.
- [x] Allow a separately permissioned administrator to retry one failed provider
  notification after explicit duplicate-delivery acknowledgement. Serialize attempts
  on the lead row, audit each outcome in Admin history, and never resend an already
  successful notification. No payment or customer-contact e-mail is involved.
- [x] Recover a failed anonymous customer-access e-mail for a single or comparison
  project through separate staff authority and explicit acknowledgement. Rotate the
  secret, keep its original expiry, audit delivery and never resend a successful,
  retained, expired or account-owned capability. Surface eligible failures in both
  Admin request lists with a customer-mail state and a recovery filter.
- [x] When initial delivery of an anonymous customer's access e-mail fails, expose
  the private workspace link only on that submission confirmation. Keep the response
  out of caches and referrers, and never expose the fallback on normal confirmations
  or later form visits.

## Milestone 5 — Operations and growth

- [x] Add a read-only, identity-free delivery audit for active requests. Report
  failed or pending provider notices, recoverable or expired customer links, and
  mixed comparison states as aggregate counts; exit non-zero when intervention
  is needed. Keep real payment out of this operational check.
- [x] Surface those same delivery counts in a GET-only, separately permissioned
  Admin page linked from the request list. Point recoverable states to existing
  filtered queues without exposing customer identities in the aggregate page.
- [x] Link expired single/comparison access and inconsistent comparison states to
  exact private Admin filters for investigation. Keep these states distinct from
  reissuable links and leave the aggregate page read-only.
- [x] Make provider-notification drill-downs match the active-only audit counts;
  exclude retained requests from failed and pending queues without changing the
  underlying notification or resend rules.
- [x] Add a permissioned, read-only pilot dashboard by county, service and 7/30/90-day
  window. Keep source approval, effective public profiles, internal previews and
  submitted-project demand separate; flag exact localities with requests but no quotes.
  Show a project-level request → first offer → accepted-offer progression and mean
  time to first offer without multiplying broadcasts by their provider recipients.
  This is launch evidence, not a publication switch or a substitute for the production
  readiness audit. Real payments remain deferred.
- [x] Add a separately permissioned, GET-only demand and response perspective for exact
  7, 30 and 90-day windows, grouped by service and exact county/SIRUTA locality. Keep
  customer projects distinct from provider deliveries so a multi-provider request never
  multiplies demand; expose no identities, free text, drilldowns or mutation paths.
- [x] Add revision-bound operational category administration with active, paused-intake
  and hidden-discovery states. Preserve the immutable CAEN taxonomy and all existing
  provider data, require explicit staff permission and reason, and append every change to
  protected history.
- [x] Add bilingual, canonical category + locality landing pages whose URLs retain the
  SIRUTA code to prevent same-name locality collisions; reuse the ordinary catalogue,
  subscription and publication readers, link them from the service index, and keep
  demo/internal-preview states `noindex` until the exact catalogue is public.
- [x] Add an environment-gated, owner-only simulated checkout that collects no financial
  data, grants one idempotent 30-day demo entitlement, and records distinct zero-payment
  provenance so the future billing adapter can replace it cleanly.
- [x] Add a separate customer registration and e-mail/password login flow with immediate
  activation, no confirmation link, an owner-only project portal, and explicit account
  ownership for single- and multi-provider requests. Preserve anonymous capability links
  and reuse the established offer, conversation, acceptance and visit-scheduling funnel.
- [x] Include provider-profile engagement events in the acknowledged retention audit:
  delete daily pseudonymous identifiers once they leave the longest 90-day metrics
  window. Align Romanian/English privacy and terms copy with all-eligible-provider
  broadcast behavior; keep application manual, audited and separate from page views.
- [x] Detach retained customer requests from account ownership. For a comparison
  project, invalidate its parent capability and unlink the parent only after every
  provider copy is retained; leave live sibling requests and audit totals intact.
- [x] Add a read-only, identity-free integrity audit for retained customer projects.
  Detect leftover contact/project text, conversations, quote text, account or token
  links, and parent batches whose children remain live; include failure in production
  readiness without mutating data or running retention automatically.
- [x] Extend that audit to retained company claims and unlisted-company registrations:
  verify scrubbed credentials and contact fields and the absence of representation
  documents, while keeping the aggregate output free of identities or document bytes.
- [x] Cover retained public reports, closed personal-data requests and Partner inquiries
  in the same read-only audit, including their child-event notes. Update the guarded
  retention run to scrub public-report triage notes and re-enter previously retained
  closed reports when older notes still need minimization.
- Complete the remaining consent, privacy, retention and legal review with the operator
  before a real launch.
- Replace the isolated simulation with a real payment provider, recurring billing,
  invoices and self-service cancellation only after the pricing and monetization policy
  are approved; disable the simulation switch before launch.

## Open product decisions

- Final product name and brand ownership.
- Whether customers contact providers directly or first submit a structured request.
- Final provider prices, tax treatment, billing provider, service agreement and
  cancellation policy; the current 49 lei Essential and 299 lei Partner values are
  operator-configurable proposals, not active checkout prices.
- Initial geographic launch area and who supplies the first real listings.
- The national strict preview contains 72,880 registered businesses whose MF 2024
  reported predominant activity maps to, and reconciles with, an authorized ONRC
  home-service category. All 42 counties remain internal-preview only.
- [x] Add a provider-visible, operator-controlled Partner inquiry tracker with strict
  forward transitions, optimistic revision checks, append-only events, and no payment or
  subscription side effects.
