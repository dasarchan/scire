# Learner evidence

`~/.scire/repos/<id>/events.jsonl` is the source of truth for assessments. Each event has a stable question key, concept, selected answer, correct/incorrect flag, conditional response distributions, misconception, source fingerprint and timestamp. Repeated submissions with the same key are idempotent. `learner.json` is a compatibility cache: deleting it or editing an assessed concept does not change replayed mastery. Historical assessment events are replayed with their original likelihood assumptions; older evidence that predates assessment events is imported once.

For a concept with prior mastery p and response r:

```text
posterior = p * P(r | known) / (p * P(r | known) + (1-p) * P(r | unknown))
mastery after feedback = posterior + (1-posterior) * 0.12
```

Every choice, including “I don’t know”, has a likelihood under each hypothesis. Both response distributions must sum to one. The correct response must be most likely for a knowledgeable learner. Defaults are conservative; agents may provide question-specific distributions. These are heuristic diagnostic assumptions and have not been fitted to observed learner populations. A setup calibration quiz supplies answer evidence, not a statistical calibration of these probabilities.

Between observations, mastery moves toward the 0.20 prior with a 45-day half-life. A changed anchored code fingerprint discounts the distance above/below the prior by 0.55 before the next observation. This discount is applied once per observed revision transition, not repeatedly during page views. Feedback observations record the new fingerprint.

Areas aggregate descendant concept probabilities using concept importance as weights, including uncertain priors for untested concepts. Coverage is reported separately as assessed/total concepts so an estimate is not confused with demonstrated knowledge. The prompt summary includes area rollups, up to six weak or uncertain concepts, three strengths and six tentative misconceptions. Full event histories stay out of prompts.

Reading budgets bound the whole round: prose, question stems, choices, explanations and proposed findings. Question decisions add an estimated 20 seconds each. Oversized sections are rejected before streaming publication so an agent can shorten them during a fix pass. Budget estimates are approximate; they are not timed quiz limits.
