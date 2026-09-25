---
name: business-alignment-review
description: "Check whether code and tests satisfy the BUSINESS goal, not just code quality or line coverage. Use when reviewing a change that touches business logic, when tests were added/changed, or when you need to know if high coverage actually proves the required behavior. Maps each Acceptance Criterion in product-context.md to a test that would fail if the behavior broke, and flags coverage that executes code without asserting the business outcome."
---

# Business Alignment Review

High line coverage and clean unit tests answer "is the code well-built?" — they do NOT
answer "does it do what the business needs?". This skill checks the second question.

## Core distinction

| Code-quality signal (necessary, not sufficient) | Business-alignment signal (what this skill verifies) |
|---|---|
| Line/branch coverage % | Every Acceptance Criterion (AC) maps to a test |
| Test doesn't over-mock | Test asserts the *business outcome*, not just "no crash" |
| Assertions on real values | The asserted value is the value the *requirement* demands |
| Tests pass | A test would *fail* if the business rule were violated |

**Coverage's lie:** a test can execute a line (counts as covered) while asserting nothing
about the business rule that line implements. 100% coverage with the wrong assertions
proves nothing. This skill hunts that gap.

## Instructions

### Step 1: Load the business goals
- Read `.kiro/steering/product-context.md` — especially **Acceptance Criteria**, **Product
  Rules**, and **Data Invariants**.
- Read the change's stated intent (commit message, ticket, MR description).
- If a change touches business logic but you cannot find the governing AC/rule, that
  absence is itself a finding: "behavior changed with no stated business criterion."

### Step 2: Map criteria → tests (the core check)
For each relevant Acceptance Criterion / Product Rule (note its **P0/P1** priority):
1. Find the test(s) that claim to cover it — look in `tests/acceptance/` first (that's where
   AC-proving tests live by convention), then anywhere the AC id is cited.
2. Ask the decisive question: **"If I broke this business rule in the implementation, would
   any existing test fail?"** If no → the behavior is unproven regardless of coverage.
3. Check the assertion is against the **required** value, not just *a* value:
   - AC says "non-VIP gets 10% off" → a test asserting `calc() == 90` on a $100 order proves
     it; a test asserting `calc() is not None` does not.
4. Check the AC's **boundaries and negative cases** are proven, not just the happy path:
   - "export all orders" → is there a test with >1 page (e.g. 1001 items)? Happy path with
     5 items does not prove the business goal.
   - "refund ≤ captured" → is there a test that a refund exceeding the capture is rejected?

### Step 3: Distinguish the three outcomes (severity follows AC priority)
- **PROVEN** — an AC maps to a test that asserts the required outcome and would fail if
  the rule broke.
- **COVERED-BUT-UNPROVEN** — code runs in a test (coverage counts it) but no assertion ties
  it to the business rule. Report this — it's the most common false-confidence case.
- **UNCOVERED** — the AC has no test at all.

Severity for an unproven/uncovered AC is set by its priority:
- **P0** AC (correctness / security / money / launch-blocking) → **HIGH** finding, blocking.
- **P1** AC (important but degradable) → **MEDIUM** finding, non-blocking.

### Step 4: Use coverage as a pointer, not a verdict
- Coverage gaps are *hints* about where behavior might be unproven — inspect those lines
  against the ACs.
- Do NOT report "raise coverage to N%" as a finding. Report "AC-X (business rule) is not
  proven by any test," and cite the missing scenario.

## Output Format
```
## Business Alignment: [ALIGNED | GAPS FOUND]

### Criterion → Test Map
| Criterion | Test | Status | Note |
|-----------|------|--------|------|
| AC-2 export all pages | test_export_orders | COVERED-BUT-UNPROVEN | only tests 5 items; never exercises >1 page |
| AC-3 idempotency | (none) | UNCOVERED | duplicate-submit behavior has no test |

### Findings
**[SEVERITY]** <business rule> is not proven
- Requirement: <the AC / product rule>
- What the test actually checks: <e.g. asserts not-None, or only happy path>
- Missing scenario: <the boundary/negative case that proves the rule>
- Fix: <the specific test to add, named after the outcome>
```

Severity follows review-policy.md: an unproven rule on money, access control, or data
integrity is HIGH/CRITICAL; an unproven convenience feature is MEDIUM.
