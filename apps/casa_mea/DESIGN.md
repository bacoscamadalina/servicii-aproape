---
name: ServiciiAproape
description: O ediție locală vie, caldă și precisă pentru servicii dedicate casei.
colors:
  editorial-ground: "#fcf9f2"
  editorial-ink: "#0f3425"
  editorial-coral: "#fd6049"
  editorial-lavender: "#e7caf7"
  editorial-mint: "#c9e8d1"
  deep-ink: "#1f3331"
  soft-ink: "#526964"
  warm-paper: "#eeeee8"
  deep-paper: "#dfe5dc"
  clean-paper: "#fffefa"
  editorial-line: "#aeb6b0"
  muted-brick: "#bd6749"
  deep-brick: "#985039"
  quiet-sage: "#365e55"
  error-red: "#a43b2f"
  field-ink: "#2a454c"
  field-line: "#768789"
typography:
  display:
    fontFamily: "Nimbus Narrow Local, sans-serif"
    fontSize: "clamp(3.7rem, 7.2vw, 6rem)"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Nimbus Narrow Local, sans-serif"
    fontSize: "clamp(2rem, 4vw, 3.3rem)"
    fontWeight: 900
    lineHeight: 1.05
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Nimbus Narrow Local, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 800
    lineHeight: 1.1
  body:
    fontFamily: "Carlito Local, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Carlito Local, sans-serif"
    fontSize: "0.76rem"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "0.03em"
rounded:
  square: "0"
  control: "10px"
  editorial-control: "12px"
  panel: "16px"
  circular: "50%"
spacing:
  xs: "6px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.quiet-sage}"
    textColor: "{colors.clean-paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "54px"
  button-primary-hover:
    backgroundColor: "{colors.deep-ink}"
    textColor: "{colors.clean-paper}"
  input-editorial:
    backgroundColor: "{colors.clean-paper}"
    textColor: "{colors.deep-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "54px"
  navigation-action:
    backgroundColor: "transparent"
    textColor: "{colors.deep-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 17px"
    height: "46px"
  status-tag:
    backgroundColor: "{colors.quiet-sage}"
    textColor: "{colors.clean-paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  button-home-search:
    backgroundColor: "{colors.editorial-coral}"
    textColor: "{colors.editorial-ground}"
    typography: "{typography.label}"
    rounded: "{rounded.editorial-control}"
    padding: "0 18px"
    height: "58px"
---

# Design System: ServiciiAproape

## Overview

**Creative North Star: "Ediția locală — Comunitatea în mișcare"**

ServiciiAproape este o ediție locală contemporană pe toate suprafețele: hârtie caldă, tuș verde, coral decisiv, fotografii documentare și repere grafice inspirate de machetele tipărite. Catalogul, profilurile, formularele, conturile client/furnizor și administrația folosesc aceeași identitate; densitatea diferă după sarcină, însă adevărul și autoritatea fiecărui flux rămân neschimbate.

Noua pagină principală nu imită un marketplace generic. Titlul foarte comprimat, colajul cu meseriași în acțiune, sigiliul lavandă și căutarea numerotată formează o compoziție asimetrică recognoscibilă. Căutarea după județ, localitate și serviciu rămâne instrumentul principal, iar toate limitele de adevăr, autorizare și proveniență a datelor rămân neschimbate în timpul migrării vizuale.

Motion on the home page behaves like editorial explanation, not decoration. One localized 29-second narrated promotion film opens with a realistic male presenter, then carries the authored focal sequence: project → local search → complete company profile → contact. Its neural male narration is rendered locally from pinned source audio, playback is user-initiated, captions are available by default, and sound never starts unexpectedly. The surrounding interface remains restrained: the headline makes one transform-only entrance, the search instrument's brick top rule draws once, and subsequent UI movement is limited to focused-field, search-button, category and playback feedback. Supporting process text remains static. Reduced motion keeps the film on its static cover until explicit playback and renders the surrounding interface in its complete final state immediately.

**Final design review verdict:** SHIP.

**Key Characteristics:**

- Warm uncoated-paper canvas, deep editorial ink, coral action, lavender identity, and mint working states across the product.
- Nimbus Narrow Local for strong display hierarchy; Carlito Local for body copy, controls, and labels.
- An asymmetric photographic collage with restrained print-register geometry rather than a generic hero card.
- An immediate county → optional locality → optional service search instrument with visible labels and caveats.
- A desktop hero that pairs headline and numbered search with three documentary trade photographs; phone preserves the collage before the stacked search.
- One localized, narrated home promotion film with a realistic presenter, captions and explicit playback control, backed by restrained interaction-triggered UI feedback.
- Six numbered service rubrics with custom consistent-stroke SVG illustrations.
- Truthful distinctions between ONRC facts, provider declarations, administrative review, internal preview, and public visibility.
- One featured approved-provider fact sheet followed by compact, scalable ONRC rows.
- Six columns on wide screens, three on tablet, and two on phone for the service index.

## Colors

Paleta produsului este caldă și editorială: verdele de tuș structurează lectura, coralul marchează acțiunea principală, lavanda aparține identității circulare, iar menta grupează controale și stări fără a deveni badge de încredere. Vechile nuanțe Nordic Pro rămân doar compatibilitate internă, nu o a doua temă vizuală.

### Primary

