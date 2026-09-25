---
name: acceptance-testing
description: Write, maintain, and gap-check acceptance tests that prove business Acceptance Criteria (AC). Use when user says "write acceptance test for AC-X", "what ACs are untested", "prove this business rule", "test the requirement", "author test cases", or when a new AC is added to product-context.md. Focuses on business outcomes — not code quality, not coverage percentage.
---

# Acceptance Testing (QA-owned)

Write tests that **prove the business behaves correctly** — not that the code is
well-structured or has high coverage. Each test maps 1:1 to an Acceptance Criterion (AC) in
`.kiro/steering/product-context.md`.

This skill is the **forward** complement of `business-alignment-review` (which checks
existing tests backward). This one *creates* the tests. Together they are the two halves of
business alignment: author here, audit there — both keyed on the same `AC-<n>` ids so the
mapping is greppable in both directions.

**Related skills**: `business-alignment-review` (audit: are ACs covered?),
`adversarial-testing` (attack: metamorphic/canary/property for invariants),
`test-quality-review` (are the tests I wrote actually strong, or do they assert the mock?).

## Where the tests live (non-negotiable)

- **Path**: `tests/acceptance/` — never `tests/unit/`. Per `AGENTS.md`, `tests/unit/`
  proves the code is well-built; `tests/acceptance/` proves the product does what it must.
  Keeping them physically separate is what makes the AC→test mapping auditable.
- **File**: group by feature/workstream — `test_<feature>.py` (e.g. `test_discount.py`,
  `test_export.py`), mirroring how a test plan groups by workstream.
- **Function name = the outcome**: `test_export_returns_all_pages_when_over_1000_orders`,
  not `test_export_function`. The name alone should read like the AC.
- **Docstring cites the AC**: first line `"""AC-2 [P0]: <the business rule>."""` — this is
  the traceability link `business-alignment-review` and any coverage grep rely on.

## Principles

1. **Test the outcome, not the code.** A valid acceptance test can be written without reading
   the implementation — it only needs the AC's business language.
2. **Name = the outcome.** See "Where the tests live" above.
3. **Cite the AC in the docstring.** `"""AC-2 [P0]: ..."""` — makes the mapping greppable.
4. **One AC ≥ one test; one P0 AC ≥ happy path + boundary + negative.**
5. **Severity of an untested AC = its priority.** P0 untested = HIGH gap; P1 = MEDIUM.
6. **Cover the dimensions deliberately, mark N/A explicitly.** For each AC walk the coverage
   taxonomy below; a dimension that doesn't apply is recorded as `N/A (reason)`, never
   silently skipped — a missing dimension must be *visible*, not absent.

## Coverage taxonomy (per AC)

Adapted from the Pharmacy QA TestCaseGenerator's per-use-case dimensions. For each AC,
consider all six; generate the ones that apply, mark the rest `N/A` with a one-line reason:

| Dimension | Generate when | Example trigger |
|-----------|---------------|-----------------|
| **Positive** (happy path) | always | valid input → stated outcome |
| **Negative** | the AC forbids something / must reject | invalid input → 4xx not 500, no side effect |
| **Edge / boundary** | numeric bounds, empty, None, max, off-by-one | 0 orders, 1000 vs 1001, empty string |
| **Performance** | AC mentions scale, pagination, timeout, "all" | 1001-row export must loop pages |
| **Security** | AC is an auth / isolation / non-leak / injection guarantee | tenant-A cannot read tenant-B |
| **UI/UX** | only if the AC is user-facing behavior (usually `N/A` for backend) | error message shown, not a stack trace |

Map the adversarial styles onto the dimensions where they fit (see `adversarial-testing`):
Property/hypothesis → universal ACs ("always/never"); Metamorphic → relational ACs
(VIP ≤ regular); Differential → a reference impl exists; Canary-injection → the Security row.

## Structured test-case → pytest mapping

The TestCaseGenerator format is a document (Title/Preconditions/Steps/Expected/Priority).
Here the same structure lands as an executable pytest — each field has a home so the test
stays human-readable *and* runnable:

