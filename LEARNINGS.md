# Engineering learnings

- A commercial quote total must be derived from immutable priced lines on the
  server; browser arithmetic is only progressive feedback and a submitted total
  is never authority. Backfill historical offers as one equivalent line, keep
  line descriptions inside the request retention/export boundary, and do not
  present these commercial rows as VAT or fiscal-invoice lines.

- Preparing an offer from a linked CRM contact must remain a read-only convenience:
  prefill only facts from the immutable request, never invent price, duration or
  validity, and keep the request snapshot as the recipient. The linked contact is
  organizational context, while persistence and delivery still require the existing
  validated, explicit send action.

- Creating a CRM contact from a request must be one atomic, explicit transition:
  prefill is convenience rather than identity proof, the owner must review and
  confirm lawful use, and a stale association must roll back the new contact so
  no orphan record survives. Keep the active directory visible because an exact
  existing record must be chosen by the owner, never inferred from matching PII.

- Linking a provider-private CRM contact to a request is an organizational relation,
  not identity verification or permission transfer. Require an explicit selection
  from the same provider's active, paginated register; keep a separate optimistic
  revision and audit event; and never overwrite the immutable contact snapshot,
  create an account, or send mail as a side effect. An archived contact may remain
  visible on historical work, but it cannot be selected for a new association.

- A technician-specific overlap can be stated only for two complete intervals
  assigned to the same currently active member. Compare all active jobs, not
  only the visible page, use strict half-open boundaries so touching endpoints
  are not conflicts, and label the result advisory: missing end times and
  external commitments cannot establish actual availability.

- Execution start is not a calendar booking: record a separate actual timestamp
  and actor-attributed revision only after the scheduled time. Once started,
  reject rebooking and reassignment so a stale owner form cannot erase who began
  the work. Technician completion must recheck the current membership and exact
  assignment under locks, require explicit confirmation, and keep the owner
  completion path for jobs whose technician later loses access.

- A technician invitation must not grant access when merely sent. Keep its
  high-entropy token as a digest, bound to one exact mailbox, with expiry and
  owner revocation; authenticate an existing account before acceptance and
  throttle those password attempts. On mail failure, revoke the invitation so
  a pending record cannot masquerade as delivered. Query assigned jobs against
  the member's *current* active state so revocation closes already-open pages.

- An owner membership cannot double as a technician role: its reader exposes
  every private lead. Keep team membership and assigned-work reads separate,
  enforce exact profile/active state at query evaluation (so even a lazy query
  cannot outlive revocation), and clear assignment on booking cancellation.
  Onboarding and a technician UI must follow this boundary, not bypass it.

- Cancelling an execution booking is not cancelling an accepted quote or job.
  Under the same owner and retention boundary, lock the work order, require its
  current revision and a future start, clear both schedule edges, and append an
  event with the previous interval. Notify the customer only after a successful
  transition; the job returns to the unscheduled queue and can be booked again.

- A calendar overlap warning must look beyond the current week's page and
  include owner-scoped active jobs starting in adjacent weeks. Compare only
  complete half-open intervals, so touching endpoints and unknown end times
  are not flagged; without crew assignments the warning is advisory.

- Adding an estimated end to an established start-only schedule must preserve
  unknown historical duration as null. Validate a bounded positive interval
  at both the service and database boundary, record both edges in the event,
  and never present the interval as team availability before crews are assigned.

- A calendar cannot invent duration or free/busy capacity from a work order
  that stores only a start time. Show a local-week agenda of scheduled starts,
  keep assessment visits separate, and if the week is paginated derive day
  counts before paging so a day with off-page jobs is not shown as empty.

- A provider work list should project the work-order state, not the lead funnel
  or an accepted assessment visit. Reuse the active-owner/non-retained lead
  boundary, compute state counts before filtering, paginate rows, and route
  actions back to the exact owner-checked request.

- A billing-preparation queue must count completed work, not infer an issued
  invoice or an outstanding balance from a private draft. Scope it through the
  same active-owner, non-retained lead reader as the inbox, paginate before
  rendering, and link each row back to the exact owner-checked request.

- A natural-language shortcut is not authority to perform the action it describes.
  Keep parsing side-effect-free, resolve named customers only within the active
  owner's request set, refuse ambiguous names, and populate the existing offer
  form rather than bypassing its validation and explicit send confirmation.
  A deterministic local parser must be labelled honestly; it must not be sold
  as generative AI or allowed to invent duration, validity, tax, or payment facts.

- A provider-created CRM contact is not a platform customer account. Keep the record
  scoped to one active provider owner, require an explicit lawful-use confirmation and
  at least one contact channel, record PII-free revision events, and archive rather than
  silently delete. Creating or editing that record must never send mail or grant portal
  access; exact-email data-subject exports must nevertheless include it.

- A CRM state called "visit scheduled" must not be owner-selectable without a
  concrete time and customer consent. Keep provider proposals separate from the
  sales funnel, allow only one live proposal per request, expire elapsed slots,
  and record customer acceptance as the audited transition. A later quote or
  accepted job may retain its more advanced funnel status while the confirmed
  visit remains visible as a separate fact. Delete appointment notes and times
  when retaining the closed customer request.
  A cancellation must release the accepted slot transactionally, record who
  cancelled it, and reverse only the visit-specific funnel state; an already
  sent quote or accepted job retains its commercial state. Enforce at most one
  accepted visit per request in the database before allowing a new proposal.

- A quote acceptance is the handoff into execution, but the lead's `won` status
  is not a work-order record. Create exactly one order from the accepted quote
  inside the same lead-locked transaction for both direct and comparison paths;
  backfill active historical acceptances when adding the table. Keep visit,
  execution, fiscal issuance and payment separate so a state label never
  overstates what actually happened.

- A disabled submit button is only a browser convenience for a multi-provider
  request. Issue a signed, expiring form nonce, persist only its unique digest on
  the parent project, and enforce replay rejection in the transaction before
  notifying recipients. Preserve a valid nonce across form errors, but never
  reconstruct an anonymous customer's bearer link from its stored digest.