- **Editorial Ink** (`editorial-ink`): text, reguli, navigație și desenul logo-ului pe toate suprafețele.
- **Editorial Coral** (`editorial-coral`): acțiunea de căutare și punctuația decisivă din colaj.
- **Quiet Sage** (`quiet-sage`): culoarea principală pentru acțiuni, structură și stări active.
- **Muted Brick** (`muted-brick`): accent de brand, selecție și punctuație vizuală.
- **Deep Brick** (`deep-brick`): accent de hover și contrast secundar.

### Secondary

- **Editorial Lavender** (`editorial-lavender`): sigiliul și marcajul rotund al identității, folosit rar.
- **Editorial Mint** (`editorial-mint`): planuri secundare în colaj și acțiunea profesională din masthead.
- **Deep Paper** (`deep-paper`): fundal secundar pentru grupare și separare tonală.

### Neutral

- **Editorial Ground** (`editorial-ground`): hârtia caldă a întregului produs.
- **Deep Ink** (`deep-ink`): primary text, strong rules, outlined marks, and high-contrast structure.
- **Soft Ink** (`soft-ink`): explanatory copy, metadata, and secondary labels.
- **Warm Paper** (`warm-paper`): default page canvas.
- **Deep Paper** (`deep-paper`): subdued facts, inactive fields, and secondary tonal separation.
- **Clean Paper** (`clean-paper`): interactive fields and restrained rubric hover lift.
- **Editorial Line** (`editorial-line`): hairline and dotted dividers.
- **Field Ink / Field Line** (`field-ink`, `field-line`): inherited private and administrative workflow fields where a dark working surface remains necessary.
- **Error Red** (`error-red`): adjacent validation and explicit failed or blocked states.

**The Coral-Is-The-Primary-Action Rule.** Coralul aparține acțiunii primare, numerelor și reperelor mici; nu devine un fundal de secțiune.

**The Legacy-Brick Rule.** Muted brick rămâne numai pentru compatibilitatea componentelor vechi; noile acțiuni folosesc coralul editorial.

**The Paper-Stays-Warm Rule.** Default reading surfaces remain warm paper. Clean paper is a controlled interaction lift, not a replacement page background.

**The Truth-Needs-Words Rule.** Sage, brick, and red can accelerate scanning, but status copy must name what is declared, reviewed, blocked, previewed, or public.

## Typography

**Display Font:** Nimbus Narrow Local (with `sans-serif` fallback)
**Body Font:** Carlito Local (with `sans-serif` fallback)

**Character:** Nimbus Narrow Local oferă o voce compactă, arhitecturală și modernă. Carlito păstrează formularele, navigarea, explicațiile și fluxurile operaționale directe și foarte lizibile.

### Hierarchy

- **Display** (weight `900`, fluid `clamp(3.7rem, 7.2vw, 6rem)`, line-height `0.9`): promisiunea principală; pe telefon `clamp(3rem, 15vw, 4.35rem)`.
- **Headline** (weight `900`, fluid `clamp(2rem, 4vw, 3.3rem)`, line-height `1.05`): titluri majore de secțiune și detaliu.
- **Title** (weight `800`, `1.2rem`, line-height `1.1`): titluri de card și grupuri compacte.
- **Body** (weight `400`, `1rem`, line-height `1.5`): instructions, facts, and caveats; long measures stay near `68ch`–`74ch`.
- **Label** (weight `700`, `0.76rem`, modest `0.03em` tracking): visible form labels, navigation, actions, and metadata.
- **Brand / micro-label** (`1.1rem`–`1.35rem` pentru wordmark; `0.62rem`–`0.72rem` pentru etichete rare): rezervat identității și metadatelor compacte, nu textului de citire.
- **Workspace display** (weight `900`, fluid `clamp(3.5rem, 7vw, 6rem)`): titlul unic al autentificării sau al unui portal fără a concura cu display-ul principal.
- **Project-route display** (weight `900`, fluid `clamp(3.2rem, 7vw, 6.5rem)`; phone `clamp(2.8rem, 15vw, 4.4rem)`): titlul de orientare al portalului client și starea goală. Etapele folosesc `clamp(1.25rem, 2vw, 1.7rem)`, iar acțiunea contextuală `clamp(1.35rem, 2.4vw, 1.9rem)`; micro-etichetele rămân între `0.69rem` și `0.82rem`.

**The Sans-Leads Rule.** Nimbus stabilește ierarhia vizuală; controalele, etichetele, textul lung, datele dense și administrația rămân în Carlito.

## Layout

The public shell uses a centered `1240px` maximum width with `64px` total viewport inset. It narrows to a `760px` reading column below `980px`, with `32px` total inset, then to `24px` total inset below `560px`. At the supported `320px` viewport, content, controls, metadata, and actions must remain within the canvas without horizontal overflow. The header is framed by a strong top rule and hairline bottom rule; the category index continues that newspaper datum line.

Hero-ul migrat folosește două coloane: titlu și căutare numerotată în stânga, colaj fotografic în dreapta. Formularul nu este un card; trei rânduri plate, numerotate `01–03`, păstrează județul, localitatea dependentă și serviciul în ordinea reală. Butonul coral de `58px` închide instrumentul. La maximum `900px`, ordinea devine titlu → colaj → formular; sub `560px`, fotografiile se suprapun într-un cadru de `410px`, notele dispar, iar formularul rămâne complet și fără overflow.

