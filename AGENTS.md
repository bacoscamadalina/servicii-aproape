# Guidance for Project Agents

This repository is the DropTheWork monorepo created from the legacy DropTheWork projects. It may contain one or more apps, packages, services, tools, or modules. Work on the area the user specifies. If the user does not specify an area, inspect the project plan, open files, recent instructions, and repository structure before choosing a scope.

## Monorepo repository structure

Keep the repository root small. Root files are for repository discovery and agent bootstrapping only.

- `README.md`: short human-facing overview and starting instructions.
- `MIGRATION.md`: notes about how the monorepo relates to the legacy project checkout.
- `AGENTS.md`: root agent instructions.
- `CLAUDE.MD`: root Claude-specific bootstrap instructions, if Claude is used.
- `LEARNINGS.md`: durable engineering lessons that should survive refactors.
- `ai/`: monorepo-level product direction, design direction, workflow, project planning,
  architecture, specs, and milestone plans.
- `apps/`: application source code. The imported apps, packages, services, tests, build files, and runtime configs live here.

Do not place application source files in the repository root. If a tool or framework expects a root-level config, prefer creating it inside the relevant `apps/` project and running the tool from that directory. Only add root-level app configs when the chosen toolchain cannot work cleanly otherwise, and document the reason in `ai/ARCHITECTURE.md`.

## Required project context

AGENTS.md — this current file is always inserted into the start of every agent conversation, and explains (1) how the user wants the AI to behave, and (2) development instructions for this repo. If an app has its own `AGENTS.md`, read this root file first, then the app-local file before changing that app.

LEARNINGS.md — you MUST ALWAYS read this file. It contains hard-won engineering lessons learned through costly trial and error. Read it before doing work so you do not repeat past mistakes.

Architecture documents — read the relevant architecture notes for the app, package, service, or module you are changing. Monorepo-level notes live under `ai/`; app-specific notes may live under each app's `docs/` directory or app-local `AGENTS.md`. They may be named `ARCHITECTURE.md` or `architecture.md`, and may be linked from `LEARNINGS.md`. You are expected to study the architecture before doing work, so your changes fit existing codebase patterns, dataflow, and invariants.

Workflow and plan documents — read `ai/README.md`, `ai/WORKFLOW.md`, and the relevant `ai/PLAN*.md` files before planning or executing milestone work. These capture the current documentation map, validation expectations, prior planning decisions, deferred engineering work, and scope boundaries.

Product and design/spec documents — read relevant product, design, API, schema,
or UX documents, including `ai/DESIGN.md`, app-local `PRODUCT.md`, and app
documentation before changing behavior.

## Cross-cutting engineering expectations

Everything should typecheck clean.

Preserve project architecture invariants. If a module has explicit invariants around state ownership, data flow, caching, persistence, API boundaries, rendering, synchronization, or error handling, treat those invariants as binding unless the user explicitly asks to redesign them.

Design for the actual scale described by the project. If the repository handles large files, deep trees, large datasets, many records, high-frequency events, slow devices, unreliable networks, or long-running jobs, implementation and validation must cover those conditions without blocking the main execution path.

Network and external-service calls must go through the project’s approved wrappers and error-handling paths. Respect existing conventions for authentication, retries, rate limits, timeouts, cancellation, logging, telemetry, and user-visible failures.

Assume partial failure is normal. External services, local storage, caches, browsers, file systems, background jobs, and network connectivity can fail or be unavailable. Handle failure explicitly and preserve a usable state wherever the architecture requires it.

## Codebase style and guidelines

Coding style: All code must also be clean, documented and minimal. That means:
- Keep It Simple Stupid (KISS) by reducing the "Concept Count". That means, strive for fewer
  functions or methods, fewer helpers. If a helper is only called by a single callsite,
  then prefer to inline it into the caller.
- At the same time, Don't Repeat Yourself (DRY)
- There is a tension between KISS and DRY. If you find yourself in a situation where
  you're forced to make a helper method just to avoid repeating yourself, the best
  solution is to look for a way to avoid even having to do the complicated work at all.