- The direct provider request needs the same database replay boundary, but batch
  child leads must not consume separate form tokens. Keep distinct signing and
  digest namespaces for direct and broadcast forms, with a nullable unique key on
  direct leads so older records and batch children remain valid.

- A broadcast form should show how many providers currently qualify before the
  customer submits private project details. Derive that number from the same
  effective public visibility reader as dispatch, return only a count, discard stale
  browser responses, and recheck recipients at POST because availability can change.

- An aggregate operations report and its drill-down must agree about retention.
  If the audit counts only active provider copies, a generic status filter can
  misleadingly include retained failures; use a dedicated active-only filter for
  those navigation links while leaving the underlying retry authority unchanged.

- An aggregate delivery warning without an exact drill-down leaves operators unable
  to investigate expired or inconsistent projects. Reuse the audit predicates in
  private Admin filters, keep direct requests separate from comparison parents, and
  never turn a diagnostic link into authority to resend an expired capability.

- An operational CLI audit is useful for scheduled checks but not for everyday
  triage. Reuse the exact aggregate projection in a separately permissioned,
  GET-only Admin view; send staff to existing filtered private queues only for
  recoverable states, and never imply an expired or mixed link can be retried.

- Delivery health is project-level for customers but provider-copy-level for firms.
  A multi-provider request must count once for a failed customer link, while each
  failed firm notice needs its own follow-up. Exclude retained work, separate expired
  capabilities from reissuable ones, and expose mixed batch-child states rather than
  presenting them as a safe automatic retry.

- Because an anonymous capability exists in raw form only during request creation,
  a failed initial e-mail is the last chance to offer immediate self-service access.
  Show the relative link only on that confirmation response, prevent caching and
  referrer leakage, and do not try to recover it from the stored digest on later GETs.
  An administrator's later reissue deliberately invalidates this earlier link.

- An anonymous customer's private access link cannot be recovered from its stored
  digest after e-mail failure. Recover by rotating the capability under a row lock,
  preserving the original expiry, and sending only to the recorded customer address
  with separate staff authority and an explicit warning that an ambiguously delivered
  older link will be invalidated. Do not reissue links for account-owned or retained work.
  The operational filter must mirror that eligibility and count a multi-provider
  project by its parent, not by each provider copy.

- A failed provider e-mail must not erase a durable request. Recovery should target
  only the failed notification, require separate staff authority and an explicit
  duplicate-delivery acknowledgement, and serialize the retry against another
  administrator. SMTP cannot promise exactly-once delivery after an ambiguous error.

- A customer portal that lists every owned request and prefetches every quote will grow
  with a long-lived account. Page each owner-scoped project stream before rendering,
  count distinct parent projects rather than recipient copies, and use database-side
  existence/count projections for summary indicators instead of hydrating child history.

- A closed report's private triage notes are another free-text retention surface.
  When a policy begins scrubbing a previously overlooked child table, make already
  retained parents with legacy notes eligible for the same acknowledged operation;
  auditing alone would detect drift without a controlled remediation path.

- Retaining a provider claim or unlisted-company intake must remove its private
  representation document as well as contact and credential fields. Check the
  post-retention state through an identity-free `Exists` projection; an audit should
  not read binary proof just to determine whether it still exists.

- A retention marker is not proof that every related private field was scrubbed.
  Audit retained children and parent comparisons read-only for residual text,
  messages, account/capability links and lifecycle contradictions, and surface drift
  in launch readiness without making healthcheck or page views mutate private data.

- Redacting a customer request's text is not enough while explicit account ownership
  or a parent comparison capability still links it back to the person. Detach each
  aged child and only retire the parent once every recipient copy is retained; keep
  active siblings accessible, project totals intact and the transition auditable.

- Daily pseudonymisation does not make engagement events anonymous. Retain their
  digest rows only through the longest provider-reporting window, audit eligible
  rows before a guarded, batched purge, and keep public privacy/terms copy synchronized
  with the actual broadcast recipient rule in both languages.

- Customer project attention cues must come from persisted offer state, not an
  inferred unread-message state. Sort owner-scoped pages in the database before
  pagination; use provider message and offer timestamps for recency, and require a
  still-valid sent offer before asking the customer to respond. Filter those same
  predicates before pagination, preserve validated filter state in page links, and
  distinguish "no matching offers" from "no projects" in the empty state.

- Activity e-mails for account-owned customer projects should lead to the exact
  login-guarded workspace, not instruct the customer to find an anonymous bearer
  link they never received. Keep anonymous customers on their original capability
  path and never copy a new bearer token, quote terms or message text into an
  activity notification.

- An owner inbox that pages its queue cannot promise a useful notification by linking
  only to page one. Carry a non-secret, opaque request id, resolve it inside the
  owner-scoped active queryset, and compute its current page using the same ordering;
  reject missing or foreign ids before rendering any private content. Redirect to a
  canonical page with the fragment after login, since login redirects discard fragments.

- A provider-offer funnel must use customer projects as its unit, not provider
  deliveries. A broadcast can yield several quotes but remains one project; measure
  its first-offer delay from the parent project creation time, and describe outcomes
  as of report time for a fixed project-creation cohort.

- Pilot readiness must join demand to *effective* provider visibility, not raw ONRC
  company counts or draft coverage. Keep public profiles and internal previews separate,
  scope demand by exact county/service/SIRUTA locality, and call out that zero replies
  describes submitted platform projects only. A dashboard is not an approval decision.

- A plan that combines marketplace software with human website delivery needs two explicit
  boundaries. List the repeatable monthly scope and allowance, name separately quoted costs,
  and require a brief plus calendar confirmation; never reuse a simulated software
  entitlement as evidence that custom work was purchased or scheduled.

- A marketplace broadcast is a subscription entitlement, not an ONRC mailing list.
  Send one project only to every currently visible professional snapshot whose active
  subscription, reviewed service and exact declared locality all match; create a private
  provider-owned copy for each recipient and keep contact details and project free text out
  of notification e-mails, logs and unrelated inboxes.

