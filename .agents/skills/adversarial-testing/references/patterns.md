# Adversarial Test Patterns (Living Catalog)

Loaded on demand by the adversarial-testing skill. Add a pattern when a review keeps
recommending the same kind of adversarial test. Each entry: when it applies + the strategy +
a concrete snippet.

## How to Add
1. Notice a recurring "this rests on an invariant/guarantee with no adversarial test" gap.
2. Generalize it to a reusable pattern below.
3. Reference the AC or bug-pattern it defends against.

---

## ROUND_TRIP (encode/decode, serialize/parse)
**Applies when**: code has `to_x`/`from_x`, serialize/deserialize, or any lossless transform.
**Invariant**: `decode(encode(v)) == v` for all v in the domain.
```python
@given(v=st.dictionaries(st.text(), st.integers()))
def test_json_round_trip(v):
    assert loads(dumps(v)) == v
```

## MONEY_BOUNDS (financial math)
**Applies when**: discounts, refunds, tax, currency. Defends AC-1, AC-4.
**Invariant**: result stays within business bounds; integer cents never overflow to float.
```python
@given(captured=st.integers(min_value=0), refunds=st.lists(st.integers(min_value=0)))
def test_refund_never_exceeds_capture(captured, refunds):
    assert sum(apply_refunds(captured, refunds)) <= captured
```

## PARSER_NEVER_PANICS (untrusted input)
**Applies when**: parsing user/network/file bytes. Defends against DoS + crashes.
**Invariant**: the parser returns a Result/None or raises a *declared* exception — never an
unhandled crash — on arbitrary bytes.
```python
@given(data=st.binary())
def test_parser_handles_arbitrary_bytes(data):
    try:
        parse(data)
    except ParseError:
        pass  # declared, fine
```

## IDEMPOTENCY (dedup, retries)
**Applies when**: mutating endpoints with an idempotency key. Defends AC-3.
**Invariant**: N identical submissions produce exactly one effect.
```python
@given(n=st.integers(min_value=1, max_value=20))
def test_idempotent_submit(n):
    key = "k"
    for _ in range(n):
        r = submit(order, idempotency_key=key)
    assert count_orders(key) == 1
```

## NO_LEAK_CANARY (logs / errors)
**Applies when**: any path handling secrets or customer content. Defends security baseline.
**Guarantee**: an injected sentinel never appears in logs or error messages.
```python
def test_secret_not_in_error(caplog):
    canary = f"CANARY-{uuid.uuid4()}"
    with pytest.raises(AuthError) as e:
        authenticate(token=canary)
    assert canary not in str(e.value) and canary not in caplog.text
```

## TENANT_ISOLATION_CANARY (multi-tenant reads)
**Applies when**: any cross-tenant data access. Defends AC-5.
**Guarantee**: data written under tenant B never surfaces to tenant A.
```python
def test_no_cross_tenant_read(fake_store):
    canary = f"SECRET-{uuid.uuid4()}"
    save(org="B", note=canary)
    assert canary not in export(org="A")
```

## METAMORPHIC_MONOTONICITY (business relation, no fixed oracle)
**Applies when**: you can't hardcode the right output but a business relation must hold —
pricing, ranking, scoring. Defends AC-1 and similar "always ≥ / never shrinks" rules.
**Relation**: transforming the input changes the output in a business-mandated direction.
```python
@given(subtotal=st.integers(min_value=0, max_value=10_000_00))
def test_vip_discount_at_least_regular(subtotal):
    assert apply_discount(subtotal, vip=True) <= apply_discount(subtotal, vip=False)


@given(items=st.lists(st.integers(min_value=1), min_size=1))
def test_adding_item_never_shrinks_total(items):
    assert order_total(items + [1]) >= order_total(items)
```

## DIFFERENTIAL_EQUIVALENCE (behavior-preserving change)
**Applies when**: optimizing/refactoring, or two paths that must agree (cache hit vs miss,
sync vs async, fast path vs naive). Guards "optimize while preserving correctness."
**Guarantee**: new/optimized output equals the reference output for all inputs.
```python
@given(data=st.lists(st.integers()))
def test_optimized_equals_reference(data):
    assert optimized(list(data)) == reference(list(data))  # reference = known-correct
```