The home lead uses deliberate asymmetry on wide screens and a single reading column on narrow screens. Do not repeat service navigation, quick-city links or search instructions above the form. The photographic collage, numbered search and rotating seal carry the personality; no route graph or animated process copy belongs in the hero.

The service index contains seven Nordic service rubrics in a balanced four-plus-three desktop grid and two columns on phone. Every rubric retains its complete title, icon and supporting label in both Romanian and English; translation must not collapse it into an icon-only index. Fine rules divide rubrics without turning them into a heavy card grid. The promotion film follows the service index and carries the only narrative explanation; do not repeat it with a separate process section.

The public provider profile opens as one ordered project sheet. Provider identity leads a
compact first field; a supporting summary beside it groups the offered service and the
visitor's searched locality. Claim ownership and administrative workflow state remain
private and never appear as customer-facing profile content. The reading sheet then
places the company presentation on the left and one complete clean-paper contact directory
on the right, keeping phone, public contact e-mail, address, website and exact service areas
together. On phone, the order becomes identity → status and service fit → contact directory →
description and services → work photographs, matching urgent contact intent without splitting
one task across multiple bands. Portfolio images always preserve their original aspect ratio:
one image is centered at a controlled width, multiple images form a two-column gallery, and
phone layouts return every image to one column. Images are never cropped to fit a preset frame.

The general project intake extends the same Nordic Pro grammar without becoming a wizard:
one numbered location/service section, one project section and one explicit privacy/action
footer. The private comparison workspace starts with one shared project summary, uses a
compact provider anchor strip, then gives every provider an equal flat response row with
its own quote and conversation. No provider is presented as first, best or recommended;
accepting one offer is the only emphasized decision state.

Search results use deliberate asymmetric density. An approved provider is featured once
as a clean-paper summary without portfolio imagery; work photographs belong exclusively
to the full provider profile. Its summary keeps the name, short description, and category
together, while declared service and searched locality lead to one `44px` profile action.
On phone, the facts share two columns and the action becomes full width. Ordinary ONRC results remain compact
ruled rows before and after the featured sheet so pagination can scale to hundreds without
turning the registry into a card feed.

Provider, claim, moderation, publication, password, and administrative surfaces keep their existing task-first responsive sequence. Their authorization and data-provenance boundaries outrank cosmetic reuse: private drafts stay private, review remains revision-specific, and administrative preview stays inert.

The customer-request form is a single Nordic Pro working sheet reached from the public
contact directory. Its heading confirms the exact company and locality before the form;
contact facts form a two-column grid on desktop and one column on phone. Labels remain
visible, optional location copy explains that a precise home address is unnecessary, and
the consent statement sits next to its checkbox rather than becoming fine print.

The provider activity area is a private operational surface, not a marketing dashboard.
One compact, sticky two-item navigation separates the customer-request inbox from profile
performance, so the owner sees only one working context at a time. The inbox begins with a
ruled four-value band for new, recent, total and accepted requests. Each request is one
complete white sheet with customer identity, project facts, direct contact actions and one
bounded status/notes control; quotation and conversation remain in a native expandable
workspace until needed. The surface stacks without horizontal overflow at `390px` and
never exposes customer data on public pages or in notification e-mails.

Quotation and conversation extend each request sheet as two aligned operational regions,
not a second dashboard: the complete quote form and its latest immutable revision sit next
to the shared message thread. The customer follows an e-mailed private link into a calm
workspace that leads with their submitted project, gives the current quote equal visual
weight, and keeps the append-only conversation below. Accept and decline are explicit,
keyboard-visible actions; desktop becomes one column below `900px`, and every action stacks
at `560px` without horizontal overflow.

The public quote-request route continues Nordic Pro as one calm two-column work surface:
provider and locality context remain visible beside a single labelled form, with no repeated
marketing card stack. On phones context precedes the form and every control remains at least
`44px`. The private request inbox is a real task queue rather than a decorative dashboard:
one ruled aggregate band precedes chronological lead sheets, customer contact and project
facts remain grouped, and the status/notes action stays visibly separate from immutable
intake. Empty state copy explains where requests originate without inventing sample data.

Subscription status is a compact ruled workflow fact, never a pricing card or trust
badge. The provider sees whether the entitlement is active, expired, or inactive and
that the current test mechanism records no payment. Only the administrative preview
exposes the explicit activation/deactivation form.

The temporary simulated checkout extends the same Nordic Pro working surface: the plan,
displayed price and 30-day demo period form a ruled summary, while one clean-paper sheet
contains the explicit acknowledgement and activation action. It never collects financial
fields and repeats in plain language that no payment, invoice or obligation is created.
The confirmation page names the active period and states that no payment was processed.

**The County-First Rule.** Preserve the visible county → optional locality dependency and the complete primary action before supporting explanation at every viewport. The empty locality option always means all localities in the selected county.

**The Four–Three–Two Rule.** The seven service rubrics render in balanced rows of four and three on desktop and two columns on phone; do not collapse them into a generic one-column card feed.

## Elevation & Depth

Ediția locală folosește adâncimea mai ales în colaj: fotografiile primesc o umbră ambientală moale, iar textul, navigarea, registrele și majoritatea formularelor rămân plate și sunt separate prin reguli fine. O acțiune primară poate primi o singură umbră funcțională; administrația și suprafețele dense nu devin feed-uri de carduri.

### Shadow Vocabulary

