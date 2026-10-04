# Runtime scenarios

The journeys a real user takes through Jev Triage for Orca. Each starts from a freshly
started app with an empty database and no `OPENROUTER_API_KEY`, so the offline decider
answers. Shared runtime verification owns execution and evidence.

## A developer defines routes and tests a task

1. Open the routes page and add a route `cheap` with criteria `small edits, renames,
   typos`, target model `anthropic/claude-haiku-4.5` and price `100` cents.
2. Add a second route `strong` with criteria `architecture, multi-file refactors,
   hard debugging`, target model `anthropic/claude-opus-4.5` and price `1500` cents.
3. Both routes are listed with their criteria, model and price.
4. Open the route tester, paste `fix the typo in the README title` and submit.
5. The decision page names one chosen route, shows a probability for `cheap` and for
   `strong` that add up to 1, shows a confidence between 0 and 1, says whether
   escalation fired, and says the `offline` decider answered.

**What would make this fail:** a route is missing from the probabilities, the
probabilities do not add up to 1, the page does not say which decider answered, or a
route with an empty name or a non-numeric price is accepted instead of re-rendering
the form with an error.

## An unsure decision escalates, and the thresholds change that

1. With the `cheap` and `strong` routes defined, paste a task that mixes both kinds of
   work, such as `rename a variable and also redesign the storage architecture`.
2. The decision shows a confidence below 0.5, at least 0.2 probability on `strong`,
   escalation fired, and the chosen route is `strong`.
3. Open the thresholds form, set the confidence threshold to `0` and save.
4. Submit the same task again. Escalation did not fire this time.

**What would make this fail:** escalation fires when either condition is not met,
the escalated task goes anywhere other than the most expensive route, or saved
thresholds are ignored by the next decision.

## Decisions are logged, labelled and scored

1. With two routes defined, submit three different tasks through the tester.
2. Open the decision log. All three are listed newest first, each with its task,
   route, confidence, decider and time.
3. Mark the newest one right. Mark the oldest one wrong and pick the route it should
   have been.
4. The summary shows 2 labelled decisions and an overall accuracy of 50%, and each
   labelled decision is counted in exactly one confidence band (below 0.5, 0.5 to
   0.8, above 0.8).

**What would make this fail:** a decision made in the tester is missing from the
log, the order is oldest first, unlabelled decisions count towards accuracy, or
labelling one decision changes another.

## Integration snippets follow the current routes

1. With routes `cheap` and `strong` defined, open the Claude Code integration page.
2. It shows a `settings.json` env block that sets `ANTHROPIC_BASE_URL` to a local
   proxy address, labelled as working on the CLI, and a `UserPromptSubmit` hook
   snippet with the note that hooks cannot switch the model.
3. The generated `route_proxy.py` text contains both target models,
   `anthropic/claude-haiku-4.5` and `anthropic/claude-opus-4.5`.
4. Open the Codex page: it shows a `[model_providers.jevroute]` block. Open the
   Hermes page: it shows a `config.yaml` custom provider.
5. Change the `cheap` route's target model, reload the Claude Code page, and the
   proxy text now contains the new model and no longer the old one.

**What would make this fail:** snippets are hard-coded instead of generated from the
routes, a snippet has no label saying where it works, or the page tries to install or
run anything.
