---
name: test-quality-review
description: Detect test cheating, over-mocking, and weak assertions in Python tests. Use when user says "review the tests", "are these tests good", "check test quality", when a diff contains test files (test_*.py, *_test.py, tests/, conftest.py), or when existing tests are modified or deleted.
---

# Test Quality Review

A test that passes but proves nothing is worse than no test — it creates false confidence.
This skill checks whether tests verify behavior, not just execute code.

**Related skills**: `business-alignment-review` (whether tests prove the *business* rule, not
just avoid crashing), `ai-code-review` (the parent review this plugs into).

## When to Use
- When diff contains files matching: `test_*.py`, `*_test.py`, `tests/`, `conftest.py`
- When reviewing tests that accompany new implementation code
- When existing tests are modified or deleted

## Instructions

### Detection Criteria

**Over-Mocking (most common AI test cheat)**
- The unit under test is itself mocked (testing the mock, not the code)
- Return values are hardcoded to match assertions (tautological test)
- More than 3 mocks in a single test function (likely testing nothing real)
- Mock patches on internal methods of the class being tested

Example of a bad test (Python):
```python
def test_calculate_total():
    service = OrderService(Mock())
    service.calculate = Mock(return_value=100)  # mocked the thing we're testing!
    assert service.calculate() == 100  # always true, tests nothing
```

**Assertion Weakness**
- Only `assert result is not None` or `assert isinstance(...)` without checking values
- Assertions on implementation details (internal method call counts) rather than outputs
- Single assertion that matches mock setup verbatim

**Test Deletion / Weakening**
- Existing test removed without replacement
- Assertion made less specific (e.g., `assertEqual` → `assertIsNotNone`)
- Error/boundary test cases removed
- `@pytest.mark.skip` added without linked ticket or explanation

**Coverage Gaps**
- New public function with no corresponding test
- Happy path only — no error path, boundary, or empty-input test
- Async code tested only synchronously (missing `await` / event loop)

### Verification Method
For each suspected test quality issue:
1. Mentally "flip" a condition in the implementation — would this test catch it?
2. If the answer is no, the test provides false confidence
3. Check if the test describes a real scenario in its name/docstring

### Report Format
For each finding:
```
**[TEST-QUALITY · SEVERITY]** test_file:line
- Problem: <what's wrong with this test>
- Why it matters: <what regression would slip through>
- Fix: <concrete rewrite suggestion>
- Missing coverage: <what additional test cases are needed>
```

### Positive Signals (do NOT flag)
- Using fakes/stubs for external I/O (databases, HTTP, filesystem) — this is correct
- Fixture setup that creates real objects with controlled inputs
- Parameterized tests covering multiple scenarios
- Tests that verify error messages or exception types on failure paths
- Tests that assert on real return values so a failure shows the actual vs. expected value
  (prefer `assert result == 90` over `assert result is not None` — a clear failure message
  beats a vague one)

## Example

**Reviewing** a new `test_apply_discount` that does:
```python
svc = Pricing(Mock())
svc.calc = Mock(return_value=90)
assert svc.calc() == 90
```

**Actions**:
1. Over-mock check: `svc.calc` (the unit under test) is itself mocked → tautology.
2. Mutation check: change the real `calc` to return `-5` — this test still passes. It proves
   nothing.
3. Coverage check: the real discount logic is never executed.

**Result**:
```
**[TEST-QUALITY · HIGH]** test_pricing.py:3 — test mocks the method under test
- Problem: svc.calc is replaced with a Mock, so the assertion checks the mock, not the code
- Why it matters: any bug in the real calc() (wrong %, negative totals) ships green
- Fix: construct Pricing(FakeRepo(price=100)) and assert calc() == 90 against real logic
- Missing coverage: discount never negative (price=0), VIP vs non-VIP rate
```

## Troubleshooting

### Everything looks mocked but the tests are for an HTTP client
**Symptom**: many mocks, unsure if it's cheating.
**Fix**: mocking external I/O (network/DB/clock/filesystem) is correct and expected. Only
flag when the *unit under test itself* or its internal logic is mocked.

### You can't tell if an assertion is weak
**Symptom**: unsure whether `assert result` is enough.
**Fix**: apply the mutation test — mentally break the implementation. If no test fails, the
assertion is too weak regardless of how it looks.
