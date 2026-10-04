# Mission

**Derived from:** `PRD.md`
**Last reconciled with it:** 2026-10-04

## What Jev Triage for Orca is

Jev Triage for Orca is a small web app where one developer defines model routes for
their coding agents, pastes a coding task, and sees which route a fast decision model
(Jev, `typesafe/jev-1.13` on OpenRouter) would send it to: the chosen route, the
probability for every route, the confidence, and whether the escalation rule fired.
Every decision is saved, can be labelled right or wrong, and feeds an accuracy summary
so the thresholds are tuned on the developer's own data. The app also generates
copy-paste setup text for Claude Code, Codex and Hermes from the current routes.

It is built for one person on one machine: no accounts, one routing policy at a time,
one SQLite database, server-rendered pages on the Python standard library.

## Who it is for

- One developer who uses several coding agents and wants model triage they built and
  understand, with evidence of how good the routing calls are.

Jev Triage for Orca is not a model gateway or a proxy service. It decides and
explains a route; it never carries the traffic.

## Core capabilities (in scope)

The factory may accept issues in these areas.

**Routes and the route tester**
- Create, edit and delete routes: name, one-line criteria text, target model, price
  per million tokens in integer cents.
- Paste a task and get a decision: chosen route, probability per route, confidence,
  whether escalation fired, and which decider answered.
- The escalation rule (confidence below a threshold and the most expensive route
  holding at least a threshold share of probability) with both thresholds editable.
- A `Decider` interface with `JevDecider` (OpenRouter, only when `OPENROUTER_API_KEY`
  is set) and `OfflineDecider` (deterministic keyword-and-length heuristic).

**Decision log and labelling**
- A log of every decision, newest first: task, route, confidence, decider, time.
- Marking a decision right or wrong, and picking the route it should have been.
- An accuracy summary overall and per confidence band (below 0.5, 0.5 to 0.8, above 0.8).

**Integration snippets**
- One page per tool (Claude Code, Codex, Hermes) rendering setup text for the current
  routes, each snippet labelled where it works (CLI, Desktop, or "not verified on Desktop").
- A generated single-file standard-library `route_proxy.py`, shown as text.

## Out of scope -- the factory must never build this

**Carrying traffic or touching the user's machine**
- Running, hosting or supervising the route proxy from the app. The app only renders
  `route_proxy.py` as text.
- Installing anything, or writing into Claude Code, Codex or Hermes configuration
  files. Snippets are text the developer copies.
- Streaming responses, or executing the coding task itself. The app picks a route; it
  does not do the work.
- Editor plugins or desktop-app plugins.

**Becoming a multi-user or commercial product**
- Accounts, logins, teams or any multi-user feature.
- Dashboards of real spend, or reading usage or billing from any provider.
- More than one routing policy active at a time, or A/B testing between policies.

**Breaking the stack or the secret boundary**
- Third-party Python packages, or a frontend framework or build step. Standard
  library, SQLite and server-rendered pages only.
- Storing `OPENROUTER_API_KEY` in the database, showing it on any page or in any
  generated snippet, or calling the network from a test.

## Hard invariants -- not tunable by any issue

These are not features. They are properties that define what Jev Triage for Orca is.
The factory cannot modify them even if an issue asks nicely, gives a good reason, or
calls it a bug. Changing one requires a human commit.

1. **Standard library and SQLite only.** The factory's verification copies the app and
   runs it with a plain interpreter, so any dependency makes every check unrunnable.
2. **No test calls the network.** `JevDecider` is used only when `OPENROUTER_API_KEY`
   is set; tests always use `OfflineDecider`.
3. **Both deciders return the same shape.** A pick, a probability per route and a
   confidence, so every page and the log work identically whichever one answered.
4. **Money and probability are integers.** Prices are integer cents per million tokens;
   probabilities and confidence are stored as integers in thousandths.
5. **Every decision is saved.** A decision shown to the user that is missing from the
   log is a bug, never an optimisation.
6. **`/health` and `/build-id` keep working.** The factory verifies against them.
7. **The factory cannot modify governance files.** `MISSION.md`, `FACTORY_RULES.md`
   and `AGENTS.md` are the constitution. A PR touching any of them is an automatic reject.
8. **The factory cannot modify its own judge.** `harness/`, `.factory/locks/` and
   `.factory/holdout/` define what "working" means here. Adding an assertion is
   always welcome; removing or loosening one is a human decision, always.

## Allowed evolutions

Explicitly in scope, so the factory does not reject them as architectural drift:

- New feature modules under `app/features/` with their own named migrations and tests.
- Improving the `OfflineDecider` heuristic, as long as it stays deterministic.
- Clearer wording, layout and error messages on existing pages.
- More tests, at any time.

## Definition of done

Every change the factory ships clears all three gates.

**Gate 1 -- static checks and tests pass.** `python3 -m compileall -q app tests` and
`python3 -m unittest discover -s tests`.

**Gate 2 -- usable without documentation.** Any new page is reachable from the
navigation, every form says what it wants, and every validation error is shown next to
the form with a 400 status, never a 500.

**Gate 3 -- the end-to-end path passes as a real user.**

1. Start the app with an empty database: `python3 -m app.server --port 8080`.
2. Create at least two routes with different prices.
3. Paste a coding task into the route tester.
4. The page shows the chosen route, a probability for every route, the confidence and
   the decider that answered, and the same decision is at the top of the log.

This runs on every change that touches runnable code, including ones that "seem
unrelated". It is not optional. The full journeys are in `harness/END-TO-END.md`.

## Open questions -- decisions nobody has made yet

These are undecided, not forbidden. **The factory may propose an answer to any of
them**, build against it, and record what it assumed in the pull request.

- **Q1** Which keywords and length cut-offs the `OfflineDecider` uses to tell an easy
  task from a hard one.
- **Q2** What the tester shows when fewer than two routes exist.
- **Q3** Whether deleting a route keeps or hides the past decisions that chose it.

**Except this, which does stop the factory** -- it is on the irreversible list
(`FACTORY_RULES.md` §7.3) rather than open in the ordinary sense:

- Any migration that drops or rewrites stored decisions or labels.

Once answered, an entry moves to `.factory/decisions.md` with its answer and date,
and stops being asked. **A decision is asked once.**

## What the factory does NOT own -- permanently human

- Whether the routing policy is *good*: the criteria wording and the thresholds are
  the developer's judgement, tuned on their own labelled data.
- Whether the pages look right and read clearly at a glance.
- Whether the generated snippets actually work inside Claude Code, Codex and Hermes
  on a real machine. The factory checks the text, not the tools.

The factory owns the route data model, the decision and escalation logic, the log,
the accuracy arithmetic and the snippet text: the layer whose correctness can be
asserted.