| Structured field | Lands in pytest as |
|------------------|--------------------|
| Test Case ID + traceability | docstring `AC-<n> [P0/P1]` citation |
| Title | the outcome-named test function + docstring one-liner |
| Priority | derived from the AC's P0/P1 (drives gap severity) |
| Preconditions | the **Arrange** block (fixtures, setup to reach the trigger) |
| Steps | the **Act** block (the call under test) |
| Expected Results | the **Assert** block — assert the real value (`== 1001`), not `is not None` |
| Coverage dimension | encoded in the function-name suffix (`..._when_over_1000_orders`) |

## Process

### Step 1: Load the ACs
Read `.kiro/steering/product-context.md` → Acceptance Criteria section. Note each AC's id,
priority (P0/P1), and the "When X, system does Y" statement.

### Step 2: Gap analysis
For each AC, search `tests/acceptance/` for a test whose docstring cites it (restrict to
`*.py` — a mention in a README is not a test):
```bash
grep -r --include='*.py' "AC-<N>" tests/acceptance/
```
Classify per dimension: PROVEN (test exists and would fail if the rule broke), UNTESTED
(no test), or PARTIAL (only happy-path exists; boundary/negative/perf/security missing per
the taxonomy).

### Step 3: Write the missing tests
For each gap, write a test in `tests/acceptance/` that:
- **Arrange** — constructs the minimal setup to reach the AC's trigger condition
- **Act** — exercises the behavior
- **Assert** — asserts the business outcome stated in the AC, on the real value
- Walks the **coverage taxonomy**: at minimum happy path + boundary + (for P0) a negative
  case proving the rule rejects the wrong behavior; add perf/security rows when they apply
- Only mocks external I/O (network, DB, clock, filesystem) — never the unit under test
- Verifies its own referents exist: before asserting on `export_orders(...)` or a fixture,
  confirm that symbol/fixture actually exists — don't write a test against an imagined API.

### Step 4: Mutation sanity check
For each new test, break the production code (flip a condition, off-by-one the bound): if the
test still passes, it isn't proving the AC — rewrite until it would fail. This is the same
check `test-quality-review` applies; run it on your own output before handing off.

## Example

**AC-2 [P0]**: "export all orders" returns every order across pages — a tenant with 1001
orders yields 1001 rows, not 1000.

```python
def test_export_returns_all_pages_when_over_1000_orders(fake_api):
    """AC-2 [P0]: export must loop pagination, never silently truncate."""
    # Arrange (Preconditions): API returns 2 pages (1000 + 1)
    fake_api.set_orders(["order"] * 1001)

    # Act (Steps): export
    result = export_orders(client_id="tenant-1")

    # Assert (Expected Results): business outcome — all 1001 delivered
    assert len(result) == 1001  # perf/pagination dimension


def test_export_zero_orders_returns_empty_with_header(fake_api):
    """AC-6 [P1]: 0 orders → empty file with header, not error."""
    fake_api.set_orders([])  # edge dimension
    result = export_orders(client_id="tenant-2")
    assert result == []  # or: CSV has only a header row
```

## Gap Report Format

Report coverage as an AC × dimension matrix so a hole is visible. `✓` = proven, `—` =
untested gap, `N/A` = deliberately not applicable (with reason), blank = not yet assessed.

```
## AC Coverage Report
| AC   | Pri | Positive | Negative | Edge | Perf | Security | UI/UX | Test file / function |
|------|-----|----------|----------|------|------|----------|-------|----------------------|
| AC-1 | P0  | ✓        | ✓        | ✓    | N/A  | N/A      | N/A   | test_discount.py::test_discount_total_within_bounds |
| AC-2 | P0  | ✓        | —        | ✓    | ✓    | N/A      | N/A   | test_export.py::test_export_returns_all_pages_when_over_1000_orders |
| AC-5 | P0  | ✓        | ✓        | N/A  | N/A  | ✓        | N/A   | test_orders.py::test_tenant_isolation_no_cross_read (canary) |
| AC-6 | P1  | —        | —        | —    | N/A  | N/A      | —     | UNTESTED — needs empty-export test |

Gaps (by severity): AC-2 negative [HIGH — P0], AC-6 all [MEDIUM — P1].
N/A reasons: AC-1 Perf — pure function, no I/O; AC-5 Edge — boolean guarantee, no boundary.
```
