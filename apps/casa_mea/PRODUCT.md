# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python by explicit user choice. Django is delegated to the implementation as the recommended foundation for a marketplace with future accounts, administration, and relational data.

## Users

Primary users are people in Romania who need a professional or company for work around their home and want to see who actually serves their locality. Provider-side workflows are a later milestone.

## Product Purpose

Help people discover home-service providers by county, optional locality, and type of work. Success in the first milestone means a visitor can understand the service and complete that search immediately.

## Positioning

The county is the required discovery boundary. Visitors may narrow it to one official locality and one service, while a county-only search shows every eligible company in that county with its actual registered locality.

## Operating Context

Visitors may arrive with an urgent repair or an improvement project and often search from a phone. They need plain Romanian terminology, broad category coverage, and useful empty states when local supply is thin.

## Capabilities and Constraints

- Search requires a county; locality and service are optional refinements. When locality is omitted, every result keeps its own official SIRUTA locality and provider-profile links remain pinned to an exact declared coverage area.
- Category filtering is optional and includes a precise electrician specialty alongside
  gardening, construction, repairs, installations, cleaning and related home work.
- The complete non-admin experience is available in Romanian and English. Romanian
  remains at unprefixed URLs, English uses `/en/`, and switching language preserves the
  current page and search criteria. Django admin remains unprefixed and Romanian.
- The home page includes one localized 29-second narrated promotion film that opens with
  a realistic male presenter and demonstrates the visitor journey from location and
  service selection to complete profiles and direct contact. Playback is user-initiated
  so sound never starts unexpectedly; synchronized captions preserve comprehension without
  audio. Its male narration is generated locally from pinned neural voice assets, without
  a metered external service. It pauses outside the viewport, exposes a keyboard-accessible playback control,
  and stays on its static cover for reduced-motion visitors until explicitly played.
- Localized labels never change domain identity: for example, the `instalatii` category
  is presented in English as “Plumbing & heating” while its slug and stored value remain
  unchanged and `electricieni` remains a distinct “Electrical work” choice.
- All counties have PostgreSQL-backed internal previews across the six original curated
  categories plus an electrician specialty projected from exact MF/ONRC CAEN 4321
  evidence. The strict refinement retains only firms whose MF 2024 reported predominant
  activity maps to and reconciles with an authorized ONRC home-service category; missing
  MF evidence is exclusion from this preview, not proof of irrelevance.
- ONRC results represent registered-office and authorized-CAEN facts, never service coverage, availability, contact, competence, quality, or recommendation.
- A visible company can receive a minimum-data claim request. E-mail confirmation
  proves only mailbox control and starts a separate administrative review; it does
  not publish contact data or grant editing rights. The claimant must select their
  role, provide one private PDF/JPEG/PNG document proving authority to represent the
  company and declare the right to transmit it. Only authorized staff can download
  the document, and approval is blocked if its stored bytes no longer match the hash.
- A representative whose company is absent from the active catalogue can submit a
  separate company-registration request with legal name, CUI/CIF, trade-register
  number, one required primary service category, registered-office locality, minimum
  contact data and the same private representation proof. The category is an onboarding
  intent shown to the reviewer, not proof of legal authorization or publication; after
  conversion it preselects the provider's first private service draft only when that
  category remains permitted by the current authorization boundary. E-mail confirmation
  proves only mailbox control. Authorized staff must verify and reconcile the legal
  identity before the request becomes a normal claim; neither submission nor
  reconciliation publishes the company, services or contact data.
- An approved claimant receives a separate, expiring account invitation and may edit
  a private provider-supplied draft. Saving the draft does not publish it, change ONRC
  facts, or establish verified services and coverage. Only an account created through
  the audited conversion of an unlisted-company registration may privately select known
  categories and exact SIRUTA localities while current ONRC authorization is unavailable.
  It cannot submit, enter review, or publish that revision until authorization resolves
  and the provider saves it again against the current ONRC and SIRUTA pins. An established
  catalogue provider whose ONRC source becomes unavailable cannot edit services or
  coverage; its previously saved private data remains intact. Once authorization is
  current, services must fit its legal ceiling; staff may then approve the exact submitted
  revision or request changes with provider-safe feedback. A later edit invalidates that
  review.