- **Editorial photo lift** (`0 20px 50px rgba(15, 52, 37, 0.13)`): exclusiv fotografiile suprapuse din colajul paginii principale.
- **Inherited working instrument** (`0 18px 42px rgba(33, 56, 66, 0.1)`): legacy private or administrative task surfaces only; never an ordinary public container.
- **Featured provider sheet** (`0 14px 34px rgba(33, 56, 66, 0.08)`): the single approved-provider search result only; never repeated on ONRC rows.

**The Collage-Owns-Depth Rule.** Pe pagina principală migrată, doar fotografiile au adâncime; formularul, serviciile și navigarea rămân plate. Nu repeta umbra colajului într-un feed de carduri.

## Shapes

Întregul produs folosește muchii drepte pentru structură și cercuri pentru logo/sigiliu. Scara de raze este `0`, `7px`, `8px`, `10px`, `12px`, `14px`, `16px`: valorile mici apar numai pe controale și grupuri interactive, iar panourile editoriale rămân drepte. Colajul folosește decupaje fotografice ușor rotite.

**The Editorial Shape Rule.** Pe suprafețele migrate, muchiile drepte și liniile fine construiesc pagina; radius-ul este rezervat acțiunilor, nu fiecărui container.

**The One-Hand Rule.** All field and category icons should look drawn by one hand: consistent stroke weight, no emoji, no icon-font substitutions, and no decorative filled badges.

## Components

### Buttons

- **Shape:** home search uses `12px` radius and `58px` height; established workflow actions remain at least `48px`.
- **Primary:** coral editorial cu text deschis pentru acțiunile dominante; verdele profund este hover-ul și acțiunea secundară de lucru.
- **Hover / Focus:** deep editorial ink on home hover with a `2px` lift; visible focus outline remains mandatory.
- **Secondary:** transparent or deep-ink outlined actions with at least a `44px`–`48px` touch height.

### Status Tags

- **Style:** compact `8px` labels using quiet sage, deep paper, or an established state tone with explicit text.
- **State:** color never substitutes for “declarată”, “în verificare”, “preview intern”, “public”, “retras”, or “blocat”.

### Cards / Containers

- **Corner Style:** `16px` for major panels, `10px` for compact interactive containers, square only for dense ledger rows.
- **Background:** warm paper by default; clean paper for controlled hover; deep paper for quiet factual grouping.
- **Shadow Strategy:** none on public containers and catalogue rows.
- **Border:** deep-ink hairlines for major boundaries; editorial-line hairlines or dots internally.
- **Internal Padding:** typically `16px`–`24px`; larger reading sheets use `28px`–`32px`.

### Inputs / Fields

- **Style:** câmpurile paginii principale sunt rânduri transparente, numerotate `01–03`; fluxurile de lucru folosesc câmpuri clean-paper cu etichete verde-închis și contrast constant, inclusiv la autofill.
- **Focus:** focus-ul rămâne vizibil și coral pe toate suprafețele.
- **Error / Disabled:** errors sit adjacent in error red; locality stays disabled until county supplies authoritative SIRUTA choices.

**The County-Owns-Locality Rule.** Never show locality as independent free text or retain choices from a previous county. Loading, empty, failure, and no-JavaScript states keep the visible county → locality sequence.

### Navigation

The migrated masthead pairs a compact Carlito wordmark with the lavender circular house-and-wrench mark. Links remain flat; the professional action uses a mint `12px` field, and language is one compact dropdown. On phone, navigation becomes a full-width details control below the brand while language remains visible.

The RO/EN language switch is a compact pair of square editorial controls in the
masthead. Each target is at least `44px`, names its language natively and exposes the
current choice programmatically. It preserves the current page and query state instead
of sending the visitor back to the home page. The control remains visible on phone and
uses the existing ink, paper, brick and focus vocabulary; it is not a pill, flag or
decorative badge.

**The Same-Journal Rule.** English is the same locality-first journal with translated
labels and copy, not a separate visual theme. Longer English labels may wrap without
removing information, changing the two-column phone service index or weakening touch
targets.

### Customer Project Route

„Proiectele mele” este o hartă de lucru, nu un panou de carduri. Un traseu constant
`Cerere → Ofertă → Lucrare → Finalizare` introduce modelul mental, iar fiecare proiect
repetă compact aceleași etape lângă informațiile reale și un singur „Următorul pas”.
Proiectele care cer răspuns primesc numai o regulă coral de prioritate; culoarea nu
înlocuiește textul stării și nu inventează etape pe care datele încă nu le confirmă.

Starea goală explică primul pas și previzualizează forma viitorului proiect. Pe telefon,
traseul general devine patru rânduri, iar traseul unui proiect devine o linie orizontală
compactă înaintea conținutului; acțiunile rămân late și ușor de atins. Interfața în engleză
folosește aceeași ordine, structură și prioritate.

**The Current-Step-Is-Explicit Rule.** Etapa curentă și acțiunea următoare trebuie numite
în cuvinte. Coralul marchează atenția, dar nu substituie starea operațională.

### Local Service Atelier

Paginile canonice de serviciu folosesc compoziția „Atelier vizual”: un hero împărțit
între titlul serviciului și o fotografie documentară specifică acelei categorii, urmat
imediat de o bandă factuală cu serviciul, localitatea și acțiunea de schimbare a
căutării. Fotografia este întotdeauna etichetată drept ilustrativă și nu poate sugera
că reprezintă o lucrare a firmelor listate.