- Category availability is an operational policy, not a legal-taxonomy edit. Lock one
  stable policy row per code-owned slug, audit revision-bound changes, and preserve valid
  existing provider selections when intake pauses or discovery hides; never rewrite CAEN
  evidence, provider drafts, or publication snapshots to achieve merchandising behavior.
- A transitional constraint migration must accept every state already authorized by the
  previous schema, including privacy-retained rows whose tokens were intentionally erased.
  Test the transition against populated long-lived data, not only against an empty schema;
  the following migration cannot relax a constraint that PostgreSQL refused to create.

- Provider analytics should measure intent without building a visitor dossier. Pin each
  event to the visible immutable publication snapshot, accept only actions the snapshot
  actually exposes, omit IP/user-agent/referrer data, and daily-salt the secret-keyed
  session digest so database uniqueness can deduplicate reloads without linking visits
  across days.

- A service selected during unlisted-company intake is onboarding intent, not legal
  authorization. Preserve it on the audited registration, expose it to the reviewer,
  and use it only as a safe first-draft preselection when the later authorization
  boundary permits it; never let an intake choice publish or prove a service.

- A useful customer specialty need not rewrite an already audited broad catalogue
  taxonomy when the immutable retained evidence is exact enough to project it safely.
  Treat `electricieni` as a narrow CAEN-4321 view over `instalatii`, preserve the
  audited source run, and never relabel plumbing or other installation records. Once
  the UI offers both as separate choices, the broad installation filter must exclude
  electrical-only rows in both the live reader and older immutable preview snapshots;
  otherwise searching installations visibly returns electricians.

- Editorial category photographs on ONRC company records must follow the same validated
  service slug as the detail reader. They are shared illustrations, not company media or
  proof of work; label them visibly and keep them out of search-result thumbnails.

- A claimant's selected company role, chosen credentials and control of an e-mail
  inbox are not proof of authority to represent the legal entity. Require a bounded, signature-validated
  private document plus an explicit transmission declaration, hash the exact bytes,
  recheck integrity at approval, serve it only as an authorized admin attachment and
  move the same evidence atomically when an unlisted-company intake becomes a claim.
  When credentials arrive before approval, retain only the password hash and erase its
  duplicate from the request on approval or rejection.

- A synthetic end-to-end provider must not be smuggled into an ONRC import merely to
  satisfy publication foreign keys. Give it a separately named source and an explicit,
  audited profile grant; resolve that grant only in development settings, keep the real
  current county catalogue as an independent visibility pin, and make production ignore
  the row even if the database is copied there.

- Subscription is an entitlement boundary, not a field on a reviewed profile and not
  proof of payment. Lock a stable per-profile aggregate, append every administrative
  transition, require it both at approval and on every public read, and let expiry hide
  the immutable professional snapshot without rewriting moderation history. A manual
  test grant must say plainly that no payment was processed.

- Adding a new public provider field is a snapshot-schema change, not merely a form
  migration. Normalize it in the private aggregate, copy it into a new immutable
  contract version, and project an empty value for older versions; otherwise a storage
  default or later row mutation can masquerade as content that administrators reviewed.

- A wildcard `ALLOWED_HOSTS` does not make HTTPS form submissions valid behind a
  development proxy. Django's CSRF origin comparison also needs the trusted proxy
  scheme and a narrowly scoped platform-origin wildcard. Bind both to the known
  managed-host boundary; do not disable CSRF or trust arbitrary internet origins.

- A persistent cloud demo is not automatically a production deployment. Give the
  development target full database-backed workflows without forcing real domain/SMTP
  ownership: console e-mail and permissive HTTP hosting make verification possible,
  while the separate production settings retain strict HTTPS, secret, legal and SMTP
  gates. Never weaken the production module to make a development host convenient.

- A packaged discovery catalogue does not require a packaged mutable production
  database. Keep the public search projection immutable in SQLite, seed PostgreSQL
  only with the stable public identities required by workflow foreign keys, and
  persist accounts, claims and media in named volumes. Pin the identity seed to the
  exact snapshot checksum and refuse partial existing state; otherwise a deployment
  can render firms that its claim workflow cannot reference safely.

- Container liveness is not marketplace readiness. Database and HTTP health may stay
  green after a publication approval expires or is revoked, while the public reader
  correctly fails closed. Keep a separate read-only launch audit over an explicit
  county allowlist, migration/restore state and mutable publication/integrity gates;
  emit identity-free aggregates and never make this gate block administrative recovery.
- Post-deploy HTTP verification is a third contract, distinct from both liveness and
  marketplace readiness. Run it from outside the origin, require canonical HTTP→HTTPS,
  security headers, both localized entry points, private-route redirects and denial of
  generic private-media paths. Bound response reads and emit machine-readable failures;
  never weaken TLS verification merely to make the smoke test pass.
- A strict production CSP is an application contract, not just a proxy decoration.
  Keep it in middleware so every response shares the same boundary, remove app-owned
  inline styles/scripts instead of adding `unsafe-inline`, and make the external smoke
  reject weakened policies. Moving CSS can expose stale cache keys and narrow-screen
  overflow, so unify asset versions and verify the real 320px content width.

- A managed cloud can reject standard Docker Compose fields before build, even
  when `docker compose config` passes locally. Keep host-specific hardening in an
  opt-in local override and distinguish known unsupported fields from unverified
  ones. Non-root execution and a root-owned, immutable catalogue should remain
  image/application invariants, not depend solely on host Compose options.

- A cloud's automatic Docker discovery may inspect only the repository root.
  An app-local Compose file can build correctly and still be invisible to that
  detector. Keep a root discovery entry extending the app-owned service, pin
  its app-local build context explicitly, and verify that both entry points
  resolve to the same service. See the cloud boundary in `ai/ARCHITECTURE.md`.