- An approved service-and-coverage declaration can be included with voluntary profile
  fields and a sanitized private portfolio in one immutable publication submission.
  Staff review and visibility activation are separate, permission-gated decisions.
  Provider profiles are discoverable by their exact declared SIRUTA coverage and
  service category, separately from registered-office ONRC rows, and the provider may
  withdraw visibility immediately. Current catalogues authorize only clearly labelled
  development previews; real public profiles remain blocked until the exact ONRC/MF
  source run receives a valid, revocable legal publication approval.
- A provider may declare current availability and one preferred public contact method.
  The preferred method must have a corresponding visible value. Both declarations are
  copied into the reviewed publication snapshot and remain explicitly provider-supplied;
  they are not proof of response time, capacity, availability, or acceptance of work.
- A provider owner may keep a private, revisioned customer contact register with a name,
  at least one contact channel, optional address and private notes. Every create or update
  requires an explicit lawful-use confirmation; archiving keeps the record and its PII-free
  event history. A manual contact never creates a customer account, sends an e-mail, or
  grants portal access, and another provider cannot read it.
- A provider may optionally supply one normalized professional address. It is never
  inferred from the ONRC registered office and becomes visible only as part of a
  separately reviewed, immutable publication snapshot. Legacy snapshots cannot expose
  a migrated address field that was not part of their reviewed contract.
- Professional profile visibility also requires a separate active subscription
  entitlement. The first implementation is an explicitly labelled, administrator-
  activated 30-day test period and processes no payment. Expiry or deactivation hides
  the approved professional snapshot on the next request without deleting its review;
  reactivation restores it only if every other publication gate still passes.
- A visitor can send a structured quote request only from a currently visible professional
  profile. The request is pinned to that exact approved snapshot and one declared service
  and SIRUTA locality; it collects contact details, project description, budget and desired
  start period, but publishes none of them. A secret-keyed session digest bounds repeated
  submissions without retaining an IP address. A signed form token and unique stored
  digest additionally reject a replay of the same request before any notification.
- For an active direct or multi-provider request, the firm can propose a future
  visit time and a short private note. The client accepts or declines in their
  existing private workspace; a proposal alone never means a confirmed visit.
  Only one live proposal exists per firm/request, an elapsed proposal can be
  replaced, and a confirmed visit is visible to both sides. Real payment is not
  part of scheduling.
  Either party can cancel a confirmed visit and the firm can withdraw a pending
  proposal. Cancellation is recorded with its initiator and frees the request
  for a new proposed time without erasing an already sent quote.
  Accepting an offer opens one private work-order record for that exact provider
  and accepted quote. Initially it is only "to be scheduled" in both private
  workspaces. The provider can then schedule execution and explicitly mark it
  complete after the scheduled time. A future booking can be cancelled without
  cancelling the accepted quote or job; the customer is notified and the job
  returns to "to be scheduled". A private weekly agenda shows scheduled
  start times and optional provider-estimated end times without claiming to
  reserve team availability. The agenda marks overlapping known intervals as
  an advisory, not as a confirmed team conflict.
  The owner can invite technicians by e-mail, assign a scheduled job and
  revoke access. Technicians accept a 48-hour invitation using a matching
  account or new credentials, then see only their own assigned scheduled jobs
  in a bounded workspace. They can confirm the start after the scheduled time
  and then explicitly confirm completion; both actions record actor and revision.
  Once execution starts the owner cannot rebook or reassign that job, but may
  still close it if technician access is revoked. The technician cannot access
  the owner's request inbox or billing drafts.
  The owner and technician see an advisory warning when two complete estimated
  intervals overlap for the same active technician. It does not reserve capacity
  or infer an end time for an open-ended job.
  Only then may the provider prepare a private,
  editable billing draft from the accepted offer. This draft is not an issued
  fiscal invoice, is not sent to the customer and records no payment or warranty.
  Separately, the owner may save private, revisioned issuer details declared by
  the firm. They do not overwrite ONRC facts or qualify the firm to issue a fiscal
  document through the platform.