- If some code looks heavyweight, perhaps with lots of conditionals, then think harder for a more elegant way of achieving it.
- Prefer functional-style code, where variables are immutable "const" and there's less branching. Prefer to use ternary expressions "b ? x : y" rather than separate lines and assignments, if doing so allows for immutable variables.
- Code should have comments, and functions should have docstrings. The best comments are ones that introduce invariants, or prove that invariants are being upheld, or indicate which invariants the code relies upon.
- **Name side-effecting functions to expose the side effect.** A function named `load()` implies it returns data. If its real purpose is to populate module-scoped state and fire a callback, that must scream from the name — e.g. `loadIntoStateAndNotify()`. Every side effect is dangerous and unclean; the function name is the best place to call it out. Pure functions (input→output, no mutation) can have simple names; impure functions must wear their impurity on their sleeve.
- **Never use `void asyncFn()` for fire-and-forget.** Discarding a promise with `void` silently swallows exceptions or causes unhandled rejections. The caller should always `await` the async function. If fire-and-forget is truly needed (rare), the function itself must handle all errors internally and return `void` (not `Promise`), with a name that makes the contract explicit (e.g. `saveFireAndForget()`). Prefer `await` — it keeps error propagation explicit and lets the caller decide how to handle failure.

I am adamant about clean engineering. What I look for:
- Learnings must be stored in `LEARNINGS.md`, or in other files linked from it.
- Invariants are the best way to document all aspects of code. These include code invariants (stating what assumptions a function makes about shared data, and how it upholds them), and architecture invariants (for instance the main index.js never touches state except through component accessors).
- **Address prerequisites cleanly, don't hack around them.** When working toward a goal, you will often discover that a prerequisite needs fixing first. Do the clean-engineering right thing for the prerequisite, even if this leads down a long detour of better-engineering and refactoring. Never just hack around it to reach the goal faster. The user is positively DELIGHTED when we discover new reasons, justifications, opportunities for refactoring and improved clean engineering. If you find yourself in a situation "I have been asked to do X, but I need to do Y first, and that in turn needs Z", then it's positively desirable to set X aside while we start on an entirely new plan for Z.

## Agent peer review

Agents can and should get opinions from other agents:
- Claude is invoked directly as an interactive CLI session after writing the
  review request to a `/tmp` prompt file. Always start Claude with skip
  permissions so it does not block on permission prompts:
  `META_DISABLE_SHAMAN=1 CLAUDE_CODE_VERSION_OVERRIDE=latest claude --dangerously-skip-permissions`.
  Then send Claude a prompt such as
  "Please read /tmp/instr.md and write your response in markdown to
  /tmp/result.md". Do not route Claude review through the human unless direct
  CLI execution is unavailable, and do not use `claude -p` unless the user
  explicitly asks for non-interactive print mode.
  When driving interactive Claude from a PTY, after writing the prompt send an
  explicit carriage return and verify Claude entered the working/spinning state
  or wrote the expected result file; a single write may only place text in the
  prompt box.
- Codex can be invoked `codex exec "prompt goes here"`
- A great prompt is "Please read instructions in /tmp/instr.txt and write your answers in markdown to /tmp/result.md"
- Use other agents for review when you're coming up with a plan, or there is a weighty decision to be made.
- The other agent is aware of AGENTS.md and can and will read files. It normally takes a long time to give a thoughtful response; expect up to 10-15mins without any sign of output before it finishes.

## Agent interaction rules with human

- IMPORTANT. Only do git work in two cases
  - if the user explicitly asks for a code review, then you may use git ONLY ONCE to learn the previous state
    of files
  - if the user asks you to push to github, then you may use git to do this
  - If ever you find yourself invoking git in any other circumstance, you MUST STOP


### Close the loop, autonomy

The agent is responsible for fully validating every change, end-to-end, autonomously. The human should not have to prompt for testing, deployment, or production verification — the agent must pursue these proactively.

- **Test before presenting to the human**: if you've made changes, they must be built, tested via Playwright, and verified (including screenshots) before telling the human it's done or asking them to look at it. You don't need to test after every individual edit — but you must test before handing off.
- **Test all UI interactions**: don't just test the happy path. Click every button, test sign-out, test error states, test on mobile viewports. If the UI has a button, verify it works.
- **Proactively gather metrics**: timing data, track counts, cache sizes. Record them without being asked. These help the human evaluate whether the implementation meets performance goals.
- **Don't wait unnecessarily**: if a background process might already be done, check before sleeping. Poll actively rather than using fixed delays.
- When the agent needs human help (OAuth sign-in, other things the agent literally cannot do), treat the human as a tool: Give the exact command to run, fully spelled out, copy-pasteable; explain what the human should see and when they're done; Once the human has completed their step, the agent resumes and handles everything else — no further prompting needed. (This is different from final milestone validation, where the agent presents a walkthrough of what was built and the human evaluates the result.)
- Solve your own obstacles. If testing requires setup (e.g. a Chromium profile for production, a running server), figure out how to set it up. Try the obvious approach first. Only ask the human if you've confirmed the obstacle truly requires human intervention. (Exception: the sandbox notes that you should use sandbox-escape only for a small allowlist of items. Do not try to be creative by using it outside that narrow remit.)