Profilurile complete publicate sunt foi editoriale ample, fără a deveni clasament sau
recomandare. Înregistrările ONRC rămân rânduri compacte, paginate și ușor de scanat;
proveniența datelor și limitele catalogului rămân lângă rezultate. La maximum `900px`,
hero-ul se așază în ordinea titlu → fotografie → criterii, iar sub `640px` toate
acțiunile devin late, cu ținte de minimum `44px`, fără overflow orizontal.

**The Illustrative-Photo-Is-Not-Proof Rule.** Fotografia de categorie oferă orientare
vizuală, nu dovadă de portofoliu, disponibilitate, calitate, clasament sau recomandare.

### Public Professional Entry

The public “Pentru profesioniști” page uses the same flat editorial grammar to explain
a gated operational path, not open sign-up: active ONRC catalogue record → claim →
e-mail confirmation and administrative review → activation invitation → provider
profile completed and reviewed separately. Its wide layout pairs a large serif lead
with restrained explanatory copy, then turns the path into numbered ruled rows and
ends with an explicit legal-data/profile boundary. Below `850px` these regions become
one reading column, and the stage band wraps across rows rather than clipping or
forcing horizontal overflow.

The hero action hierarchy starts with two decision-path calls to action: one for a
company that already exists in the catalogue and one for a company that is absent.
Subscription details and provider login follow as compact resource links; they must
not compete visually with or interrupt those two starts. The decision-path actions sit
side by side only above `980px` and stack at `980px` and below, while the resource links
remain a separate, compact group that can wrap without horizontal overflow.

**The Decision-Path-Before-Resources Rule.** Preserve the two catalogue-presence
choices as the hero's dominant actions; subscription and login remain secondary
resources at every viewport.

The home-page professional strip reuses this hierarchy in a narrower format: two
stacked, equal-width route actions lead first—claim an existing catalogue company,
then register a missing company—followed by compact subscription and provider-login
resource links. The overall strip becomes one column at `850px` and below. It must
never flatten these distinct levels into a `2 × 2` matrix of equal buttons.

The linked subscription page compares three distinct choices in one reading order:
free catalogue presence, the green Essential software entitlement and the white Partner
managed-service card. The three-column row remains on wide screens and collapses below
`980px`; badges, borders and contrast differentiate the offers without making every card
equally loud. Partner must state its delivery boundary, monthly update allowance and
separately quoted costs next to its benefits. Until real billing is connected, only
Essential may enter the explicit zero-payment simulation; Partner opens the configured
commercial contact because its site work requires a brief and calendar confirmation.

### Missing-Company Registration

A company missing from the active catalogue enters through a legal-identity checkpoint,
not a generic account form. On wide screens, the established claim-flow split places a
large editorial explanation and three numbered, ruled stages beside the dark ink
verification panel. The visible sequence is legal-data submission → e-mail confirmation
→ administrative identity verification → the existing claim and activation flow. The
panel opens with the no-account/no-publication boundary before the first field and closes
with a privacy note after the action.

Below `850px` the regions become one column. At phone width (`560px` and below), the ink
panel moves ahead of the explanation, extends into the narrow page gutter, and preserves
square fields, adjacent errors, the county-owned SIRUTA locality selector, and a full-width
brick action. The e-mail result is a separate ruled reading state that repeats that staff
verification still precedes any account or publication.

**The Legal-Identity-Before-Account Rule.** Registration confirms a mailbox and opens
staff verification; it never visually or verbally collapses legal reconciliation, claim
review, account activation, profile creation, or publication into one success state.

### Locality Search Instrument

On the migrated home, the signature search is one flat numbered sequence beneath the headline: county, locality and service are rows `01–03`; the locality is disabled until the county loads authoritative SIRUTA choices. A full-width coral action closes the sequence. The ONRC caveat remains adjacent and states that registered office does not prove coverage, availability, experience, or quality.

The circular seal rotates slowly over the photographic overlap and the wrench inside the masthead mark makes one restrained breathing motion. Search hover lifts the action by `2px`; all other copy stays still. The separate promotion film keeps user-initiated narration, captions and a visible playback control. With `prefers-reduced-motion: reduce`, seal and logo stop, the film remains on its static cover until explicit playback, and focus indication remains visible.

**The Living-Seal Rule.** Identity motion belongs to the slow seal rotation and subtle logo-tool breath; interaction motion belongs to the action being used. Do not animate explanatory copy, the documentary photographs or a decorative route graph.

### Service Rubrics

Each of seven rubrics combines a serif title, short description and custom consistent-stroke SVG. It is not a card. Hover or keyboard focus changes paper to clean paper and ink to deep brick, expands a short brick rule, and lifts the category illustration by `5px` with a restrained `-1deg` turn. Search arrows move only a few pixels in their direction of travel. These transform cues are brief and interaction-triggered; reduced motion makes them effectively immediate without removing their final state or focus indication.

### Registry and Provider Truth Surfaces

Approved provider supply and ONRC registry supply are intentionally different result types, never two styles for the same truth. The approved provider receives one restrained clean-paper summary with a hairline border and subtle shadow. Search results never expose portfolio imagery: photographs remain in the provider profile, where visitors deliberately ask for more detail. On phone the summary becomes one column. The internal-preview label appears before the provider name only when that preview state is true; it must never be shown as a general approval or trust badge.