- A cloud that only builds and runs Docker needs a self-contained development
  artifact, not a restore procedure it cannot execute. Package a historical,
  whitelisted discovery projection separately from production, with indexed reads,
  category-specific evidence variants, no ORM fallback, no private/write routes,
  and explicit capture dating. Validate the full county set and row counts as well
  as hashes: a correctly hashed partial export is still an incomplete catalogue.
  Source exports use a single read-only repeatable-read transaction; snapshots do
  not inherit future source revocations or constitute production publication.

- A Docker image packages code, not the current database or permission to publish it.
  Transfer the SQL snapshot and private media as a restricted, explicit backup outside
  the image, preserve private audit relationships, and report persisted data separately
  from public visibility. Never enable production DEBUG to reproduce an internal preview.
- PostgreSQL and private media cannot commit one restore transaction together. Validate
  and stage files first, restore SQL transactionally, and write a completion marker only
  after both stores succeed. Refuse nonempty targets and recover an interrupted install
  into fresh volumes; do not auto-delete existing data. Exclude the deployment marker
  when exporting a restored installation again. See
  [the production runbook](apps/casa_mea/deploy/PRODUCTION.md).
- A checksum proves that a backup did not change after its manifest was written, but it
  does not prove that `pg_restore` can parse the original dump or that a media archive
  is safe to extract. Periodic verification must exercise the PostgreSQL archive parser,
  recheck every tar member and inventory, enforce a freshness limit and emit only
  aggregate facts. The recovery drill still needs fresh, uniquely named volumes and a
  second restore attempt that proves overwrite refusal; delete only those exact drill
  volumes after validation and retain the source backup.
- Exercise bind mounts under the actual host's security model: on this SELinux host,
  Compose's long-form `bind.selinux` did not relabel the restricted backup, while the
  standard short `:ro,z` mount did. Keep private permissions instead of making backup
  files world-readable or disabling SELinux to work around a deployment failure.

- The repository is a monorepo: product code belongs under `apps/`, while shared plans and architecture belong under `ai/`.
- A narrated marketing film is both a media and accessibility contract. Keep its visual source, voice script, pinned neural source audio and FFmpeg generator in the app; use a local open-source voice instead of a metered external service when cost-free operation is required, include synchronized WebVTT captions, and require an explicit user action before sound starts.
- The product stack is Python by explicit user choice. The initial application uses Django so later milestones can add accounts, provider profiles, moderation, and administration without replacing the foundation.
- Missing-catalogue onboarding must be a staged identity intake, not a shortcut that
  fabricates an ONRC snapshot or grants a generic account. Collect the account credential,
  reconcile the legal identity under a separate staff permission, then feed the result
  into the same claim review; service authorization and publication remain independent.
- Only an account whose legal identity passed the audited unlisted-company registration
  conversion may use the service-area editor before current ONRC authorization resolves.
  It may save a clearly labelled private draft of known categories and exact SIRUTA
  coverage, but submission, review and publication stay fail-closed until authorization
  resolves and the draft is saved again against the current source pins. An established
  catalogue provider does not inherit this exception during a source outage: its editor
  stays fail-closed while previously saved private data remains intact.
- Marketplace counts and provider information shown in the first prototype are illustrative until a real data source and verification workflow exist.
- Romanian locality selection is county-dependent and uses official SIRUTA codes. The source resource may be named `.csv` while containing an Excel workbook, so generation must validate the file type rather than trust its extension.
- ONRC open-data exports describe legal entities, registered offices, states, and authorized CAEN activities. A registered office is not a service coverage area, and an authorized CAEN code is not proof of availability, skill, or quality.
- ONRC snapshots are multi-file, caret-delimited bundles. Company status and CAEN activity are both relational, CAEN codes require their version (0=1998, 1=2003, 2=2008, 3=2025), and all resources plus nomenclatures must come from the same snapshot date.
- ONRC exports contain literal, unescaped double quotes in company names. The caret is the only structural delimiter; Python CSV quote processing must be disabled or valid company rows and relationships are silently misparsed.
- SIRUTA locality aliases must preserve the official `SIRSUP` parent and both administrative TIP codes. A child name that is unique in a county can still belong to a different commune, town, or municipality, so display labels and name uniqueness are not safe reconciliation evidence.
- ONRC status decisions must partition both coherent firms and every raw/distinct status membership. Statuses linked to conflicting firm payloads are a separate quarantine bucket, not orphans and not records that may disappear through an inner join.
- Partial ONRC pilots are owned by an immutable `ImportRun`, not activated through the national source snapshot. Visibility must require an explicit succeeded run and a verified source; the deterministic scope key is rechecked against its materialized policy fields to detect provenance drift.
- In Iași, an exact-only registered-office reconciliation yielded no pilot rows because ONRC uses administrative forms such as `Municipiul X` and `Sat X, Comuna Y`. Strict hierarchy aliases are therefore a required, separately pinned policy input rather than a fuzzy matching convenience.
- Long ONRC imports need a database compare-and-swap claim token: checking a run state on an in-memory ORM object is not concurrency control. Finalize and failure updates must require the same claim token, and the PostgreSQL two-connection race must be tested.
- Locality-rule and hierarchy hashes must be validated once, target-country/county resolution must be prefiltered, and normalized forms must be cached. Rehashing a multi-megabyte hierarchy for every unmatched firm turns an otherwise bounded-memory scan into hundreds of gigabytes of redundant I/O.
- Catalogue activation needs a stable lockable row per provider/county. Locking an activation record that may not exist leaves a first-activation race, while activating per arbitrary category scope makes empty-category search ambiguous and duplicates overlapping firms.
- Internal preview and public publication are different states. Preview must require an explicit development flag and production must default fail-closed; public mode additionally needs a revocable, time-bounded approval tied to the exact run.
- Public registry results must use a whitelist projection rather than passing ORM objects to templates. This prevents later model fields such as CUI, registry URLs, fingerprints, or raw address data from leaking through incidental template changes.
- ONRC and SIRUTA may differ by meaningful punctuation in official locality names
  (`Piatra Neamț` versus `Piatra-Neamț`). Never weaken normalization globally: use an
  exact, county-scoped, reviewed comparison alias, retain the raw ONRC value, and still
  require the complete SIRUTA TIP/SIRSUP hierarchy contract.
