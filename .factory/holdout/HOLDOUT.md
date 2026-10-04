# Holdout scenarios

Independent composed scenarios for Jev Triage for Orca. Each starts from a freshly
started app with an empty database and no `OPENROUTER_API_KEY`. This file is readable
by the builder; the scenarios that are actually hidden live outside the checkout and
are given only to the verification environment.

## Hostile route text never becomes markup, anywhere it travels

1. Add a route named `<script>alert(1)</script>` with criteria `"><img src=x onerror=alert(2)>`,
   target model `m/one` and price `100`.
2. Add a second route `strong` with criteria `hard debugging`, target model `m/two`
   and price `900`.
3. Paste the task `<b>fix</b> the login bug` into the tester and submit.
4. On the routes page, the decision page, the decision log and the Claude Code
   integration page, the route name and criteria and the task appear as visible text.
   No page contains an unescaped `<script>`, `<img` or `<b>` taken from those values.
5. The decision still lists a probability for both routes and they add up to 1.

## Three routes, a tie on price, and labels that disagree with the decider

1. Add routes `small` (price `100`), `mid` (price `900`) and `big` (price `900`).
2. Submit four different tasks, including one that is a single word and one that is
   several paragraphs long.
3. Every decision shows three probabilities adding up to 1, and any decision where
   escalation fired chose one of the two routes priced `900`, the same one every time.
4. Mark two decisions right and two wrong, choosing `mid` as the correct route for
   both wrong ones.
5. The summary shows 4 labelled decisions and 50% overall accuracy, and the per-band
   counts add up to 4.
6. Change one label from wrong to right. The summary now shows 75%, still with 4
   labelled decisions.
7. Submit a label for decision id `abc` and for an id that does not exist. Neither
   returns a server error, and the summary is unchanged.
