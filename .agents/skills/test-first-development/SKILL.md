---
name: test-first-development
description: Test-first / TDD discipline — define acceptance criteria and write tests BEFORE implementation. Use when starting any feature or bugfix, when a spec/AC is ready and code hasn't been written yet, or when the user says "write tests first", "TDD", "test-driven", "先写测试", "先定义验收标准". Enforces spec → failing test → minimal code → refactor.
---

# Test-First Development (TDD)

Write the acceptance criteria and the tests **before** the implementation. In an AI-assisted
lifecycle the biggest failure mode is code that looks right but does the wrong thing (see
AGENTS.md "four failure modes"). Test-first is the cheapest defense: the test encodes the
intended behavior *before* the model gets a chance to drift.

**Core principle:** if you didn't watch the test fail first, you don't know it tests the
right thing (a test that never failed might be asserting nothing).

**Related skills**: `acceptance-testing` (author the AC-proving tests this skill front-loads),
`self-review-loop` (the after-writing verifier), `business-alignment-review` (audits the
AC↔test mapping backward). This skill is the *forward, before-code* discipline that feeds them.

## When to Use
**Always, before writing implementation code:**
- New features, bug fixes, behavior changes, refactors.
- As soon as a spec / Acceptance Criteria exist and code does not yet.

**Exceptions (ask the human first):** throwaway prototypes, generated code, pure config.
> Thinking "skip it just this once"? That's the rationalization the rule exists to stop.

## The Order (non-negotiable)
1. **Define the criterion first.** Before any code, state the observable outcome as an
   Acceptance Criterion in `.kiro/steering/product-context.md` using the `AC-<n> · [P0/P1]`
   format (so `acceptance-testing` / `business-alignment-review` can grep it). For a bug: the
   AC is "the bug can't happen" — written as a reproduction.
2. **Write the test, watch it FAIL.** Author the test (unit in `tests/unit/`, business-AC in
   `tests/acceptance/`) and run it. A red test with a *clear* assertion (`assert x == 90`, not
   `assert x is not None`) proves the test exercises real behavior. **No failing test → no code.**
3. **Write the minimal code to pass.** Just enough to go green — no speculative extras
   (YAGNI). If you're adding code the test doesn't require, stop.
4. **Watch it PASS, then refactor.** Green bar first; then clean up with the test as a safety
   net. Re-run; still green.
5. **Hand off to the verifier.** Run `self-review-loop` before calling it done.

## Rules
- **Red before green, every time.** If a new test passes on the first run, you didn't watch
  it fail — change the expected value to confirm it can fail, then restore.
- **One behavior per test**; name it `test_<scenario>_<expected_outcome>`.
- **Assert on real values**, not liveness. The failure message must show actual vs expected.
- **Only mock external I/O** (network, DB, clock, filesystem) — never the unit under test.
- **Never weaken or delete a test to go green.** A failing test is information; fix the code.
- **Don't retry locally to make it pass** — a real failure must surface (see AGENTS.md).

## Classify tests on TWO independent axes (don't collapse them)
"Unit test" and "AI-generated test" are **not** two kinds of the same list — they live on
different axes. Any given test has a position on both:

- **Axis A — granularity (what it tests):** *unit* (a code unit behaves — "it runs") vs
  *acceptance* (a business AC holds — "it's what was asked"). Lives in `tests/unit/` vs
  `tests/acceptance/`.
- **Axis B — author / trust (can it gate?):** *self-authored* (written by the same actor
  that wrote the code — a human dev, or more often the AI alongside its own code) vs
  *independent* (written by a different actor — the Test-phase QA agent — from the ACs).

The gate-worthiness comes from **Axis B, not Axis A.** An AI-generated test can be a unit or
an acceptance test, but as long as it grades the AI's own code it's *self-authored* and
therefore **suspect** — the classic test-cheating failure mode (AGENTS.md): it may assert the
implementation's shape or a mock, pass trivially, or have been shaped to match the code
instead of the requirement.

Rules that follow:
- **Self-authored tests (incl. AI-generated) never count as acceptance.** They prove "it
  runs," useful during build; review them with `test-quality-review` and keep only those that
  assert real behavior. A green self-authored suite ≠ the Test phase passing.
- **The Test phase gate is independent + acceptance-level:** re-derived from the ACs (see
  `acceptance-testing`) by the QA agent, not the code author. This independence — not the
  unit/acceptance distinction — is why Test is a separate phase from Develop.
- Where they physically live is Axis A (`tests/unit/` vs `tests/acceptance/`); who may treat
  them as a gate is Axis B.

## In the delivery lifecycle
Test-first shifts **Test left**: the acceptance criteria are defined during **Research** (as
ACs) and the failing *acceptance* tests are written at the **start of Develop**, before the
implementation — authored from the ACs so they stay independent of whatever code (human- or
AI-written) later fills them in. When code is generated (in Kiro / by whoever implements), the
AC-proving tests already exist and immediately gate it; the Test phase then *verifies against
pre-written, independently-authored criteria* rather than accepting the code's own
self-authored unit/AI tests as proof.