- `Loc. copil, Oraș părinte` identifies the town centre only when child and parent are
  omonim after reviewed aliases. Require equality, TIP 17, parent TIP 2, real SIRSUP,
  county scope and a unique target; otherwise satellites can be assigned to the centre.
- A national county rollout must scan large ONRC exports once, while preserving global
  identity coherence before county filtering. Stage counties under independent claims,
  but activate their stable pointers in one deterministically locked transaction with
  explicit predecessor checks; this prevents partial catalogues and stale batch swaps.
- A product category can be narrower than its own label even when the import is
  technically correct. `Tâmplărie & mobilă` originally admitted only installation and
  repair, hiding a Săbăoani firm whose MF-reported predominant activity is furniture
  manufacturing. Curated CAEN mappings must cover the complete user-facing promise,
  with nearby broad manufacturing codes kept as explicit negative tests.
- Never activate an unrefined replacement base merely to feed a second-stage import.
  Refinement accepts an explicit complete set of hidden base runs, captures the old
  active refined pointers as CAS predecessors, and exposes only the new refined set in
  one atomic swap.
- A reported predominant activity is a precision gate, not a complete catalogue of a
  firm's real services. Do not weaken it globally when it creates a false negative:
  recover only the exact category through versioned, expiring, revocable direct
  evidence that separately proves legal identity, service, and declared coverage,
  while retaining the ONRC authorization and locality gates.
- A development server must not silently fall back to an empty SQLite database when
  the usable catalogue lives in PostgreSQL. Local `runserver` either connects to the
  complete, validated 42-county container or fails with an actionable error; tests and
  production keep their explicit database contracts.
- A company detail URL is another catalogue reader, not a lookup by primary key. It
  must resolve the opaque business id through the current county pointer, selected
  SIRUTA locality, optional category, strict MF branch and still-valid direct-evidence
  branch; otherwise a guessed URL can bypass catalogue activation or evidence expiry.
- E-mail claim links are bearer credentials, not approval decisions. Store only a
  SHA-256 digest, expire the token, make the landing page read-only, and require a
  CSRF-protected POST to confirm; scanners and link previews must never advance a
  claim. E-mail possession moves a request only to administrative review and never
  publishes contact data or grants profile editing by itself.
- Provider approval must create marketplace identity through one transactional
  service, never through direct admin-field edits. Keep the legal business immutable,
  create an inactive account and invited membership, and use a second hashed,
  one-time credential for activation; GET remains inert and profile editing is always
  authorized through the exact active membership.
- Provider-declared services and service coverage are one private, versioned aggregate,
  not editable ONRC facts and not reviewed evidence. Categories must remain a subset
  of the business's current authorized ONRC categories, localities must be exact
  county–SIRUTA pairs, and every replacement must lock the active owner, compare the
  expected revision, and invalidate any review of the previous revision.
- Moderation must decide an immutable snapshot of one provider-declared revision, not
  mutable draft rows. A real edit supersedes the current submission while preserving
  its historic decision; approval revalidates the current catalogue pointer and source
  pins under lock, and remains a private workflow distinct from publication.
- A provider publication must never read mutable profile, service-area, or portfolio
  rows directly. Copy every public field into one immutable, hashed submission and
  expose it only through a stable audited pointer; edits and asset revocation must hide
  the pointer fail-closed without erasing its history.
- Private media is not made safe by an unguessable filename alone. Decode and bound the
  pixels, re-encode to remove EXIF and original metadata, store only opaque derivatives
  outside any generic media route, and authorize every response through owner,
  reviewer, or currently visible publication state.
- PostgreSQL rejects `SELECT ... FOR UPDATE` when the query locks the nullable side of
  an outer join. Lock the stable scope row by itself, then load its optional approval;
  SQLite will not reveal this incompatibility, so publication workflows need a real
  PostgreSQL test before handoff.
- Registered-office discovery and provider-declared coverage are different products.
  Query them in separate reader branches, deduplicate by stable business identity, and
  label each source so declared service reach is never presented as an ONRC fact.
- Optional aggregate filters must not erase row-specific context. A county-wide search
  uses no SIRUTA predicate, projects each registry firm's actual registered locality,
  and pins every claimed-provider link to one exact declared coverage locality.
- An administrative account preview is an authorization boundary, not impersonation
  and not publication. It may project the current private provider draft to staff with
  explicit view permission, but its GET must remain inert and private portfolio media
  must be authorized through that same staff permission.
- Marketplace availability is a mutable provider declaration, not a trust badge. Store
  it in the private profile, copy it into the immutable publication snapshot, qualify it
  everywhere it is shown, and preserve version-aware hash verification for older
  snapshot schemas when the public contract gains a field. Database defaults added by
  a migration are compatibility values, not historical user claims; legacy public
  projections must say the declaration was unavailable in that snapshot version.
- Password recovery is part of the provider authorization boundary, not merely a
  generic Django account screen. Keep request responses enumeration-safe, restrict
  delivery to active provider ownership, bound repeated sends, and recheck membership
  at confirmation so a reset token cannot outlive revoked access. A process-local
  cache is not a send limit across workers: reserve the shared budget under a database
  lock and persist only a secret-keyed digest of the e-mail/client pair. A durable
  throttle also needs bounded expiry cleanup; otherwise enumeration-safe requests can
  still become an unbounded storage attack.
- A process-local login throttle is not a production control when Gunicorn has several
  workers. Reserve attempts under a database row lock, persist only a secret-keyed
  digest of the normalized account identifier, reset successful authentication explicitly,
  and bound cleanup of expired keys. The same primitive can protect provider and Django
  Admin login only when its HMAC namespace separates those budgets; failures in one
  authentication domain must never lock the other. Exercise the limit with real concurrent
  PostgreSQL connections; thread tests must explicitly close their worker connections or
  teardown can leave a misleading database-in-use failure.
