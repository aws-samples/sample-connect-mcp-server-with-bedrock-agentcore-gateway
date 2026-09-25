---
name: ai-code-review
description: Review Python code for semantic correctness, security, test quality, and spec compliance. Use when user says "review this", "review the diff", "check this code", "review my changes", "review this MR/PR", or before committing. Applies the .kiro/steering rules and reports only verified findings with evidence.
---

# AI Code Review

Review AI-generated or human-written Python code the way a senior engineer reviews a
junior's work: it compiles and passes tests, but that does not mean it is correct.

**Related skills**: `adversarial-verify` (challenge each MEDIUM+ finding), `test-quality-review`
(when the diff touches tests), `business-alignment-review` (when tests must prove a business
rule, not just cover lines).

## When to Use
- After writing or editing Python files
- Before committing changes
- When reviewing a diff or merge request

## Instructions

### Phase 1: Gather Context
1. Read the diff or changed files
2. Load `.kiro/steering/engineering-standards.md` for hard rules
3. Load `.kiro/steering/review-policy.md` for severity calibration and suppress/emphasize rules
4. Load `.kiro/steering/product-context.md` for business rules and architecture decisions
5. Identify the requirement or intent behind the change (from commit message, ticket, or user prompt)

### Phase 2: Analyze (check each dimension)

**Semantic Correctness** (most dangerous — silent failures)
- Does the code actually solve the stated problem, or just look like it does?
- Pagination: if calling a paginated API, does it loop until exhausted or only fetch one page?
- Boundary conditions: empty input, None/null, off-by-one, concurrent access
- Data source: is the correct data being operated on?

**Test Quality** (test cheating detection)
- Are tests asserting behavior (observable outputs) or implementation details?
- Is the unit under test being mocked? (testing the mock = useless test)
- Were existing tests deleted or weakened to make the build pass?
- Are there boundary/error-path tests, not just happy path?
- Mutation test: if you flip a condition in the implementation, would any test fail?

**Security**
- External input validated before use?
- No hardcoded secrets, tokens, account IDs?
- SQL uses parameterized queries?
- No `shell=True` in subprocess calls?
- Authentication and authorization on public endpoints?

**Spec & Contract Compliance**
- Does the change respect API contracts documented in product-context.md?
- Are schema/spec files updated when API behavior changes?
- Do data invariants still hold?

**Known bug patterns** — scan the diff against the recurring classes in
`references/bug-patterns.md` (pagination-not-looped, inverted boolean, ignored parameter,
check-then-act race, validation-skipping fast path, API format break, synthetic ID
collision). Load that file only when a dimension above smells like one of these; each entry
has the signal to grep for and the fix. When you confirm a NEW recurring class, add it there.

**Simplicity & scope** (quality, not correctness) — is the change bigger, more abstract, or
broader than the task needs? Bloat, needless abstraction, dead code, and scope creep (touching
unrelated code/comments) are the most common AI-code annoyances. For a large or over-built
diff, run the `simplification-review` skill — the "couldn't you just do this instead?" pass.

### Phase 3: Verify Each Finding
For each potential finding:
1. Confirm the cited code actually exists at the stated location (verbatim match)
2. Confirm the trigger condition is realistic (not purely theoretical)
3. Apply severity calibration from review-policy.md
4. Check against suppress list — drop if matched
5. Check against emphasize list — upgrade if matched
6. If you cannot demonstrate the issue with a concrete scenario, move to "Needs Confirmation" rather than reporting as a defect

### Phase 4: Report
For each confirmed finding, output:
```
**[SEVERITY]** file:line — short summary
- Evidence: <exact code snippet>
- Impact: <what goes wrong, under what conditions>
- Fix: <concrete suggestion>
- Test needed: <what test to add>
```

If zero findings survive verification, report CLEAN with a brief note on what was checked.

### Escalate immediately (don't just file a finding)
Flag these to a human right away, tagged CRITICAL, regardless of the automated gate:
- Security: auth/authz bypass, injection, secret exposure
- Data loss: incorrect deletion, missing backup, silent truncation (e.g. pagination drop)
- Correctness on money/billing paths
These map to the "emphasize" rules in review-policy.md and should never be auto-dispositioned.

### Phase 5: Close the loop
For each confirmed HIGH/CRITICAL finding, follow `findings-writeup.md`: record it in the
write-up format AND feed the lesson back into the right catalog (bug-patterns.md, an
Emphasize rule, or a new Acceptance Criterion) so the next review catches this class
automatically. A finding that produces no rule is a finding you'll see again.

## Output Format
- Findings sorted by severity (CRITICAL > HIGH > MEDIUM > LOW)
- Each finding must have evidence, impact, fix suggestion, and test recommendation
- Separate section for "Needs Confirmation" items (suspected but unproven)
- Never report purely stylistic issues unless they match an "emphasize" rule

## Example

**User**: "Review this diff" — the diff adds `export_orders()` that calls
`api.list_orders(client_id, limit=1000)` and writes `resp.items` to CSV.

**Actions**:
1. Load steering; requirement (commit msg) says "export ALL orders".
2. Analyze: `list_orders` is paginated (`next_token` in product-context.md), but the code
   fetches one page and never loops → semantic correctness bug.
3. Verify: cite `export.py:5` verbatim; trigger = any tenant with >1000 orders; realistic.
4. Severity: HIGH (silent data loss on a core path), matches an "emphasize" rule.

**Result**:
```
**[HIGH]** export.py:5 — export_orders only fetches the first page
- Evidence: `resp = api.list_orders(client_id, limit=1000)` then `write_csv(resp.items)`
- Impact: tenants with >1000 orders silently lose all rows past 1000; violates "export all"
- Fix: loop on `resp.next_token` until it is None, accumulating items
- Test needed: test_export_returns_all_pages_when_over_1000_orders
```

## Troubleshooting

### The reviewer reports style nits despite the suppress list
**Symptom**: findings about import order, docstrings, naming.
**Fix**: re-load `.kiro/steering/review-policy.md`; these are on the suppress list. Only
report style that matches an explicit "emphasize" rule.

### A finding cites a line that isn't in the diff
**Symptom**: file:line points outside the changed hunks.
**Fix**: this is an unverified finding — move it to "Needs Confirmation" or drop it. Every
reported finding's evidence must appear verbatim in the diff (see `adversarial-verify`).
