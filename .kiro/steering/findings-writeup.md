---
inclusion: always
---
# Findings Write-up & Learning Loop

How to record a confirmed defect, and how to feed the lesson back into the review rules so
the same class is caught automatically next time. This closes the loop that
`.agents/skills/ai-code-review` opens: find → verify → **record → generalize**.

This is deliberately lightweight — it is NOT an RCA/COE/postmortem process. Use it for a
review finding or a caught bug, not for customer-facing incident write-ups.

## When to write one up
- A finding confirmed at **HIGH or CRITICAL** (see review-policy.md severity)
- Any defect that a reviewer/agent could plausibly hit again → worth a reusable pattern
- Skip for LOW/style: just fix it in place, no write-up

## Write-up format (a compact defect-ticket template)
Keep it to what a reader needs to act. One finding = one block:

```markdown
### <one-line, user-visible problem>
- **Severity:** CRITICAL | HIGH   (state the trigger condition + impact path)
- **Root cause:** <file:line> — what the code does vs. what it should do
- **Trigger:** <the concrete input/state that makes it fail>
- **Impact:** <what goes wrong, for whom, under what conditions>
- **Fix:** <the change; if there are options, name the recommended one and why>
- **Test added:** <the test that now fails if this regresses — name it after the outcome>
- **Related:** <commit / PR / AC id / bug-pattern id>
```

Rules:
- Root cause must cite `file:line` and contrast actual vs. required behavior — not "it was
  buggy".
- Every write-up names the **test that now guards it** (behavior/property/canary as
  appropriate — see the adversarial-testing skill). No test → the fix isn't done.
- State the trigger concretely enough that someone could reproduce it.

## The learning loop (the part that matters)
A write-up is only half the value. For each confirmed finding, ask: **"what rule would have
caught this?"** and update the right place so it's caught automatically next time:

| If the finding is… | Feed it back into… |
|--------------------|--------------------|
| A recurring bug shape (race, ignored param, off-by-one) | `.agents/skills/ai-code-review/references/bug-patterns.md` (add an entry: signals + fix + first-seen) |
| A security class (injection, missing validation, leak) | `review-policy.md` → Emphasize / GenAI-API Security Checklist |
| A missing business guarantee | `product-context.md` → a new Acceptance Criterion (with P0/P1) + an acceptance test |
| A style / convention issue worth enforcing | `code-style.md` or `engineering-standards.md` |
| An invariant that needs fuzzing | a property test (adversarial-testing skill) + a note in its `references/patterns.md` |

The catalogs are living documents — the point is that the *next* review inherits this
finding as a rule, so the reviewer's coverage compounds over time instead of resetting.

## Where write-ups live
- Ephemeral (this review/PR): inline in the review output or MR discussion — no file needed.
- Worth keeping (a pattern others will hit): don't create a loose markdown file; put the
  reusable lesson directly into the catalog it belongs to (table above). Per repo hygiene in
  AGENTS.md, we don't accumulate standalone write-up files — we accumulate *rules*.