- A control that blocks abuse but emits no stable event is difficult to operate in a
  managed cloud. Send security events to one dedicated logger with machine-readable
  event codes and an explicit field allowlist. Never attach account identifiers, message
  recipients, bearer URLs, exception text or arbitrary log-record fields; an exception
  class is sufficient to route delivery failures without turning logs into a second PII
  store.
- E-mail is part of the account authorization path, so an empty SMTP configuration is
  not a harmless optional production feature. Validate host, bounded port, credentials,
  sender syntax, STARTTLS and timeout before startup. Separate configuration audit from
  delivery: the default probe must make no connection, while a real synthetic send must
  require a valid recipient plus an exact operator acknowledgement and must never echo
  the recipient or provider exception text.
- Legal identity is deployment data, not a brand-string default. Require the real
  operator name, address and privacy contact before production startup, while local
  development uses an unmistakable placeholder. A consent record must store the exact
  public policy version rendered by the form; otherwise later copy changes destroy the
  audit meaning of an accepted checkbox. Cookie copy must follow the running product:
  necessary session/CSRF cookies can be explained without manufacturing an analytics
  banner when no analytics or advertising storage exists.
- Authenticated password change must prove the current credential and recheck active
  provider ownership; it must not become a generic user-targeting endpoint. After a
  successful change, refresh only the requesting session's authentication hash so the
  provider stays signed in while every other session becomes invalid, and keep this
  credential mutation entirely separate from marketplace publication state.
- Workflow guidance must project domain truth rather than persist a second progress
  model. Derive provider publication readiness from the exact submission predicates,
  expose pending and changes-required decisions as distinct states, and link each
  missing prerequisite to its authoritative editor. A completed checklist stage is a
  preparation fact, never a verification, recommendation or publication badge.
- Public reporting should target the exact immutable snapshot a visitor could see, not
  a mutable provider profile. Re-resolve visibility fail-closed on the intake route,
  store no visitor identity or IP address, and use only a secret-keyed session digest
  for per-snapshot duplicate prevention. Keep the resulting operational queue read-only:
  a report is private review input, not public accusation or automatic withdrawal.
- Operational triage must not turn an immutable public report into an editable admin
  record. Create one stable lockable case at intake (and backfill it for existing
  reports), advance only `new` → `in_review` → `closed` with an optimistic revision,
  and append one protected event per accepted transition. Revalidate the exact reported
  snapshot contract before every action, block on integrity drift, require dedicated
  staff permission plus an own-profile conflict check, and keep any publication or
  withdrawal decision in its separate authoritative workflow.
- Operational insight is another private-reader boundary, not permission to expose the
  queue. Require both the model view permission and a narrower aggregate permission,
  keep the route GET-only, and project only fixed identity-free groups. Current queue
  state and missing-case integrity are all-time facts; intake and transitions use exact
  half-open rolling windows, with transition outcomes derived from immutable events.
- An integrity audit must start from the parent record with a `LEFT JOIN`; starting from
  cases or events hides the missing-child anomaly it is meant to detect. Stream one
  aggregate query through a bounded iterator, emit only versioned identity-free counts,
  fail non-zero on drift and never repair during observation. Relational invariants can
  prove that persisted rows are coherent now, but without an external digest or ledger
  they cannot prove cryptographically that a currently valid row was never rewritten.
- Localized server-rendered routes need one explicit authority. Keep the default
  language unprefixed, derive English from `/en/` through `i18n_patterns` and
  `LocaleMiddleware`, and translate equivalent URLs rather than storing a hidden
  language preference. Preserve path and query state in the switch, publish matching
  canonical/`hreflang` metadata, and keep admin outside the localized route set.
  JavaScript copy should enter through translated template data attributes; never
  translate stable slugs, policy versions, acknowledgements, audit facts or persisted
  codes. Administrator-triggered e-mails need explicit bilingual content until the
  product stores a verified recipient-language preference.
- A locality refresh is a coordinated source-pin migration, not a JSON replacement.
  Generate future SIRUTA releases outside the active data directory with explicit
  release metadata and raw-workbook identity, hash the exact bytes that were parsed,
  compare the UI catalogue and hierarchy as one national pair, and fail on drift by
  default. Even formatting-only catalogue changes can invalidate provider source pins;
  observation never authorizes installation or activation.
- Retention is a policy-controlled minimization workflow, not a startup cleanup. Keep
  legal durations environment-owned and fail closed in production, make inventory the
  default read-only operation, and require an exact acknowledgement before mutation.
  Preserve decision state and audit relationships while replacing expired contact data
  and free text; never auto-minimize approved ownership or work still under review.
- A personal-data rights request is both sensitive intake and an operational deadline.
  Freeze the received facts, calculate the initial deadline in calendar months rather
  than days, and move state only through locked, revision-checked transitions with an
  append-only event. A two-month extension is a separate notified action before the
  initial deadline, never an editable date; closing the register records the decision
  but does not itself execute deletion across unrelated domain stores.
- A personal-data export must be an allowlisted projection, never a model dump. Link the
  verified subject only by exact normalized contact and explicit ownership edges; omit
  credentials, token digests, staff identities, moderation notes and third-party rows.
  Generate it in memory, disable caching and journal only its SHA-256 so the application
  does not create a second unmanaged personal-data store.
- A personal-data register needs a separate integrity observer after it gains deadline,
  export and retention events. Rebuild each chain from the request-side `LEFT JOIN`,
  validate calendar deadlines and action-specific metadata, and count anomalies once
  per request without emitting identity. Retention may deliberately redact notes, so
  accept the redaction only when the parent request carries the authoritative retention
  marker; observation must never restore or rewrite the history.
- A live help/status line inside one nested form column must not control the vertical
  position of sibling controls. Align the outer search grid from the start and offset
  only the label-less action to the control row; at stacked breakpoints remove that
  offset so dynamic locality counts expand downward without moving service selection.
