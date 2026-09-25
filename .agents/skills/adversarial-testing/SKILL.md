---
name: adversarial-testing
description: Design adversarial tests that attack the code instead of confirming it — property-based tests (hypothesis) for invariants, canary-injection tests for data-leak/isolation, metamorphic tests for business relations, and differential tests for behavior-preserving changes. Use when user says "write property tests", "fuzz this", "test invariants", "adversarial tests", "test for leaks", "metamorphic test", "test the refactor is equivalent", or when reviewing code whose correctness rests on an invariant, a business relation, or a non-leak guarantee.
---

# Adversarial Testing

Example-based tests prove the cases you thought of. Adversarial tests attack the cases you
didn't. Two complementary techniques:

- **Property-based** (`hypothesis`): generate thousands of inputs and assert an *invariant*
  holds for all of them. Best for math, parsing, encode/decode, boundaries.
- **Canary-injection**: plant a known sentinel value where it must never appear, exercise
  the system, then assert the sentinel did NOT leak (into logs, responses, other tenants).
  Best for isolation and non-leak guarantees. (A "logging canary" pattern.)

**Related skills**: `business-alignment-review` (invariants often come from a P0 AC),
`test-quality-review` (property tests must still assert real behavior, not tautologies).

## When to Use
- Code whose correctness is an *invariant*: `total` never negative, refund ≤ captured,
  round-trip `decode(encode(x)) == x`, parser never panics on arbitrary bytes
- A guarantee phrased as "X never appears in Y": no secrets in logs, no cross-tenant reads
- A P0 Acceptance Criterion that states a universal ("always", "never", "for all")

## Part 1 — Property-Based Tests (hypothesis)

### Method
1. State the invariant as one sentence ("discounted total is in [0, subtotal]").
2. Pick a `hypothesis` strategy that covers the real input domain — including the nasty edges
   (0, negatives, huge values, empty, unicode). Don't over-constrain the strategy; that's how
   bugs hide.
3. Assert the invariant, not a specific output.
4. Let hypothesis shrink failures to a minimal counterexample; add that as a regression
   `@example`.

### Example
```python
from hypothesis import given, strategies as st


@given(subtotal=st.integers(min_value=0, max_value=10_000_00), vip=st.booleans())
def test_discount_total_within_bounds(subtotal, vip):
    """AC-1 [P0] invariant: discounted total is never negative, never exceeds subtotal."""
    total = apply_discount(subtotal, vip=vip)
    assert 0 <= total <= subtotal  # holds for ALL inputs, not just $100
```

### What makes a property test adversarial (not decorative)
- The strategy reaches the boundary/negative space (mutation test it: break the code, the
  property must fail).
- The assertion is the invariant, not `is not None`.
- Discovered counterexamples are pinned with `@example(...)` so they never regress.

## Part 2 — Canary-Injection Tests

### Method
1. Choose a **unique sentinel** unlikely to occur naturally (a UUID or tagged token).
2. Inject it as customer data / input on the path under test.
3. Exercise the code (call the endpoint, run the job, trigger the error path).
4. Assert the sentinel is ABSENT from every channel it must not reach: captured logs,
   the response to a *different* tenant, error messages, serialized events.

### Example
```python
import logging, uuid


def test_prompt_content_not_logged(caplog):
    """Security baseline: customer prompt content must never hit logs at INFO."""
    canary = f"CANARY-{uuid.uuid4()}"
    with caplog.at_level(logging.INFO):
        handle_request(prompt=canary)
    assert canary not in caplog.text  # no prompt leak into logs


def test_tenant_isolation(fake_store):
    """AC-5 [P0]: org A can never read org B's data."""
    canary = f"SECRET-{uuid.uuid4()}"
    save_order(org="B", note=canary)
    visible = export_orders(org="A")
    assert canary not in visible  # cross-tenant leak = fail
```

### Where these live
Isolation/leak canary tests are business guarantees → `tests/acceptance/` (cite the AC).
Pure-invariant property tests can live in `tests/unit/` unless they prove an AC.

## Part 3 — Metamorphic Tests (business relations, not single values)

Sometimes you can't state the exact expected output (the "test oracle problem") but you CAN
state a **relation** between inputs and outputs — and those relations are often the business
rule itself. Metamorphic testing asserts the relation holds when you transform the input.

Use when the correct answer is hard to hardcode but a business relationship is clear:
- **Monotonicity**: a VIP discount is always ≥ a non-VIP discount for the same order.
- **Adding shouldn't shrink**: adding a line item never decreases the order total.
- **Order-independence**: applying the same coupons in any order yields the same total.
- **Scaling**: doubling quantities doubles the subtotal (before rounding rules).

```python
from hypothesis import given, strategies as st


@given(subtotal=st.integers(min_value=0, max_value=10_000_00))
def test_vip_never_pays_more_than_regular(subtotal):
    """Business relation (AC-1): VIP total <= non-VIP total for the same order."""
    assert apply_discount(subtotal, vip=True) <= apply_discount(subtotal, vip=False)
```

The power: you don't need to know the "right" total — only that the *relationship* the
business promises must hold. A violated metamorphic relation is a business-logic bug even
when every single-value test passes.

## Part 4 — Differential Tests (behavior-preserving change)

When you optimize or refactor, the new code must produce the same results as the old for the
same inputs. This directly supports "write the naive-correct version first, then optimize
while preserving correctness."

```python
@given(data=st.lists(st.integers()))
def test_optimized_matches_reference(data):
    """Refactor guard: fast path must equal the naive reference for all inputs."""
    assert optimized_sort(list(data)) == sorted(data)  # reference = known-correct
```

Use it to guard: an optimization vs. its naive version, a rewrite vs. the old implementation
(keep the old one temporarily as the oracle), or two code paths that must agree (cache hit vs.
miss, sync vs. async). When the reference is retired, keep the fixed counterexamples as
regression cases.

## Reviewer Guidance (how this plugs into review)
When reviewing a change that rests on an invariant or a non-leak guarantee, a
COVERED-BUT-UNPROVEN gap is: "example tests exist, but no property/canary test attacks the
invariant." For a P0 invariant that's a HIGH finding — recommend the specific property or
canary test (see `references/patterns.md`).

## Troubleshooting

### hypothesis test is flaky / too slow
**Symptom**: intermittent failures or long runtimes.
**Fix**: a real flaky failure is usually a genuine edge-case bug — read the shrunk
counterexample before dismissing it. For speed, narrow the strategy's range or lower
`max_examples`, don't delete the test.

### Canary test passes but you're unsure it's real
**Symptom**: sentinel not found — but did the code path even run?
**Fix**: mutation-check it — make the code leak the canary on purpose; the test must fail.
A canary test that can't fail proves nothing.
