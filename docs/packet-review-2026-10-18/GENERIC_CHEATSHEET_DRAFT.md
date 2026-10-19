# Generic proof-search cheatsheet

Draft for v8 review. This is proposed shared guidance, not an installed prompt. Validity rules, scoring, tool schemas, and spend/lifetime policy belong in the separate task contract.

- Look for a better proof shape before polishing syntax. A theorem about the whole structure can replace induction, repeated cases, or a manual construction. Search by the obligation and the project's abstractions, not only names used in the reference.
- Check whether symmetry, an equivalence, a converse, or a characterization removes a duplicated direction. A useful theorem may be absent from the original proof's dependencies.
- Prefer the project's native API when it avoids representation conversions and transport scaffolding. Inspect signatures when uncertain; batch related lookups and reuse evidence already available.
- Give parallel searches distinct, testable hypotheses. Separate structural routes, lemma families, and focused cost experiments. Rephrasing the same search does not create an independent idea.
- Inspect the actual goal and its case-local hypotheses before replacing a step. The same variable name can mean different things in different branches. A printed goal alone is not a reusable Lean environment.
- Use the smallest isolated experiment that answers the question. Distinguish a useful signature, a locally closing example, a full candidate, and all-pin/cold verification. Carry helper dependencies explicitly.
- After a structural gain, inspect the improved candidate's costs. Reference hotspots can become irrelevant. Compare token and heartbeat changes using the published scoring rates; shorter text can score worse.
- Try broad automation, direct terms, constructors, inferred arguments, and smaller intermediate identities where they fit. Measure the complete candidate. No tactic or proof spelling is always cheapest.
- For local tuning, change a small related set of things so outcomes remain interpretable. A structural hypothesis may require a larger rewrite. Avoid repeating failed experiments unless the assumptions or question changed.
- Preserve useful discoveries as compact evidence records. Link the hypothesis, exact proof/step, experiment, outcome, and remaining uncertainty. Add prose only for new intent or findings absent from structured records. Publish useful candidates before the whole search assignment finishes.