- Repository-root configuration is justified only when the platform itself requires a
  fixed discovery path. GitHub Actions must live in `.github/workflows/`; keep such a
  workflow orchestration-only and leave application runtime ownership under the app.
- A green SQLite test run is insufficient evidence for a PostgreSQL production system,
  and a successful source test is insufficient evidence for its Docker artifact. CI
  should exercise the real database engine, migration drift, both packaging stages and
  a live request to the final preview image, using synthetic disposable data only.
- Dependency automation should propose reviewed changes, not silently mutate the stable
  branch. Target the integration branch, keep ecosystems separate, group only compatible
  minor/patch updates, isolate majors, and put every proposal through the same real-
  database and packaging gates as human changes.
- Building an image is not proof that its runtime security contract survived. Make CI
  inspect the final declared user, load fail-closed production settings, check the
  resolved dependency environment and exercise a forbidden write against the running
  read-only artifact; source-level intentions otherwise drift unnoticed.
- Browser regression tests should drive the final packaged artifact as a black box.
  Assert stable user contracts—roles, IDs, routes, query state, responsive overflow and
  console errors—rather than mutable company names or exact catalogue totals. Keep each
  journey isolated and retain traces only on failure so diagnostics do not become a
  routine second copy of catalogue content.
- When `runserver` discovers a PostgreSQL catalogue but other Django commands default
  to SQLite, a successful bare migration can leave the live application unchanged.
  Provide an explicit, side-effect-obvious catalogue migration command that reuses the
  exact runserver discovery path; never make bare `migrate` mutate a discovered database
  implicitly.
- A root-only managed-cloud detector should receive the smallest self-contained Compose
  contract possible. Avoid `extends` for a single service, point directly at the
  app-owned build context and keep platform-specific runtime options out. Also keep
  database administration clients out of a self-contained read-only image; install
  them only in the production stage that actually performs backup or restore.
- A persistent development cloud should have its own explicit Docker target instead of
  turning a production target into development through a Compose command override.
  Validate the immutable catalogue and its one-to-one workflow identity seed while the
  image is built, then repeat validation before first database seeding; a partial image
  must fail before it reaches the platform.
- `close_old_connections()` is a request-boundary hygiene operation, not a guaranteed
  teardown for database work done in test-created threads. With a positive
  `CONN_MAX_AGE`, a healthy thread-local PostgreSQL connection remains open and can
  prevent Django from dropping the test database. Concurrent test workers must call
  `connection.close()` explicitly in `finally`; use `close_old_connections()` only
  before work to discard inherited or stale state.
## 2026-09-09 — Treat fuzzy gettext matches as untranslated UI

- `makemessages` can fuzzy-match new Romanian labels to semantically different older
  strings and preserve an incorrect English `msgstr` (for example, “Decline quote” can
  inherit “Accept quote”). `msgattrib --untranslated` will not report those entries.
- For every new bilingual surface, inspect both `msgattrib --untranslated` and
  `msgattrib --only-fuzzy`, replace fuzzy matches with exact translations, compile the
  catalogue, and verify the rendered English route in a browser.

## 2026-09-10 — Review eligibility must be customer-authored evidence

- A provider-side funnel status cannot prove that a customer completed a transaction.
  Permit one review only when the capability-authenticated customer accepted an immutable
  platform quote; keep it private until a separate, audited moderation decision.
- Freeze review content and consent at intake, minimize the public reviewer name, and
  let moderation decide visibility without editing testimony or changing profile ranking.
- A provider response is new public content, not an edit to the customer's evidence.
  Authorize it through active ownership, freeze one response per review, and moderate it
  independently before nesting it under the original public review.

## 2026-09-10 — Session conveniences must reuse public visibility gates

- An anonymous shortlist should store only opaque identity plus the minimum exact search
  scope, never copied profile or contact data. Resolve every saved entry again through the
  standard fail-closed public reader so expiry and withdrawal take effect immediately.
- Treat saved state as a visitor convenience only: bound its size, keep redirects internal,
  and never let it influence ranking, analytics, trust labels or publication state.
- Registry-only firms need the same visible bookmark affordance as complete profiles,
  but their saved identity and scope must re-enter the active catalogue reader. Keep
  registry and professional snapshots distinct in the saved view; a saved ONRC record
  must never imply a service area, contactability, or provider verification.

## 2026-09-10 — Detail routes must accept search-projected specialties

- A category derived at read time can be valid even when it is absent from the immutable
  import run's broad category list. Search support and company-detail validation must use
  the same `catalogue_categories` projection; otherwise a valid result produces a 404 when
  opened in its unchanged search scope.

## 2026-09-14 — Human-readable locality URLs still need stable identity

- Locality names are not unique enough to identify an SEO page, even inside a county, and
  their spelling can change between official releases. Keep the readable slug for people,
  but include the authoritative SIRUTA code in the route and permanently redirect stale
  slugs to the one canonical spelling.
- A locality landing page must reuse the ordinary search reader and visibility gates. A
  parallel SEO query will eventually drift on catalogue approval, provider subscription or
  specialty projection and can expose results that the interactive search would hide.
# 2026-09-14 — Simulated checkout must remain an entitlement adapter, not fake billing

- A demonstrative subscription flow should never collect realistic card fields or create
  payment-shaped records. Grant the existing entitlement through an explicit environment
  gate and record a distinct policy version in the audit trail.
- Make demo activation idempotent while the entitlement is active. Otherwise a replayed
  POST becomes an accidental free renewal mechanism and diverges from the webhook contract
  a real processor will eventually need.
- A multi-provider request needs one capability-bearing parent plus separate child leads
  pinned to each provider's immutable publication snapshot. Never share a conversation or
  quote record across providers: accepting one offer must lock the parent and atomically
  close all competing live offers, while the provider selection remains bounded and free of
  ranking signals.

## 2026-09-14 — Demand and delivery are different operational measures