- A customer may create a free account with first name, last name, username, e-mail and a
  confirmed password. The account activates immediately without an e-mail link and opens a
  separate Nordic Pro portal for searches, single-provider requests, multi-provider quote
  comparisons, conversations and current project status. Signed-in requests take identity
  from the account and remain linked by explicit ownership; anonymous request links continue
  to work for visitors who do not create an account. A customer who forgets the password
  can request a single-use reset link by e-mail; the response does not reveal whether
  an account exists, and only a still-active customer account may use the link. A signed-in
  customer can also change the password after proving the current one; that session stays
  active while other sessions are invalidated. The private project dashboard pages
  single-provider requests and multi-provider comparisons separately (ten per page),
  preserving each list's position while keeping other customers' projects out of view.
  Within each list, still-valid offers awaiting a response appear first, followed by
  the latest provider offer or message activity. The portal does not claim a message
  is unread because message read state is not tracked. A separate "Offers to review"
  filter shows only those currently actionable projects, with a clear empty state;
  each list retains independent pagination and filter state in the URL. When a
  provider sends an offer or message to an account-owned project, the activity
  e-mail links directly to its login-guarded single or comparison workspace;
  anonymous customers continue to use their original private capability link.
- A visitor can also describe one project once and dispatch it to every currently visible
  provider whose active subscription, reviewed service and exact SIRUTA locality match.
  Each provider receives a separate snapshot-pinned lead and cannot read the other providers'
  responses; registry-only and unsubscribed firms receive nothing. The form previews
  the current recipient count after exact service and locality selection, and checks
  eligibility again when the project is submitted. A signed form token and unique
  server-side digest prevent a replayed submission from creating another project;
  opening a fresh form permits a separate, intentional request.
- The verified owner receives a notification containing the customer's name and request scope,
  while contact data and the full project remain only in the private provider inbox. The owner
  can move it through a constrained,
  audited status funnel, retain private notes and see aggregate new, 30-day, won and
  conversion counts. Completed or declined request identity and free text are anonymized
  by the configured retention workflow. A notification opens the exact owner-only
  request even when it has moved to a later inbox page; the link contains only an
  opaque request id, not customer contact or an access token.
- If a provider notification e-mail fails, authorized staff can retry it individually
  from the administrative record after acknowledging possible duplicate delivery;
  this does not alter the request or send customer contact data by e-mail.
- A visible provider profile records daily deduplicated views and explicit phone, e-mail,
  website and quote-request actions. The owner can compare aggregate totals over 7, 30 or
  90 days. Measurement stores no IP address and uses a secret-keyed session digest salted
  by local date, so it cannot become a stable cross-day visitor identity.
  An operator-reviewed retention command removes these digest rows after the longest
  90-day reporting window; browsing a profile never performs the purge.
- The customer receives a time-bounded private link whose secret is never stored in clear
  text. In that workspace the provider can send versioned, immutable quotes and both sides
  can exchange append-only messages. Only the current unexpired quote can be accepted or
  declined; the choice updates the audited request funnel. Notification e-mails announce
  activity without copying the quote or conversation body.
  Each sent quote contains immutable priced line items with description, quantity, unit
  and unit price. The server derives the quote total from those lines, while the browser
  calculation is only immediate feedback. These are commercial quote details, not fiscal
  invoice or VAT lines.
- If that initial e-mail fails for an anonymous customer, separately authorized staff
  can reissue a new private link from Admin. The earlier link stops working, its original
  expiry does not change, and the action is recorded. Account-owned projects use the
  customer portal instead of a bearer-link resend. Admin lists let staff filter only
  currently recoverable customer e-mails, counting a multi-firm request once.
- On an anonymous submission whose customer e-mail fails, the confirmation alone
  offers the private workspace link immediately. The customer is asked to save it;
  normal confirmations and later form visits do not expose the link.
- Operations staff can run a read-only delivery audit that counts failed or pending
  firm notices and failed anonymous-customer links without listing identities. It
  separates links staff can reissue from expired links and flags inconsistent
  multi-firm delivery; no messages are resent by the audit.
- Staff with permission for aggregate request reports can also inspect those
  delivery counts in Admin and open matching private filtered queues, including
  expired links and comparisons with inconsistent delivery states. The summary page
  itself shows no customer identity and cannot resend messages. Firm-notification
  queues exclude requests whose private data has already been retained.