The provider name, short summary, and category stay grouped. Service and searched locality form two explicitly labelled, customer-useful fact groups beside a single primary profile CTA with a `44px` minimum height. On phone, the two facts share two columns and the CTA spans the sheet. Claim ownership, preferred-contact workflow and administrative review state do not appear in this customer-facing result.

Ordinary ONRC results remain compact ruled rows with no shadow. Each row labels legal identity, registered-office locality, source date, and evidence type, preserving short scanning paths and pagination density for hundreds of results. They must not inherit the featured sheet's media, shadow, CTA block, or provider-declaration treatment.

The ONRC company detail uses the permanent **Nordic pro** visual direction: pale mineral
ground, pine ink, restrained copper actions, generous white space and one precise
service-specific editorial photograph. The first field places that photograph beside the legal identity,
then groups only the matched service and registered-office locality below it. Rounded
corners are limited to the major reading surfaces and remain modest; typography and strong
geometry carry the masculine character without making the full page dark. A two-column
reading area gives the service match priority and places the small public-data directory
beside it; raw dataset links stay available through an explicit details disclosure.
Claiming the company remains a secondary concluding action. Below `850px` the record
becomes one column in the order identity → category photograph → public facts → services →
data → claim, and below `560px` every region uses the full available width without
horizontal overflow. The photograph is visibly labelled as illustrative, never as a
company-supplied portfolio or evidence of completed work. The design-query selector is
not part of the shipped surface.

Result summaries use grammatically correct singular and plural copy. A provider-only result set is a valid discovery state and must not display an ONRC-empty warning merely because it contains no registry rows. Claim, activation, private editing, moderation, readiness, publication, password, and administrative-preview workflows inherit the palette but retain their authorization boundaries, inert GETs, revision ownership, and fail-closed visibility behavior.

The professional entry provides two equally honest starts: claim a company already in
the directory, or request verification for a missing company. Administrative
reconciliation leads into the existing claim review rather than bypassing it.

**The Workflow-Inherits-Color-Not-Authority Rule.** A shared palette never merges public registry facts, provider declarations, staff decisions, private drafts, credentials, or publication state.

**The Featured-Sheet-Is-Not-A-Ranking Rule.** The single approved-provider fact sheet distinguishes a richer provider-supplied publication snapshot from compact ONRC facts; its prominence never means recommendation, ranking, quality, or guaranteed availability.

### Public Provider Profile

The profile is an ordered project sheet connecting identity, service fit, direct contact
and evidence of work, not a promotional landing page. Its compact first viewport pairs an
identity-scale serif name with the exact service and locality context. It does not expose
claim ownership or administrative workflow state, and it does not use a decorative
route, trust badge or abstract illustration. The title has one brief transform reveal;
reduced-motion preference collapses it to an effectively instant state.

The supporting hero summary contains exactly two customer-useful facts—service and the
visitor's searched locality. The single
contact directory gives phone and public contact e-mail the strongest actions, then groups
professional address and website separately from the exact localities served.
Missing optional values are
named as not published instead of silently disappearing. Phone and e-mail actions expose
their values as text and move only the arrow on hover; website remains a quieter visible
URL. The description and complete declared-service list remain a separate reading column.
Portfolio images are provider uploads included in the approved publication snapshot;
their restrained hover crop may add tactility, but captions and source meaning remain
unchanged.

Legal name, internal-preview state, service area, contact values and portfolio provenance
stay named next to the values they qualify. Public copy may identify information as supplied
by the company, but claim review, ownership approval and administrative workflow state stay
outside the customer-facing profile.

**The Identity-Then-Facts Rule.** Establish the provider together with exact service and
searched locality;
do not spend the first viewport on a decorative diagram.

**The Contact-Is-A-Declaration Rule.** Contact remains explicitly provider-supplied even
when it is visually prominent and part of an approved snapshot.

### Legal Reading Pages and Footer

Privacy and terms are long-form Read surfaces inside the same journal, not generic
policy dumps. A large serif title and one consistent-stroke document or shield mark
open each page. A numbered ruled contents index sits beside a `68ch`–`74ch` reading
column on wide screens and becomes an ordinary one-column index below `850px`.
Sections use whitespace and hairlines rather than cards, banners or dense legal chrome.
Long Romanian and English words must wrap without horizontal overflow at `320px`.

The shared footer closes every public and provider workflow with the wordmark, both
legal routes, and the deployment-owned operator name. It remains a compact three-part
editorial rule on desktop, then stacks into an explicit reading order on phone. Legal
identity and policy text are facts, never badges or marketing claims.

**The Policy-Matches-Product Rule.** Describe only data, cookies and publication
boundaries that the running product actually uses; a shared footer must never invent
an operator identity from source control.

### Public Provider Report Intake

Reporting is a quiet Operate/Read extension of the public profile, not a warning banner,
generic contact form, or public accusation. The profile ends with a ruled editorial
aside and secondary action. The dedicated page names the exact provider version first,
places the privacy boundary before the fields, and separates explanatory copy from the
form with ink and dotted rules rather than a floating card. On wide screens the intro
and workspace use paired reading columns; below `850px` they become one column, the
three-step index wraps without clipping, and below `560px` the primary action spans the
available width.

The form has visible labels, persistent help text and a strong brick focus treatment.
Invalid fields keep help and error copy associated through `aria-describedby`, and the
first invalid visible control receives autofocus after submission. Error red carries
adjacent failure text with sufficient contrast but never replaces words. Completion has
two distinct, calmly worded states—new report recorded and duplicate already recorded—
and both return the visitor to the profile. Neither state suggests that the profile was
removed or that wrongdoing was established.