- Count a customer project once even when it is delivered to several providers. Provider
  deliveries, responses and awards are separate measures; collapsing them into one count
  inflates demand and makes locality planning unreliable.
- Aggregate operational demand over exact service and county/SIRUTA locality keys. Keep the
  perspective identity-free and read-only, and state that submitted requests are not the
  same thing as catalogue searches or total market demand.

## 2026-09-14 — A private lead inbox must stay bounded without moving PII into navigation

- Filter a provider queue only by fixed server-owned workflow groups and paginate the
  owner-scoped queryset before hydrating conversations and forms. Names, contact details and
  project text do not belong in URLs, logs or reusable filter state.
- Summary metrics describe the whole retained queue, while the visible-result count describes
  the selected filter. Preserve only validated filter/page values after a mutation; never
  accept an arbitrary return URL from a private form.

## 2026-09-14 — Customer accounts extend capabilities; they do not replace them

- Link a signed-in customer to requests through explicit foreign keys, never by matching
  an e-mail address. Keep historical and anonymous capability links valid, while account-
  owned requests gain token-free portal routes guarded by the same ownership boundary.
- Customer and provider identities are separate roles over Django users. Authentication
  must verify the requested role after checking the credential, and failed-login budgets
  need separate namespaces so abuse against one portal cannot lock the other.
- When an authenticated customer submits a request, derive name and e-mail from the
  account rather than trusting editable form fields. The account removes the need to send
  another bearer link; it must not weaken snapshot, locality, service or retention gates.

## 2026-09-15 — A managed-service inquiry is not an entitlement

- Keep a commercial brief behind existing provider ownership and rate boundaries. Saving
  interest must never activate a subscription, fabricate an order, or imply that payment
  occurred.
- Notify staff with an opaque record pointer, not by duplicating free text or account data
  into e-mail. Retain the operational state while anonymizing the website and brief on the
  configured schedule.
## Partner commercial workflow remains separate from entitlement (2026-09-15)

- A managed-site brief needs provider-visible progress, but those statuses describe a human
  conversation only. Even `accepted` must not create payment, subscription, order, or
  publication state.
- Treat operator changes as audited transitions: dedicated permission, row lock, expected
  revision, strict forward transition map, and one append-only event per revision.
- Provider UI may expose the current status but never internal operator notes. Retention must
  anonymize free text on both the original brief and its operational events.

## 2026-09-16 — Service artwork must follow the active catalogue scope

- A company may match several categories, so a service illustration on its detail page
  should use the selected, validated search category when present. For county-only
  routes, use one of the listing's actual category slugs, never an unrelated generic
  drawing or a slug inferred from the company's name.

## 2026-09-16 — Keep the home search path singular

- The home page should lead directly from one concise promise to the complete county-first
  search form. Search results belong immediately after that form, before service discovery
  or promotional content.
- Repeating service navigation in an editorial index, adding city shortcuts above the form,
  or explaining the same process both beside the hero and after the film makes the primary
  task harder to find. Preserve the service links and accessible film, but give each one
  clear, distinct placement.

## 2026-09-18 — Work execution must not be inferred from the sales funnel

- An accepted offer opens one provider-owned work order, but the lead's `won` label
  must not be manually changed to `completed`. Scheduling and completion are distinct
  owner-scoped transactions with revision checks and actor-attributed events.
- A scheduled execution time is separate from a customer site visit. Completion
  requires explicit confirmation after the scheduled time; it does not issue an
  invoice, confirm payment or create a warranty.
- For local development, `migrate_catalogue` targets the same PostgreSQL database
  as `runserver`; plain `migrate` uses the default SQLite database. Inspect the
  migration plan before applying an additive schema change to the catalogue.

## 2026-09-18 — A billing draft is not a fiscal invoice

- Keep pre-issuance preparation private to the provider and behind a completed
  work order. Seed it from the accepted quote, use one revisioned draft per order,
  and do not generate a number, tax treatment, due date or payment status by
  inference. An issued fiscal document needs its own verified issuer data and
  retention boundary; it cannot inherit the temporary lead's cascade deletion.

## 2026-09-18 — Declared issuer details need a separate authority boundary

- Do not auto-fill a mutable billing setup from an ONRC snapshot and call it
  verified. Keep the firm's declaration private, owner-scoped, revision-checked
  and audited, apart from both the public provider profile and the platform's
  own subscription-billing identity. Future issued documents must pin the
  validated issuer snapshot used at issuance, not dereference today's settings.

## 2026-09-21 — A manual receivable ledger must remain auditable and truth-bound

- Snapshot the amount from the completed work's private billing draft when the
  receivable is opened, then lock that draft. Otherwise later edits silently rewrite
  the history against which receipts were declared.
- Manual receipts are append-only declarations, not payment confirmations. Corrections
  must void a row with actor, time and reason; active rows alone contribute to the
  balance, and the provider-owned parent row must be locked while enforcing no overpayment.
- Keep these records in data-subject exports and the existing project-retention cascade,
  while stating clearly that no fiscal invoice, bank verification or processor exists.

## 2026-09-21 — Collection automation starts as an internal task, not customer pressure

- Before fiscal issuance exists, an overdue internal balance is not enough authority to
  e-mail a payment demand. Surface a private follow-up task first and say explicitly that
  no customer contact occurred.
- A useful reminder contract needs an owner-scoped revision journal, a minimum cooldown
  after either contact or partial receipt, and automatic clearing when the active manual
  receipts settle the balance. This prevents duplicate pressure and stale tasks without
  pretending the ledger was bank-verified.

## 2026-09-21 — A command assistant should answer only from an authoritative projection

- A natural-language shortcut can safely answer “who has not paid” only after an
  owner-scoped receivable projection exists. Return aggregate count, balance and overdue
  count, then link to the ordinary guarded list; do not put names or balances in the URL.
- Keep supported read commands exact and fail all other prose into the existing strict
  parser. This makes the assistant predictable, prevents mutations disguised as questions,
  and avoids sending private CRM data to an external model.
