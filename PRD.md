# PRD: Jev Triage for Orca

## Problem
Coding agents send every request to one model: the expensive one wastes money on easy tasks, the
cheap one fails the hard ones. Jev (TypeSafe's System One decision model, `typesafe/jev-1.13` on
OpenRouter) can make the call in about half a second for a fraction of a cent: one `choice`
question with each route as an option returns a pick, a probability per route and a confidence.
What is missing is a place to define the routes, see how good Jev's calls are, and wire the result
into the tools I actually use: Claude Code, Codex and Hermes.

## Who it is for
One developer who uses several coding agents and wants model triage they built and understand.
No accounts.

## What it does (MVP)
1. **Routes and the route tester.** Define routes: a name, a one-line criteria text (what kind of
   task belongs here; this wording is the routing policy), a target model and a price per million
   tokens in cents. Paste a coding task and get a decision: the chosen route, the probability for
   every route, the confidence, and whether the escalation rule fired. Escalation rule: if
   confidence is below 0.5 **and** the most expensive route holds at least 0.2 of the probability,
   the task goes to the most expensive route instead. Both thresholds are editable. Every decision
   is saved.
   The decision comes from a `Decider` interface with two implementations: `JevDecider` calls
   OpenRouter's decisions endpoint with the standard library (`POST
   https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`, one `choice` question whose
   options are the routes and their criteria) and is used only when `OPENROUTER_API_KEY` is set;
   `OfflineDecider` is a deterministic keyword-and-length heuristic that returns the same shape. The
   page shows which decider answered. Tests use the offline one.
2. **Decision log and labelling.** A log of every decision, newest first: task, route, confidence,
   decider, time. Mark each one right or wrong (and pick the route it should have been). A summary
   shows accuracy overall and per confidence band (below 0.5, 0.5 to 0.8, above 0.8), so the
   thresholds get tuned on your own data.
3. **Integration snippets.** One page per tool that generates copy-paste setup for the current routes,
   each snippet labelled where it works (CLI, Desktop, or "not verified on Desktop"):
   - **Claude Code:** a `settings.json` env block pointing `ANTHROPIC_BASE_URL` at a local route
     proxy (CLI), and an optional `UserPromptSubmit` hook that prints Jev's advice into the
     conversation. Note: hooks cannot switch the model; routing needs the proxy.
   - **Codex:** a `config.toml` `[model_providers.jevroute]` block for the proxy, plus a hook.
   - **Hermes:** a `config.yaml` custom provider for the proxy, plus a shell hook.
   - The proxy itself: a single standard-library `route_proxy.py` file generated from the current
     routes, which asks Jev for each request and forwards it to the chosen route's model.
   The page renders the snippets as text; it does not install anything.

## Out of scope for the MVP
Running the proxy from the app, live editor or desktop-app plugins, calling Jev in tests, streaming,
accounts or logins, cost dashboards with real spend, more than one policy at a time.

## Constraints
Standard library Python + SQLite only (see AGENTS.md). Server-rendered pages. Prices in integer
cents. Probabilities stored as integers in thousandths. No test may call the network: the
`JevDecider` is never used unless `OPENROUTER_API_KEY` is set.

## Background (sources)
OpenRouter Jev tutorial: https://openrouter.ai/docs/guides/community/jev-tutorial · Claude Code hooks:
https://code.claude.com/docs/en/hooks · Codex config and hooks: https://learn.chatgpt.com/docs/config-file/config-advanced ·
Hermes hooks: https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks · Similar tools:
claude-code-router, RouteLLM, OpenRouter Auto Router, NotDiamond.
