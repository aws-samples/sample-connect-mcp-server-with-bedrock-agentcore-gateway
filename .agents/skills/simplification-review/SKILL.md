---
name: simplification-review
description: Review a change for over-complication, bloat, dead code, needless abstraction, and scope creep — the "couldn't you just do this instead?" pass. Use when user says "simplify this", "is this over-engineered", "review for bloat", "did it change unrelated code", or after an agent generates a large diff. Flags code that is correct but larger/more abstract/broader than it needs to be.
---

# Simplification & Scope Review

AI-generated code is often correct but **bloated**: an inefficient, over-abstracted, 1000-line
construction where 100 lines would do — and it frequently touches code unrelated to the task.
This pass asks two questions the other skills don't: *"Could this be simpler?"* and *"Did it
stay in scope?"*

This is a **quality** pass, not a correctness pass — it assumes the code works and asks
whether it should be this big or this broad. Do not invent bugs here; hand those to
`ai-code-review`.

**Related skills**: `ai-code-review` (correctness/security), `test-quality-review` (tests).

## When to Use
- After an agent produces a large diff for a small-sounding task
- When an abstraction, layer, or config option was added
- Any time the change feels bigger than the problem

## Part 1 — Over-complication & bloat

Scan the diff for these, and for each, propose the simpler form concretely:

- **Premature / needless abstraction**: a base class, factory, generic, or plugin system with
  exactly one implementation. → inline it until a second caller actually exists (YAGNI).
- **Reinventing the stdlib / a dependency**: hand-rolled code for something `itertools`,
  `collections`, `pathlib`, `dataclasses`, or an existing dep already does.
- **Indirection with one caller**: a helper/wrapper/manager that's called once and just
  forwards args. → fold it into the caller.
- **Config/params nobody uses**: flags, options, or branches with a single hardcoded value at
  every call site. → drop the knob.
- **Defensive code for impossible states**: handling for cases the types or invariants already
  rule out. → delete or replace with an assertion.
- **Copy-paste divergence**: near-duplicate blocks that could be one parameterized function
  (only when there are genuinely ≥2 real uses — not speculative).

The decisive move: state the simpler version. "This 40-line `EventDispatcher` class has one
subscriber — a plain function call does the same thing in 3 lines."

## Part 2 — Dead code & leftovers

- Code the change adds but never calls; imports/vars/params now unused after the edit.
- Old code paths the change superseded but left behind ("just in case").
- Commented-out code shipped in the diff.
- TODO/FIXME with no owner or ticket that the change introduces.

## Part 3 — Scope creep (stay in the task's lane)

Flag edits that aren't required by the stated task:
- Files or functions changed that the task didn't ask for.
- **Comments or docstrings removed/rewritten** that are orthogonal to the change — a very
  common AI side effect: it deletes or "cleans up" context it doesn't understand.
- Reformatting / import re-sorting / renaming mixed into a logic change (churns the diff,
  hides the real change, risks regressions).
- Behavior changes not covered by the task's requirement or an Acceptance Criterion.

Rule of thumb: if reverting a hunk would NOT affect the task's stated goal, it's scope creep —
call it out and recommend splitting it into its own change.

## Report Format
```
**[SIMPLIFICATION | SCOPE]** file:line — what's heavier/broader than needed
- Now: <what the code does / how big>
- Simpler: <the concrete smaller form, with rough line delta>
- Risk of leaving it: <maintenance cost, hidden diff, future bug surface>
```
Severity is usually LOW/MEDIUM (this is quality, not correctness) — UNLESS the bloat hides a
real bug or the scope creep changes behavior, in which case hand it to `ai-code-review`.

## Guardrails (don't over-correct)
- Don't flag abstraction that has ≥2 real current callers — that's justified.
- Don't demand clever one-liners; "simpler" means fewer moving parts, not denser code.
- Don't propose a rewrite you can't show is behavior-preserving. Simplification must not
  change what the code does — only how much of it there is.

## Troubleshooting

### Everything looks "simplifiable" — where to stop
**Fix**: only flag when you can name the concrete simpler form AND it removes a real moving
part (a class, a layer, a knob, a branch). "Could be nicer" without a concrete smaller version
is noise — drop it.

### Is a removed comment scope creep or a fix?
**Fix**: if the comment described still-present behavior and the task didn't touch that code,
its removal is scope creep — flag it. If the comment was describing code this change deleted,
removing it is correct.