- For a request sent to several providers, one parent capability opens a single comparison
  workspace containing the separate offer and conversation for each child lead. The customer
  can accept only one valid offer; that decision atomically declines every competing live
  offer and closes the sibling leads so the project cannot be awarded twice.
- Separately authorized operations staff can inspect an identity-free demand perspective
  for exact 7, 30 or 90-day windows. It groups submitted customer projects by service and
  exact county/SIRUTA locality, then distinguishes projects from provider deliveries,
  responses and awarded work. One request sent to several providers remains one customer
  project in demand totals. The perspective is GET-only, exposes no customer or provider
  identity and does not treat catalogue searches as demand.
- The staff-only pilot dashboard compares one county and service against the current
  source-publication gate, effectively visible public providers, separate development
  previews, and recent submitted demand. It marks exact localities with requests but
  no provider quote, without showing customer or provider identities. The dashboard
  also shows distinct projects with an offer, projects with an accepted offer, and the
  mean time to a first offer. It cannot activate a listing or replace the production
  launch audit.
- A customer may leave one immutable review only after accepting a quote through that
  private workspace. The review stores a 1–5 rating, bounded text, explicit display consent
  and a minimized public name. It remains private until separately permissioned staff record
  an approve or reject decision with a required reason; approved reviews appear on the
  provider profile as customer evidence, never as a platform endorsement or ranking signal.
- The active provider may submit one immutable response to each approved review. The
  response remains private until a separate staff moderation decision and appears nested
  under the review only when approved; it cannot change the customer's text or rating.
- A visitor may save up to six currently visible professional profiles in the current
  browser session without creating an account. Each entry retains only the opaque provider
  identifier and exact search scope; the saved-firms page resolves it again through the
  normal publication and subscription gates, and silently removes entries that are no
  longer visible. The list is a comparison convenience, never a ranking or endorsement.
- A visitor may separately save up to six currently visible ONRC company records from
  their detail pages, not crowded search results. The session retains only business
  identity and exact county, locality and service scope; the saved view rechecks the active catalogue before
  rendering and clearly distinguishes registry facts from complete provider profiles.
- Every curated service has a bilingual locality landing page with a readable county and
  locality slug plus the authoritative SIRUTA code. It presents the same complete-provider
  and ONRC result branches as ordinary search, never a separate SEO copy of the catalogue.
  Demo and internal-preview pages remain `noindex`; indexing is allowed only when the exact
  catalogue scope passes the existing public approval boundary.
- The public subscription page compares three offers: the free legal catalogue presence,
  the operator-configurable Essential profile proposal, and a higher Partner proposal.
  Partner includes Essential plus a managed presentation site of up to five pages,
  hosting, SSL, backup, maintenance, lead/appointment forms, basic local SEO, analytics,
  two monthly content updates and a monthly report. Domain, paid licenses, advertising
  and bespoke features are quoted separately after a brief and delivery review.
- Partner is a human-delivered commercial service, not a broader marketplace entitlement.
  Its action opens an owner-only, consented intake that records a bounded brief for staff
  follow-up and sends only an identity-free record pointer by e-mail. Intake is limited to
  three requests per profile in 24 hours, enters the configured retention workflow, does
  not use the simulated subscription checkout and creates no subscription or payment record.
- Until real billing is approved, an explicitly configured simulated checkout lets an
  authenticated provider activate one idempotent 30-day demo entitlement. It collects no
  card or billing fields, creates no transaction, receipt or invoice, remains unavailable
  in read-only preview, and records its zero-payment provenance in the subscription audit.
- Authorized operations staff may order service categories, pause new-provider intake, or
  hide a category from public discovery. Pausing does not remove the service from customer
  search; hiding removes it from search and canonical service pages. Neither action edits
  CAEN-derived facts, existing provider declarations, reviewed submissions, or publication
  history, and providers retain valid services they already selected.
- An active provider may request a single-use password-reset link. The public response
  is identical for known, unknown, or revoked addresses; sends are bounded, and a
  revoked membership invalidates an already issued link without restoring access.
- An authenticated provider with active ownership may voluntarily change the account
  password by proving the current password and satisfying the configured password
  policy. The current session stays open, all other sessions become invalid, and no
  profile, service, coverage, moderation or publication state changes.