**The Report-The-Version Rule.** Always identify the exact visible profile before asking
for facts; never present reporting as a judgment about a mutable provider identity.

### Public Provider Report Triage

The staff triage screen stays inside the incumbent Django admin and uses Operate mode:
exact immutable report and snapshot facts come first, while operational state and the
single available action come second. A compact square status band names the case state,
revision, reported snapshot version and current visibility in words. The facts region
shows the report, services, exact coverage and contract digest; the adjacent working
region explains that triage neither withdraws the profile nor changes the snapshot.

Controls are restrained, square and task-sized. The primary action is at least `44px`
high; every input has a visible label, persistent help where needed, adjacent errors and
keyboard focus. A close action exposes the explicit terminal outcome choices. When the
snapshot contract cannot be verified, a worded alert remains visible and the ordinary
action is replaced by blocked-state guidance; historical facts and prior transition
events remain readable. On narrow screens the facts/action grid becomes one column and
definition-list labels stack above their values without horizontal overflow.

**The Facts-Before-Action Rule.** Show exactly what was reported and the immutable
snapshot evidence before asking staff to change operational state.

**The Triage-Is-Not-Withdrawal Rule.** State explicitly that taking or closing a case
does not mutate the report, profile, snapshot or visibility; never imply otherwise
through copy, placement or color.

### Public Report Operational Insights

The dedicated admin perspective is a scan-first Operate surface, separate from both
the report list and individual triage. It opens with the privacy and interpretation
boundary, then exposes square `44px` controls for the fixed 7, 30 and 90-day windows,
the exact half-open interval and calculation time. Current queue state remains visibly
distinct from windowed intake and event history, while a worded integrity warning names
reports without a case and states that the page does not repair them.

Four compact tables form a two-column working grid on wide screens and one column on
narrow screens without horizontal overflow. Each table is programmatically named by
its visible section heading through `aria-labelledby`; counts use tabular numerals and
zero-data rows remain visible so the measurement contract is understandable before the
first report arrives. There are no identity fields, individual records, links into
reports, action controls or decorative charts.

**The Aggregate-Is-Not-A-Case Rule.** Operational totals may support queue planning,
but must never become a drilldown around private report facts or imply a provider-level
judgment.

### Customer Demand Operational Insights

The demand perspective stays inside Django admin as a separate, permission-gated Operate
surface. Its opening pairs one plain-language interpretation boundary with fixed `44px`
controls for 7, 30 and 90-day windows. Four metrics form one flat ruled band rather than a
row of floating cards: customer projects, provider deliveries, provider responses and
awarded projects. On phones the band becomes a compact two-by-two grid without changing
reading order.

Two labelled tables carry the detail: service totals first, then exact county and locality
scope by service. The wide tables scroll inside their own region on narrow screens, use
tabular numerals and preserve explicit column labels. Customer projects and provider
deliveries must remain visually and verbally distinct because one project can be sent to
several providers. The surface exposes no names, contact details, project descriptions,
provider identities, record links, charts or actions, and states that it measures submitted
requests rather than catalogue searches.

**The Project-Is-Not-A-Delivery Rule.** Count demand once per customer project; show
provider deliveries separately so multi-provider dispatch never inflates locality demand.

### Service Category Operations

The category administration surface is an incumbent back-office operation, not a public
marketing page. It uses one ruled accordion register: every closed row exposes category,
current state, order and revision, while expanding exactly one row reveals the bounded
editor. A three-column legend explains consequences before any control; mobile stacks the
legend, keeps the category and current state visible, and reveals reason, confirmation,
order and revision only inside the selected editor. Invalid submissions reopen their row
with adjacent errors instead of expanding the entire register.

**The Policy-Is-Not-Taxonomy Rule.** Operational controls may change discovery, intake,
and order, but their layout and wording must never suggest they edit CAEN facts, existing
provider services, or immutable publication history.

### Verified Customer Reviews

The private customer workspace reveals its review instrument only after an offer was
accepted. Rating choices are fully worded, keyboard-operable controls; the review field
keeps its character guidance and the public-name consent is explicit. After submission,
the form becomes a compact immutable receipt with rating, moderation status and the exact
text. It never invites repeat or edited feedback.

Approved reviews form a ruled evidence section on the public provider profile. The section
states their platform provenance, uses a numeric average and `x/5` scores, and lays review
text in at most two readable columns. It avoids ornamental stars, testimonials styled as
advertising, fabricated avatars and language that implies endorsement. On phones, entries
stack in one column and retain natural text height.

**The Accepted-Work Rule.** A private-link holder may review only after accepting the
provider's quote; provider pipeline status alone never establishes customer eligibility.

**The Review-Is-Evidence Rule.** Show approved customer feedback as attributed evidence,
not as a badge, recommendation, ranking promise or platform verdict.

### Saved Provider Shortlist

The public provider profile exposes an accessible bookmark icon in the hero corner;
search results stay focused on opening the relevant detail page. Its pressed state is
visible through fill as well as the accessible label. The saved-firms page
uses one ruled editorial list: monogram and identity first, short service fit second, then
the two explicit actions to open or remove. It has a complete empty state with a direct
route back to locality search and remains useful without an account or JavaScript.

