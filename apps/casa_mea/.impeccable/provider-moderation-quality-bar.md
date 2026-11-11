# Provider service-area moderation quality bar

## Direction

Extend the existing ServiciiAproape provider dashboard without changing its visual
identity: warm paper, deep blue-green work surface, amber actions, squared controls,
and direct Romanian copy. Moderation must feel consequential but not imply public
verification.

## Required states

- Draft revision: explicit action to submit the exact revision for internal review.
- Pending: calm informational state; editing remains possible and explains
  supersession.
- Approved: explicitly says internal and still unpublished.
- Changes required: distinct warning state showing only provider-safe feedback.

## Non-negotiable trust rules

- Submission and approval never claim publication, availability, quality, or verified
  service coverage.
- Internal moderator notes never render in provider or public templates.
- ONRC authorization remains described as a legal ceiling, not proof of service.
- The public registry reader remains unchanged.

## Responsive and accessibility checks

- No horizontal overflow at 391 px effective viewport width.
- Review state remains readable after the long service-area form.
- Buttons retain a minimum 48 px target and stack to full width on narrow screens.
- State copy is present in text, not conveyed by color alone.
- Forms remain server-rendered, CSRF-protected, and usable without JavaScript.

## Verified evidence

- Desktop draft state: `.impeccable/review/provider-moderation-draft-desktop.jpg`.
- Mobile changes-required state:
  `.impeccable/review/provider-moderation-changes-mobile.jpg`.
- Browser assertions: `scrollWidth == clientWidth`; provider feedback present;
  internal note absent.