- The private dashboard exposes a five-stage publication-readiness guide derived from
  the actual submission rules: public profile content and contact, approved services
  and exact coverage, a valid portfolio, an active subscription, then controlled publication. Each stage links
  to its work area and distinguishes missing work, administrative review, requested
  changes and visibility; readiness is never presented as verification or recommendation.
- A visitor may privately report a factual problem only from a currently visible
  provider profile. The report is tied to the exact published version the visitor saw,
  collects a reason and description but no name, contact details or IP address, and uses
  only a secret-keyed session digest to prevent duplicate reports for that version.
  Reports enter a read-only administrative queue; they are not displayed publicly, do
  not prove wrongdoing and do not withdraw a profile automatically. A separately
  permissioned staff triage case can move only from new to in review to closed, records
  an append-only decision history, and is blocked if the exact reported snapshot no
  longer passes its integrity contract. Triage cannot edit the report, snapshot, profile
  or publication state, and staff cannot review a report about their own provider
  profile. If that publication version is no longer visible, the intake route is
  unavailable.
- Authorized operations staff may inspect a separate aggregate perspective over the
  private report queue. It shows all-time current case states, exact rolling 7, 30 or
  90-day intake and immutable-event counts, plus reports missing a required case. It
  exposes no provider or visitor identities, report details, staff notes, actors or
  drilldowns, and cannot change triage, publication or profile state.
- Operations may run `python manage.py audit_public_provider_report_triage` to verify
  the currently persisted report, case and event chain. It emits only identity-free
  JSON totals and anomaly counts, fails with a non-zero exit status on drift, and never
  repairs or changes records. Passing the audit proves current contract consistency,
  not cryptographically immutable row history.
- Authorized privacy staff may register requests received through the published privacy
  contact and process them in a private deadline-aware queue. Intake is immutable, the
  initial deadline is one calendar month, identity confirmation is proportionate, and a
  single two-month extension requires prior notification and a recorded reason. Every
  transition is audited; closing the case records the response but never automatically
  changes unrelated accounts, profiles, reports or publication state.
- For a verified access or portability case in analysis, authorized privacy staff may
  generate a structured JSON package from exact e-mail and explicit provider-ownership
  links. It excludes credentials, security records, staff identities, moderation notes,
  unrelated people and binary media, is streamed without server-side file persistence,
  and records its SHA-256 without closing the request.
- Operations may run `python manage.py audit_data_subject_requests` to reconstruct every
  personal-data request event chain and verify revisions, status, deadlines, extension,
  chronology and event metadata. The command exposes only aggregate counts, never
  requester details, fails non-zero on drift and does not repair records.
- The locality selector uses the official SIRUTA S1 2025 catalogue; the initial commercial launch area remains an open decision.

## Brand Commitments

The confirmed public brand is ServiciiAproape: a broad, locality-first name that includes both individual tradespeople and companies. Its visual world is “Jurnalul de cartier”: a light, masculine local directory with warm paper, editorial serif headlines, precise rules and functional service icons. It must remain airy and trustworthy rather than dark, heavy or industrial.

## Evidence on Hand

The official ONRC snapshot dated 8 July 2026 is selected as the legal-company source under CC BY 4.0. It supplies legal entities, registered offices, statuses, and authorized CAEN activities, but not reliable marketplace contact details, service coverage, availability, quality, testimonials, ratings, logos, or provider verification. The interface must distinguish registry facts from provider-supplied and verified claims.

## Product Principles

- Place comes first.
- Every home need should have a clear category.
- Trust must be earned through real verification, never invented badges or claims.
- The first useful action should be obvious within seconds.

## Accessibility & Inclusion

The core search must work with keyboard, touch, and without JavaScript. Romanian copy
uses diacritics, English copy preserves the same factual boundaries, and both languages
keep labels visible. The phone service index retains all seven choices in two columns,
and language controls provide at least `44px` touch targets.
- Providers can follow Partner discussions as received, contacted, proposal sent, accepted
  or closed. Operator notes remain private; status changes are permissioned and audited.
  Acceptance never activates billing, the Essential subscription, or public visibility.