On phones, navigation retains a compact “Salvate” route beside the brand and language
control. Saved rows stack their actions below the content, keep `44px` targets and never
overflow horizontally. The surface stays flat and Nordic: no portfolio thumbnails,
ranking ornament, gradient, floating-card grid or endorsement language.

Registry bookmarks appear as a quiet, accessible icon in the top-right corner of the
company detail card, not in search results. Saved ONRC rows carry an explicit
public-record label and registered locality, apart from complete profiles, so the
shared list does not imply that a
registry record has provider-supplied contact details or declared service coverage.

**The Saved-Is-Not-Ranked Rule.** A bookmark records only the visitor's temporary choice;
it must not affect search order, analytics, provider trust or publication state.

## Do's and Don'ts

### Do:

- **Do** keep every public, customer, provider and administrative surface in the Ediția locală world: warm paper, editorial ink, coral action, lavender identity and mint grouping.
- **Do** use Nimbus Narrow Local for display hierarchy and Carlito Local for controls, body copy, metadata, and administration.
- **Do** make locality search the first complete instrument and keep county ownership of SIRUTA locality choices visible.
- **Do** keep one brief subtitle below the home headline, let the documentary collage establish personality, and preserve the complete numbered search immediately afterward on phone.
- **Do** keep identity motion limited to the slow seal and subtle logo-tool breath; require explicit action before video narration starts and honor reduced motion.
- **Do** render service categories as seven ruled rubrics, four-plus-three on desktop and two columns on phone.
- **Do** use custom consistent-stroke SVGs for fields and categories, with one visual hand across the set.
- **Do** keep primary actions coral and retain strong focus outlines, labels, touch targets, and reduced motion throughout the product.
- **Do** keep ONRC source dates, registered-office wording, licenses, and caveats adjacent to catalogue results.
- **Do** feature one approved provider as a restrained `16px` clean-paper summary without portfolio imagery, with declared fact groups and one `44px` CTA toward the full profile.
- **Do** keep ordinary ONRC results as compact ruled rows that remain scannable and pageable at hundreds of records.
- **Do** keep the public provider profile's identity, service and searched locality together in the opening sequence.
- **Do** keep phone, e-mail, website, professional address, coverage and portfolio provenance explicitly provider-supplied wherever present.
- **Do** keep result counts grammatical and treat provider-only results as useful supply rather than an empty catalogue.
- **Do** keep missing-company registration form-first on phones and keep the no-account/no-publication boundary adjacent to the form and confirmation result.
- **Do** distinguish provider-supplied facts, review, private draft, internal preview, visibility, withdrawal, and failure in words.
- **Do** preserve existing claim, activation, profile, moderation, publication, password, and administrative authorization boundaries.
- **Do** keep report privacy guidance before the form and expose created, duplicate and
  invalid states with explicit copy, programmatic descriptions and keyboard focus.
- **Do** keep staff report triage in the incumbent admin, show immutable facts before
  state/action, name every state and blocked condition, and preserve a `44px` action.
- **Do** keep report insights identity-free, label every aggregate table, distinguish
  all-time queue state from exact rolling windows, and preserve `44px` filter controls.
- **Do** show only moderated reviews from accepted platform quotes, with minimized names,
  numeric scores and their provenance stated in plain language.
- **Do** keep the RO/EN switch visible, compact, keyboard accessible and at least `44px`,
  preserving the current route and query string in both directions.
- **Do** retain complete text labels for all seven service rubrics in the two-column phone
  index; allow English labels such as “Construction & renovations” to wrap.

### Don't:

- **Don't** add gradients, glass effects, heavy dark panels, decorative blobs, or floating card grids to the Ediția locală interface.
- **Don't** add rounded cards, pill buttons, or unrelated icon styles.
- **Don't** use coral as a broad wash, lavender on unrelated controls, mint as a trust badge, or color as evidence of quality.
- **Don't** replace the ruled locality instrument with a generic hero card or bury it below promotional copy.
- **Don't** replace the photographic trade collage with generic illustrations, restore the rejected route graph, or animate static process text.
- **Don't** turn service rubrics into rounded cards or collapse the phone grid to one column.
- **Don't** imply ONRC registration proves coverage, availability, competence, quality, or recommendation.
- **Don't** show portfolio imagery in search results, repeat the featured-provider shadow or CTA block across ONRC rows, or present the featured sheet as ranking or endorsement.
- **Don't** show the internal-preview badge unless the provider result is actually in internal preview.
- **Don't** expose claim ownership, claim approval or administrative workflow state on the customer-facing provider profile.
- **Don't** present missing-company registration as account creation, self-publication, or a shortcut around legal reconciliation and claim review.
- **Don't** let shared visuals blur mailbox control, legal representation, private editing, administrative approval, or publication.
- **Don't** hide caveats, field errors, disabled dependencies, or fail-closed states for visual neatness.
- **Don't** style a report as a public accusation, imply automatic withdrawal, or ask for
  visitor identity when the intake contract does not need it.
- **Don't** hide the triage integrity failure behind a disabled-looking control, or let
  a triage action appear to edit the report, publication snapshot or profile visibility.
- **Don't** add provider/report drilldowns, mutation controls or identity-bearing detail
  to the operational report perspective.
- **Don't** use review stars as decoration, expose full customer names, or turn reviews
  into an endorsement badge or ranking signal.
- **Don't** use flags, icon-only language controls or a language change that discards
  the visitor's current search state.
