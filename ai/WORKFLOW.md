# Workflow

Work in small, independently verifiable milestones. Each milestone must typecheck or pass Django checks, include tests for its behavior, and be verified in desktop and mobile browser sizes before handoff.

The first milestone proves the core job: a visitor selects a Romanian locality and county, chooses an optional home-service category, and sees relevant professionals. Durable data, authentication, onboarding, and commercial features are deliberately deferred.

## Branch strategy

- `main` is the stable, releasable history. Changes reach it through reviewed merges.
- `develop` integrates completed work before a release is promoted to `main`.
- `codex/data-pipeline` owns ONRC, MF, SIRUTA, CAEN, reconciliation, and evidence imports.
- `codex/marketplace-profiles` owns claimed provider profiles, contacts, and declared coverage.
- `codex/frontend` owns search UX, templates, styling, accessibility, and responsive behavior.
- `codex/ops-publication` owns approvals, publication gates, deployment, and operational tooling.

Topic branches start from `develop`, remain small and verifiable, and merge back into
`develop`. Release-ready integration is merged from `develop` into `main`; urgent
production fixes use a short `codex/hotfix-*` branch from `main` and are merged into
both long-lived branches.

## Continuous integration gate

Every push to `main`, `develop`, or a `codex/**` branch and every pull request targeting
`main` or `develop` runs `.github/workflows/ci.yml`. The required jobs are
`Django + PostgreSQL`, `Docker contracts`, and `Browser E2E`. They cover Django checks, missing
migrations, the complete Python and JavaScript suites, both Compose entry points, the
production image, the packaged read-only preview in Romanian and English, and the
persistent development-cloud bootstrap with console e-mail and all 72,881 seed identities.
The gate also rejects inconsistent installed packages, failing production deployment
checks, a root-running production image, or a packaged preview that accepts POST.

The workflow has read-only repository permissions and uses only disposable synthetic
configuration plus temporary PostgreSQL volumes. It never receives, restores, or
publishes the private database. The Docker contract verifies the full routes and admin
bootstrap, exact identity count and restart persistence, then removes only its disposable
CI volumes. Configure branch protection in GitHub to require all jobs before merging;
repository settings remain an external operator action.

## Dependency update workflow

`.github/dependabot.yml` checks Python, Docker and GitHub Actions dependencies every
Monday, with staggered runs in the `Europe/Bucharest` timezone. Version-update pull
requests target `develop`, never `main`, and pass through the same CI and review path as
human changes. Minor and patch releases are grouped per ecosystem; major releases stay
isolated so their migration and compatibility risks remain explicit. A bounded pull
request limit and release cooldown prevent update storms. Nothing is merged or deployed
automatically.

`Browser E2E` runs the packaged preview in Chromium using Python Playwright. It covers
the dependent county/locality selector, the desktop alignment regression, a filtered
Iași search, company-detail return, Cluj pagination, query-preserving RO/EN switching
and page-level overflow at desktop and mobile sizes. A failure uploads only its local
screenshot and trace for 14 days; successful runs retain no browser artifact.

GitHub repository settings remain authoritative for Dependabot alerts and security
updates. Those controls must be enabled by an owner; this file configures version-update
pull requests but does not claim that repository-level security features are active.
